"""
image_editor.py  —  Instagram Image Processor
Resize, crop, filter, and optimise images to meet Instagram's exact specs
before handing them off to poster.py for upload.

INSTAGRAM DIMENSION REFERENCE (2025 specs)
──────────────────────────────────────────
  Feed square     1080 x 1080   (1:1)
  Feed portrait   1080 x 1350   (4:5)   ← best for reach in 2025
  Feed landscape  1080 x 566    (1.91:1)
  Story / Reel    1080 x 1920   (9:16)
  Carousel        all slides must match first slide — portrait (4:5) recommended

PIXEL TARGET: 1080px wide, JPEG at 80–90% quality.
Instagram recompresses anything above 1080px anyway, so we never exceed it.

USAGE (standalone or via CLI)
──────────────────────────────
  from image_editor import ImageEditor

  editor = ImageEditor("photo.jpg")
  editor.resize("portrait")              # smart-crop to 4:5
  editor.apply_filter("warm")            # warming tone
  editor.adjust(brightness=1.1, contrast=1.05, saturation=1.2)
  result = editor.save()                 # writes to processed/ subfolder
  print(result)                          # path to the processed file

  # One-liner bulk process for carousel
  paths = process_batch(
      ["img1.jpg", "img2.jpg", "img3.jpg"],
      preset="portrait",
      filter_name="warm",
  )

FILTERS AVAILABLE
─────────────────
  none        original (just resize + optimise)
  warm        golden/sunset warmth — slightly boost reds and yellows
  cool        blue-toned, clean editorial look
  faded       lifted blacks, low contrast, matte film look
  vivid       punchy saturation boost
  matte       flat matte with faded shadows
  bw          black and white
  dramatic    high contrast, desaturated shadows
  soft        gentle blur + pastel brightness lift
  vintage     warm sepia-toned grain effect

ADJUSTMENTS (all multipliers — 1.0 = no change)
──────────────────────────────────────────────────
  brightness    0.5 (dark) → 2.0 (bright)   default 1.0
  contrast      0.5 (flat) → 2.0 (punchy)   default 1.0
  saturation    0.0 (B&W)  → 3.0 (vivid)    default 1.0
  sharpness     0.0 (blur) → 3.0 (sharp)    default 1.0
"""

import os
import math
import random
from pathlib import Path
from typing   import Optional
from datetime import datetime

from PIL import (
    Image, ImageFilter, ImageEnhance,
    ImageOps, ImageDraw,
)

# ─────────────────────────────────────────────────────────────────────────────
# INSTAGRAM SIZE PRESETS
# ─────────────────────────────────────────────────────────────────────────────

PRESETS = {
    # Feed
    "square":    (1080, 1080),   # 1:1
    "portrait":  (1080, 1350),   # 4:5  ← recommended in 2025
    "landscape": (1080,  566),   # 1.91:1
    # Story / Reel
    "story":     (1080, 1920),   # 9:16
    "reel":      (1080, 1920),   # 9:16
    # Carousel — all slides must match first; portrait is best
    "carousel":  (1080, 1350),   # 4:5
}

PRESET_ALIASES = {
    "1:1":     "square",
    "4:5":     "portrait",
    "9:16":    "story",
    "16:9":    "landscape",
}

# JPEG quality — 85 hits the sweet spot: sharp but doesn't trigger
# heavy recompression on Instagram's servers
JPEG_QUALITY = 85

# Output subfolder (relative to source image)
PROCESSED_DIR = "processed"


# ─────────────────────────────────────────────────────────────────────────────
# FILTER DEFINITIONS
# Each filter is a function: Image → Image
# ─────────────────────────────────────────────────────────────────────────────

def _apply_none(img: Image.Image) -> Image.Image:
    return img


def _apply_warm(img: Image.Image) -> Image.Image:
    """Golden warmth — boost reds slightly, lift yellows."""
    img = ImageEnhance.Color(img).enhance(1.15)
    r, g, b = img.split()
    r = r.point(lambda x: min(255, int(x * 1.08)))
    b = b.point(lambda x: int(x * 0.93))
    return Image.merge("RGB", (r, g, b))


def _apply_cool(img: Image.Image) -> Image.Image:
    """Blue-toned editorial look — desaturate slightly, push blues."""
    img = ImageEnhance.Color(img).enhance(0.90)
    r, g, b = img.split()
    b = b.point(lambda x: min(255, int(x * 1.10)))
    r = r.point(lambda x: int(x * 0.95))
    return Image.merge("RGB", (r, g, b))


def _apply_faded(img: Image.Image) -> Image.Image:
    """Lifted blacks, low contrast matte film look."""
    img = ImageEnhance.Contrast(img).enhance(0.78)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    # Lift the shadows: compress range so blacks are never pure black
    img = img.point(lambda x: int(x * 0.88 + 28))
    return img


def _apply_vivid(img: Image.Image) -> Image.Image:
    """Punchy saturation + slight contrast boost."""
    img = ImageEnhance.Color(img).enhance(1.45)
    img = ImageEnhance.Contrast(img).enhance(1.10)
    return img


def _apply_matte(img: Image.Image) -> Image.Image:
    """Flat matte: faded shadows + desaturated."""
    img = ImageEnhance.Color(img).enhance(0.80)
    img = ImageEnhance.Contrast(img).enhance(0.82)
    img = img.point(lambda x: int(x * 0.85 + 22))
    return img


def _apply_bw(img: Image.Image) -> Image.Image:
    """Pure black and white via luminosity conversion."""
    img = ImageOps.grayscale(img)
    return img.convert("RGB")


def _apply_dramatic(img: Image.Image) -> Image.Image:
    """High contrast, crushed blacks, desaturated."""
    img = ImageEnhance.Color(img).enhance(0.70)
    img = ImageEnhance.Contrast(img).enhance(1.35)
    img = ImageEnhance.Brightness(img).enhance(0.95)
    return img


def _apply_soft(img: Image.Image) -> Image.Image:
    """Subtle glow: gentle gaussian blur + pastel brightness."""
    blurred = img.filter(ImageFilter.GaussianBlur(radius=1.2))
    img     = Image.blend(img, blurred, 0.35)
    img     = ImageEnhance.Brightness(img).enhance(1.06)
    img     = ImageEnhance.Color(img).enhance(0.92)
    return img


def _apply_vintage(img: Image.Image) -> Image.Image:
    """Warm sepia tone + slight vignette effect."""
    # Desaturate
    grey = ImageOps.grayscale(img).convert("RGB")
    img  = Image.blend(img, grey, 0.35)
    # Warm sepia shift
    r, g, b = img.split()
    r = r.point(lambda x: min(255, int(x * 1.12 + 10)))
    g = g.point(lambda x: int(x * 1.02))
    b = b.point(lambda x: int(x * 0.82))
    img = Image.merge("RGB", (r, g, b))
    # Low contrast lift
    img = img.point(lambda x: int(x * 0.88 + 18))
    # Soft vignette
    img = _add_vignette(img, strength=0.30)
    return img


def _add_vignette(img: Image.Image, strength: float = 0.4) -> Image.Image:
    """Add a subtle circular vignette (darken edges)."""
    w, h    = img.size
    mask    = Image.new("L", (w, h), 255)
    draw    = ImageDraw.Draw(mask)
    cx, cy  = w // 2, h // 2
    steps   = 80
    for i in range(steps):
        t     = i / steps
        alpha = int(255 * (1.0 - strength * t * t))
        rx    = int(cx * (1.0 - t * 0.95))
        ry    = int(cy * (1.0 - t * 0.95))
        draw.ellipse(
            [cx - rx, cy - ry, cx + rx, cy + ry],
            fill=alpha,
        )
    dark    = Image.new("RGB", (w, h), (0, 0, 0))
    img     = Image.composite(img, dark, mask)
    return img


FILTERS = {
    "none":     _apply_none,
    "warm":     _apply_warm,
    "cool":     _apply_cool,
    "faded":    _apply_faded,
    "vivid":    _apply_vivid,
    "matte":    _apply_matte,
    "bw":       _apply_bw,
    "dramatic": _apply_dramatic,
    "soft":     _apply_soft,
    "vintage":  _apply_vintage,
}

FILTER_DESCRIPTIONS = {
    "none":     "No filter — resize and optimise only",
    "warm":     "Golden warmth — sunsets, portraits, food",
    "cool":     "Blue-toned editorial — architecture, fashion",
    "faded":    "Lifted blacks, matte film look",
    "vivid":    "Punchy saturation boost",
    "matte":    "Flat matte, faded shadows",
    "bw":       "Black and white",
    "dramatic": "High contrast, crushed blacks",
    "soft":     "Gentle glow, pastel brightness",
    "vintage":  "Warm sepia tone with vignette",
}


# ─────────────────────────────────────────────────────────────────────────────
# SMART CROP — centre-gravity resize
# ─────────────────────────────────────────────────────────────────────────────

def smart_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Resize to fill target dimensions, then centre-crop.
    Never stretches or adds bars — always fills the frame.
    """
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio    = src_w / src_h

    if src_ratio > target_ratio:
        # Source is wider — fit height, crop sides
        new_h = target_h
        new_w = int(src_w * (target_h / src_h))
    else:
        # Source is taller — fit width, crop top/bottom
        new_w = target_w
        new_h = int(src_h * (target_w / src_w))

    img  = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    img  = img.crop((left, top, left + target_w, top + target_h))
    return img


def fit_with_padding(
    img: Image.Image,
    target_w: int,
    target_h: int,
    pad_color: tuple = (255, 255, 255),
) -> Image.Image:
    """
    Fit image inside target without cropping — pads with pad_color.
    Use this instead of smart_crop when you don't want any content lost.
    """
    img.thumbnail((target_w, target_h), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), pad_color)
    offset = ((target_w - img.width) // 2, (target_h - img.height) // 2)
    canvas.paste(img, offset)
    return canvas


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EDITOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class ImageEditor:
    """
    Chainable single-image editor.

    Usage:
        result = (ImageEditor("photo.jpg")
                  .resize("portrait")
                  .apply_filter("warm")
                  .adjust(brightness=1.1, saturation=1.2)
                  .save())
    """

    def __init__(self, path: str | Path):
        self.source_path = Path(path)
        if not self.source_path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        self._img = Image.open(self.source_path).convert("RGB")
        self._ops: list = []   # log of operations applied

    # ── RESIZE / CROP ─────────────────────────────────────────────────────────

    def resize(
        self,
        preset: str = "portrait",
        mode:   str = "crop",
        pad_color: tuple = (255, 255, 255),
    ) -> "ImageEditor":
        """
        Resize image to an Instagram size preset.

        Args:
            preset:    square | portrait | landscape | story | reel | carousel
                       or raw e.g. "1:1", "4:5", "9:16"
            mode:      'crop'    — smart centre-crop (default, no bars)
                       'pad'     — letterbox/pillarbox with pad_color
            pad_color: RGB tuple for padding (default white)
        """
        preset = PRESET_ALIASES.get(preset, preset)
        if preset not in PRESETS:
            raise ValueError(
                f"Unknown preset '{preset}'. "
                f"Choose from: {', '.join(PRESETS)}"
            )

        w, h = PRESETS[preset]
        if mode == "crop":
            self._img = smart_crop(self._img, w, h)
        else:
            self._img = fit_with_padding(self._img, w, h, pad_color)

        self._ops.append(f"resize:{preset}:{w}x{h}:{mode}")
        return self

    def resize_custom(self, width: int, height: int, mode: str = "crop") -> "ImageEditor":
        """Resize to exact pixel dimensions."""
        if mode == "crop":
            self._img = smart_crop(self._img, width, height)
        else:
            self._img = fit_with_padding(self._img, width, height)
        self._ops.append(f"resize:custom:{width}x{height}:{mode}")
        return self

    # ── FILTER ────────────────────────────────────────────────────────────────

    def apply_filter(self, name: str) -> "ImageEditor":
        """
        Apply a named filter.
        Available: none, warm, cool, faded, vivid, matte, bw,
                   dramatic, soft, vintage
        """
        name = name.lower().strip()
        if name not in FILTERS:
            raise ValueError(
                f"Unknown filter '{name}'. "
                f"Available: {', '.join(FILTERS)}"
            )
        if name != "none":
            self._img = FILTERS[name](self._img)
            self._ops.append(f"filter:{name}")
        return self

    # ── MANUAL ADJUSTMENTS ────────────────────────────────────────────────────

    def adjust(
        self,
        brightness: float = 1.0,
        contrast:   float = 1.0,
        saturation: float = 1.0,
        sharpness:  float = 1.0,
    ) -> "ImageEditor":
        """
        Fine-tune image properties. All values are multipliers (1.0 = no change).
        Brightness  0.5–2.0  |  Contrast  0.5–2.0
        Saturation  0.0–3.0  |  Sharpness 0.0–3.0
        """
        if brightness != 1.0:
            self._img = ImageEnhance.Brightness(self._img).enhance(brightness)
        if contrast != 1.0:
            self._img = ImageEnhance.Contrast(self._img).enhance(contrast)
        if saturation != 1.0:
            self._img = ImageEnhance.Color(self._img).enhance(saturation)
        if sharpness != 1.0:
            self._img = ImageEnhance.Sharpness(self._img).enhance(sharpness)

        adj = [f"b={brightness}", f"c={contrast}",
               f"s={saturation}", f"sh={sharpness}"]
        self._ops.append(f"adjust:{','.join(adj)}")
        return self

    # ── ROTATION & FLIP ───────────────────────────────────────────────────────

    def rotate(self, degrees: float, expand: bool = True) -> "ImageEditor":
        """Rotate image. Common values: 90, 180, 270."""
        self._img = self._img.rotate(degrees, expand=expand, resample=Image.BICUBIC)
        self._ops.append(f"rotate:{degrees}")
        return self

    def flip_horizontal(self) -> "ImageEditor":
        self._img = ImageOps.mirror(self._img)
        self._ops.append("flip:horizontal")
        return self

    def flip_vertical(self) -> "ImageEditor":
        self._img = ImageOps.flip(self._img)
        self._ops.append("flip:vertical")
        return self

    # ── AUTO ENHANCE ──────────────────────────────────────────────────────────

    def auto_enhance(self) -> "ImageEditor":
        """
        Gentle automatic correction — equalise tone range and lightly
        sharpen. Conservative enough not to ruin a photo, useful for
        raw or flat shots.
        """
        # Auto-levels: stretch histogram to full range
        self._img = ImageOps.autocontrast(self._img, cutoff=1)
        # Light sharpening
        self._img = ImageEnhance.Sharpness(self._img).enhance(1.15)
        self._ops.append("auto_enhance")
        return self

    # ── VIGNETTE ─────────────────────────────────────────────────────────────

    def vignette(self, strength: float = 0.35) -> "ImageEditor":
        """Add a soft edge vignette. strength 0.0–1.0."""
        self._img = _add_vignette(self._img, strength)
        self._ops.append(f"vignette:{strength}")
        return self

    # ── SAVE ─────────────────────────────────────────────────────────────────

    def save(
        self,
        output_path: str | Path = None,
        quality: int = JPEG_QUALITY,
    ) -> Path:
        """
        Save the processed image as JPEG.

        If output_path is not given, saves to a 'processed/' subdirectory
        next to the source file with a timestamp suffix.

        Returns the absolute path to the saved file.
        """
        if output_path:
            out = Path(output_path)
        else:
            proc_dir = self.source_path.parent / PROCESSED_DIR
            proc_dir.mkdir(exist_ok=True)
            stem = self.source_path.stem
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            out  = proc_dir / f"{stem}_{ts}.jpg"

        self._img.save(str(out), "JPEG", quality=quality, optimize=True)
        return out.resolve()

    # ── INFO ─────────────────────────────────────────────────────────────────

    @property
    def size(self) -> tuple:
        return self._img.size

    @property
    def ops_log(self) -> list:
        return list(self._ops)

    def info(self) -> dict:
        w, h = self._img.size
        return {
            "source":      str(self.source_path),
            "current_size": f"{w}x{h}",
            "aspect_ratio": f"{w/h:.3f}",
            "ops_applied":  self._ops,
        }


# ─────────────────────────────────────────────────────────────────────────────
# BATCH PROCESSING
# ─────────────────────────────────────────────────────────────────────────────

def process_batch(
    image_paths: list,
    preset:       str   = "portrait",
    filter_name:  str   = "none",
    brightness:   float = 1.0,
    contrast:     float = 1.0,
    saturation:   float = 1.0,
    sharpness:    float = 1.0,
    auto_enhance: bool  = False,
    output_dir:   str   = None,
    quality:      int   = JPEG_QUALITY,
) -> list:
    """
    Process a list of images with identical settings.
    Used for carousels — ensures all slides are the same size/style.

    Returns list of output Path objects (same order as input).
    """
    results = []
    for path in image_paths:
        try:
            editor = ImageEditor(path)
            if preset and preset != "none":
                editor.resize(preset)
            if auto_enhance:
                editor.auto_enhance()
            if filter_name and filter_name != "none":
                editor.apply_filter(filter_name)
            editor.adjust(brightness, contrast, saturation, sharpness)

            if output_dir:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                stem = Path(path).stem
                ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
                out  = Path(output_dir) / f"{stem}_{ts}.jpg"
            else:
                out = None

            saved = editor.save(out, quality=quality)
            results.append(saved)
        except Exception as e:
            results.append(None)
            print(f"  [WARN] Could not process {path}: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# QUICK ANALYSE — tell the user what preset fits their image
# ─────────────────────────────────────────────────────────────────────────────

def analyse_image(path: str | Path) -> dict:
    """
    Read an image and suggest the best Instagram preset for it.
    Returns a dict with dimensions, current ratio, suggested preset,
    and whether it needs cropping.
    """
    img    = Image.open(path)
    w, h   = img.size
    ratio  = w / h
    size_kb = Path(path).stat().st_size // 1024

    # Determine closest preset
    if ratio >= 1.7:
        suggested = "landscape"
        note      = "Wide photo — will be centre-cropped to 1.91:1 for feed"
    elif ratio >= 0.95:
        suggested = "square"
        note      = "Roughly square — good for 1:1"
    elif ratio >= 0.78:
        suggested = "portrait"
        note      = "Portrait-ish — ideal for 4:5 (recommended for reach)"
    elif ratio >= 0.55:
        suggested = "story"
        note      = "Tall image — good fit for 9:16 story format"
    else:
        suggested = "story"
        note      = "Very tall — story format, will crop top/bottom"

    # Warning if below 1080px wide
    quality_warning = None
    if w < 320:
        quality_warning = "Image is below 320px wide — Instagram will upscale and it will look blurry"
    elif w < 1080:
        quality_warning = f"Image is {w}px wide — Instagram prefers 1080px; consider upscaling before posting"

    return {
        "file":             str(path),
        "dimensions":       f"{w}x{h}",
        "size_kb":          size_kb,
        "aspect_ratio":     f"{ratio:.3f}",
        "suggested_preset": suggested,
        "note":             note,
        "quality_warning":  quality_warning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PREVIEW HELPER — generate small thumbnail for quick CLI preview
# ─────────────────────────────────────────────────────────────────────────────

def make_preview(path: str | Path, max_size: int = 300) -> Path:
    """
    Generate a small preview thumbnail (max 300px) next to the source.
    Useful for quick visual checks before posting.
    Returns the preview path.
    """
    p    = Path(path)
    img  = Image.open(p).convert("RGB")
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    out  = p.parent / f"{p.stem}_preview.jpg"
    img.save(str(out), "JPEG", quality=70)
    return out.resolve()