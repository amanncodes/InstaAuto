"""
poster.py  —  Instagram Content Publishing
Handles single photos, carousels, photo stories, and video stories.
Integrates with instagrapi's full feature set:
  - Location tagging (posts + stories)
  - User tagging / mentions (posts + stories)
  - Hashtag stickers (stories)
  - Link stickers (stories)
  - Music on stories via extra_data injection (best-effort)
  - Music on reels via canonical track ID
  - Post queue: posts/queue/ → posts/done/ or posts/failed/
  - Every publish is recorded in stats_store (posts table)

Queue folder layout
───────────────────
  posts/
    queue/
      my_post/
        image.jpg          ← single photo
        meta.yaml
      carousel_post/
        01.jpg
        02.jpg
        03.jpg
        meta.yaml
      story_post/
        image.jpg
        meta.yaml
    done/                  ← moved here after success
    failed/                ← moved here after failure, error.txt added

meta.yaml reference
───────────────────
  type: photo              # photo | carousel | story_photo | story_video
  caption: "text here"     # posts only
  hashtags: [tag1, tag2]   # appended to caption automatically
  accounts: [user1]        # which accounts to post from — empty = all active
  scheduled_time: "now"    # "now" or "YYYY-MM-DD HH:MM"

  # Location (posts + stories)
  location: "Mumbai, India"        # searched via Instagram API
  location_lat: 19.076             # used as fallback if search fails
  location_lng: 72.877

  # User tags on posts  [{username, x, y}]
  usertags:
    - username: someuser
      x: 0.5
      y: 0.5

  # Story-specific
  mentions: [user1, user2]         # @mention stickers
  hashtag_sticker: photography     # single hashtag sticker
  link: "https://example.com"      # link sticker (requires 10k+ followers)

  # Music — stories (best-effort via extra_data)
  music_track_id: "18159860503036324"   # canonical Instagram music ID
  music_start_ms: 0                     # start position in ms

  # Music — story/reel from a known reel shortcode
  music_from_reel: "ABC123xyz"          # shortcode of reel to borrow music from
"""

import os
import time
import random
import shutil
import logging
from pathlib  import Path
from datetime import datetime

import yaml
from image_editor import ImageEditor, process_batch as _process_batch, analyse_image

from instagrapi.types import (
    Location, StoryMention, StoryLink,
    StoryHashtag, StoryLocation, UserShort,
    Usertag,
)
from instagrapi.exceptions import (
    ClientError, MediaNotFound, UserNotFound,
    FeedbackRequired, RateLimitError,
)

import stats_store

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

QUEUE_DIR  = Path("posts/queue")
DONE_DIR   = Path("posts/done")
FAILED_DIR = Path("posts/failed")

for _d in (QUEUE_DIR, DONE_DIR, FAILED_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# LOGGER
# ─────────────────────────────────────────────────────────────────────────────

def _log(username: str) -> logging.Logger:
    return logging.getLogger(username)


# ─────────────────────────────────────────────────────────────────────────────
# META YAML HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def load_meta(post_dir: Path) -> dict:
    """Load and parse a post's meta.yaml. Returns {} if not found."""
    meta_file = post_dir / "meta.yaml"
    if not meta_file.exists():
        return {}
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logging.warning(f"Could not parse meta.yaml in {post_dir}: {e}")
        return {}


def build_caption(meta: dict) -> str:
    """
    Build the final caption from meta.yaml.
    Appends hashtags on a new line if provided.
    """
    caption   = meta.get("caption", "")
    hashtags  = meta.get("hashtags", [])
    if hashtags:
        tag_str = " ".join(f"#{t.lstrip('#')}" for t in hashtags)
        caption = f"{caption}\n\n{tag_str}".strip()
    return caption


def collect_images(post_dir: Path) -> list:
    """
    Return sorted list of image paths from a post folder.
    Accepts jpg, jpeg, png, webp.
    """
    exts   = {".jpg", ".jpeg", ".png", ".webp"}
    images = sorted(
        p for p in post_dir.iterdir()
        if p.suffix.lower() in exts
    )
    return images


def collect_video(post_dir: Path) -> Path | None:
    """Return the first video file found in the folder, or None."""
    exts = {".mp4", ".mov", ".avi"}
    for p in post_dir.iterdir():
        if p.suffix.lower() in exts:
            return p
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LOCATION RESOLVER
# ─────────────────────────────────────────────────────────────────────────────

def resolve_location(cl, meta: dict) -> Location | None:
    """
    Try to resolve a Location object from meta.yaml.
    First tries searching by name, falls back to lat/lng, returns None if
    neither is provided or search fails.
    """
    name = meta.get("location")
    lat  = meta.get("location_lat")
    lng  = meta.get("location_lng")

    if not name and not (lat and lng):
        return None

    if name:
        try:
            results = cl.location_search(lat or 0.0, lng or 0.0, name)
            if results:
                r = results[0]
                return Location(
                    pk   = r.pk,
                    name = r.name,
                    lat  = r.lat,
                    lng  = r.lng,
                )
        except Exception:
            pass  # fall through to raw lat/lng

    if lat and lng:
        return Location(name=name or "Unknown", lat=lat, lng=lng)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# USERTAGS  (for posts)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_usertags(cl, meta: dict) -> list:
    """
    Build a list of Usertag objects from meta.yaml usertags list.
    Skips any username that can't be resolved.
    """
    raw  = meta.get("usertags", [])
    tags = []
    for item in raw:
        try:
            uid  = cl.user_id_from_username(item["username"])
            info = cl.user_info(uid)
            tags.append(Usertag(
                user = UserShort(
                    pk       = uid,
                    username = item["username"],
                    full_name= info.full_name,
                ),
                x = item.get("x", 0.5),
                y = item.get("y", 0.5),
            ))
        except Exception as e:
            logging.warning(f"Could not tag @{item.get('username')}: {e}")
    return tags


# ─────────────────────────────────────────────────────────────────────────────
# STORY STICKER BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def build_story_mentions(cl, meta: dict) -> list:
    """Build StoryMention list from meta.yaml mentions: [user1, user2]"""
    mentions = []
    for uname in meta.get("mentions", []):
        try:
            uid  = cl.user_id_from_username(uname)
            info = cl.user_info(uid)
            mentions.append(StoryMention(
                user = UserShort(
                    pk       = uid,
                    username = uname,
                    full_name= info.full_name,
                ),
                x=0.5, y=0.5, width=0.5, height=0.1,
            ))
        except Exception as e:
            logging.warning(f"Could not build mention for @{uname}: {e}")
    return mentions


def build_story_hashtag(cl, meta: dict) -> list:
    """Build a single StoryHashtag sticker if hashtag_sticker is set."""
    tag = meta.get("hashtag_sticker")
    if not tag:
        return []
    try:
        tag = tag.lstrip("#")
        return [StoryHashtag(
            hashtag = cl.hashtag_info(tag),
            x=0.5, y=0.8, width=0.4, height=0.08,
        )]
    except Exception as e:
        logging.warning(f"Could not build hashtag sticker #{tag}: {e}")
        return []


def build_story_location(cl, meta: dict) -> list:
    """Build a StoryLocation sticker if location is set."""
    loc = resolve_location(cl, meta)
    if not loc:
        return []
    try:
        return [StoryLocation(
            location = loc,
            x=0.5, y=0.2, width=0.5, height=0.08,
        )]
    except Exception as e:
        logging.warning(f"Could not build story location sticker: {e}")
        return []


def build_story_link(meta: dict) -> list:
    """Build a StoryLink sticker if link is set."""
    url = meta.get("link")
    if not url:
        return []
    return [StoryLink(webUri=url)]


def build_music_extra_data(cl, meta: dict) -> dict:
    """
    Build extra_data dict for music sticker on stories.
    Two sources supported:
      1. music_track_id — a known canonical Instagram music ID
      2. music_from_reel — shortcode of a reel to borrow music from

    Returns {} if no music config found or track can't be resolved.
    """
    track_id  = meta.get("music_track_id")
    from_reel = meta.get("music_from_reel")

    # Source 1: explicit track ID
    if track_id:
        try:
            track = cl.track_info_by_canonical_id(str(track_id))
            return {
                "music_canonical_id":      str(track_id),
                "ig_music_sticker_asset_id": str(track_id),
                "music_asset_info": {
                    "id":              str(track_id),
                    "title":           track.title           if hasattr(track, "title")           else "",
                    "display_artist":  track.display_artist  if hasattr(track, "display_artist")  else "",
                    "audio_asset_uri": track.uri             if hasattr(track, "uri")             else "",
                },
                "music_start_time_ms": str(meta.get("music_start_ms", 0)),
            }
        except Exception as e:
            logging.warning(f"Could not resolve track_id {track_id}: {e}")
            return {}

    # Source 2: borrow music from an existing reel
    if from_reel:
        try:
            media    = cl.media_info_by_shortcode(from_reel)
            meta_raw = getattr(media, "clips_metadata", {}) or {}
            cid      = (
                meta_raw.get("music_canonical_id") or
                meta_raw.get("audio_canonical_id")
            )
            if cid:
                return {
                    "music_canonical_id":        str(cid),
                    "ig_music_sticker_asset_id": str(cid),
                    "music_start_time_ms":       str(meta.get("music_start_ms", 0)),
                }
        except Exception as e:
            logging.warning(f"Could not borrow music from reel {from_reel}: {e}")
            return {}

    return {}


# ─────────────────────────────────────────────────────────────────────────────
# QUEUE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def list_queue() -> list:
    """
    Return a list of pending post dicts from posts/queue/.
    Each dict: {name, path, meta, type, files, scheduled_time, ready}
    """
    posts = []
    for entry in sorted(QUEUE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        meta = load_meta(entry)
        post_type = meta.get("type", "photo")
        images    = collect_images(entry)
        video     = collect_video(entry)

        # Determine if post is ready to fire
        sched = meta.get("scheduled_time", "now")
        if sched == "now":
            ready = True
        else:
            try:
                sched_dt = datetime.strptime(sched, "%Y-%m-%d %H:%M")
                ready    = datetime.now() >= sched_dt
            except ValueError:
                ready = True

        posts.append({
            "name":           entry.name,
            "path":           entry,
            "meta":           meta,
            "type":           post_type,
            "images":         images,
            "video":          video,
            "scheduled_time": sched,
            "ready":          ready,
        })
    return posts


def mark_done(post_dir: Path):
    """Move a completed post folder to posts/done/."""
    dest = DONE_DIR / f"{post_dir.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.move(str(post_dir), str(dest))


def mark_failed(post_dir: Path, reason: str):
    """Move a failed post folder to posts/failed/ and write error.txt."""
    dest = FAILED_DIR / f"{post_dir.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.move(str(post_dir), str(dest))
    (dest / "error.txt").write_text(reason, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# CORE PUBLISHER
# ─────────────────────────────────────────────────────────────────────────────

class Publisher:
    """
    Wraps all post/story upload methods.
    One Publisher instance is created per InstagramBot (owns the cl client).
    """

    def __init__(self, bot):
        self.bot  = bot
        self.cl   = bot.cl
        self.log  = bot.log
        self.user = bot.username

    def _lp(self, msg: str, level: str = "info"):
        from human_behaviour import lp
        lp(self.user, msg, level)

    def _record_post(self, post_type: str, meta: dict, media_pk: str = None):
        """Save publish event to stats_store."""
        stats_store.record_post(
            username   = self.user,
            post_type  = post_type,
            caption    = meta.get("caption", "")[:200],
            location   = meta.get("location", ""),
            media_pk   = str(media_pk) if media_pk else "",
            has_music  = bool(meta.get("music_track_id") or meta.get("music_from_reel")),
        )

    # ── SINGLE PHOTO POST ─────────────────────────────────────────────────────

    def post_photo(self, image_path: str | Path, meta: dict) -> dict:
        """
        Upload a single photo post.
        Supports: caption, hashtags, location, usertags.
        """
        image_path = Path(image_path)
        image_path = self.preprocess(image_path, meta)
        self._lp(f"─── POST PHOTO  {image_path.name}", "header")

        caption  = build_caption(meta)
        location = resolve_location(self.cl, meta)
        usertags = resolve_usertags(self.cl, meta)

        self._lp(f"  Caption  {caption[:60]}...", "info")
        if location: self._lp(f"  Location  {location.name}", "info")
        if usertags: self._lp(f"  Tagging  {len(usertags)} user(s)", "info")

        try:
            self._lp("Uploading photo via API", "api")
            kwargs = {
                "path":    str(image_path),
                "caption": caption,
            }
            if location:            kwargs["location"] = location
            if usertags:            kwargs["usertags"] = usertags
            media = self.cl.photo_upload(**kwargs)
            self._lp(f"Photo posted  pk={media.pk}  @{self.user}", "success")
            self._record_post("photo", meta, media.pk)
            return {"ok": True, "pk": str(media.pk), "type": "photo"}

        except Exception as e:
            self._lp(f"Photo upload failed: {e}", "warn")
            return {"ok": False, "error": str(e), "type": "photo"}

    # ── CAROUSEL POST ─────────────────────────────────────────────────────────

    def post_carousel(self, image_paths: list, meta: dict) -> dict:
        """
        Upload a carousel (album) post with 2–10 images.
        Supports: caption, hashtags, location, usertags (applied to first image).
        """
        self._lp(f"─── POST CAROUSEL  {len(image_paths)} images", "header")

        # Pre-process all images with identical settings so carousel is uniform
        processed = []
        for img in image_paths:
            processed.append(self.preprocess(img, meta))
        image_paths = processed

        if len(image_paths) < 2:
            return {"ok": False, "error": "Carousel needs at least 2 images", "type": "carousel"}
        if len(image_paths) > 10:
            self._lp("Truncating to 10 images (Instagram limit)", "warn")
            image_paths = image_paths[:10]

        caption  = build_caption(meta)
        location = resolve_location(self.cl, meta)
        usertags = resolve_usertags(self.cl, meta)

        self._lp(f"  Images   {[p.name for p in image_paths]}", "info")
        self._lp(f"  Caption  {caption[:60]}...", "info")
        if location: self._lp(f"  Location  {location.name}", "info")

        try:
            self._lp("Uploading carousel via API", "api")
            kwargs = {
                "paths":   [str(p) for p in image_paths],
                "caption": caption,
            }
            if location:  kwargs["location"] = location
            if usertags:  kwargs["usertags"] = usertags
            media = self.cl.album_upload(**kwargs)
            self._lp(f"Carousel posted  pk={media.pk}  @{self.user}", "success")
            self._record_post("carousel", meta, media.pk)
            return {"ok": True, "pk": str(media.pk), "type": "carousel"}

        except Exception as e:
            self._lp(f"Carousel upload failed: {e}", "warn")
            return {"ok": False, "error": str(e), "type": "carousel"}

    # ── PHOTO STORY ───────────────────────────────────────────────────────────

    def post_story_photo(self, image_path: str | Path, meta: dict) -> dict:
        """
        Upload a photo story.
        Supports: location sticker, mention stickers, hashtag sticker,
                  link sticker, music (best-effort via extra_data).
        """
        image_path = Path(image_path)
        image_path = self.preprocess(image_path, meta)
        self._lp(f"─── POST STORY PHOTO  {image_path.name}", "header")

        mentions  = build_story_mentions(self.cl, meta)
        hashtags  = build_story_hashtag(self.cl, meta)
        locations = build_story_location(self.cl, meta)
        links     = build_story_link(meta)
        music_ed  = build_music_extra_data(self.cl, meta)

        if mentions:  self._lp(f"  Mentions    {[m.user.username for m in mentions]}", "info")
        if hashtags:  self._lp(f"  Hashtag sticker  #{hashtags[0].hashtag.name}", "info")
        if locations: self._lp(f"  Location sticker  {locations[0].location.name}", "info")
        if links:     self._lp(f"  Link sticker  {links[0].webUri}", "info")
        if music_ed:  self._lp(f"  Music  id={music_ed.get('music_canonical_id','?')}", "info")

        try:
            self._lp("Uploading story photo via API", "api")
            kwargs = {"path": str(image_path)}
            if mentions:  kwargs["mentions"]  = mentions
            if hashtags:  kwargs["hashtags"]  = hashtags
            if locations: kwargs["locations"] = locations
            if links:     kwargs["links"]     = links
            if music_ed:  kwargs["extra_data"] = music_ed
            media = self.cl.photo_upload_to_story(**kwargs)
            self._lp(f"Story photo posted  pk={media.pk}  @{self.user}", "success")
            self._record_post("story_photo", meta, media.pk)
            return {"ok": True, "pk": str(media.pk), "type": "story_photo"}

        except Exception as e:
            self._lp(f"Story photo upload failed: {e}", "warn")
            return {"ok": False, "error": str(e), "type": "story_photo"}

    # ── VIDEO STORY ───────────────────────────────────────────────────────────

    def post_story_video(self, video_path: str | Path, meta: dict) -> dict:
        """
        Upload a video story.
        Supports: same stickers as photo story + music.
        Requires ffmpeg installed for video processing.
        """
        video_path = Path(video_path)
        self._lp(f"─── POST STORY VIDEO  {video_path.name}", "header")

        mentions  = build_story_mentions(self.cl, meta)
        hashtags  = build_story_hashtag(self.cl, meta)
        locations = build_story_location(self.cl, meta)
        links     = build_story_link(meta)
        music_ed  = build_music_extra_data(self.cl, meta)

        if music_ed: self._lp(f"  Music  id={music_ed.get('music_canonical_id','?')}", "info")

        try:
            self._lp("Uploading story video via API", "api")
            kwargs = {"path": str(video_path)}
            if mentions:  kwargs["mentions"]  = mentions
            if hashtags:  kwargs["hashtags"]  = hashtags
            if locations: kwargs["locations"] = locations
            if links:     kwargs["links"]     = links
            if music_ed:  kwargs["extra_data"] = music_ed
            media = self.cl.video_upload_to_story(**kwargs)
            self._lp(f"Story video posted  pk={media.pk}  @{self.user}", "success")
            self._record_post("story_video", meta, media.pk)
            return {"ok": True, "pk": str(media.pk), "type": "story_video"}

        except Exception as e:
            self._lp(f"Story video upload failed: {e}", "warn")
            return {"ok": False, "error": str(e), "type": "story_video"}

    # ── OPTIONAL PRE-PROCESS: resize + filter before uploading ──────────────

    def preprocess(
        self,
        image_path: "str | Path",
        meta: dict,
    ) -> "Path":
        """
        If meta.yaml contains image_preset or image_filter keys,
        run the image through ImageEditor before uploading.
        Returns the (possibly new) path to pass to the upload method.

        meta keys recognised:
            image_preset:    square | portrait | landscape | story | carousel
            image_filter:    warm | cool | faded | vivid | matte | bw | dramatic | soft | vintage
            image_brightness: 1.0
            image_contrast:   1.0
            image_saturation: 1.0
            image_sharpness:  1.0
            image_auto_enhance: false
            image_mode:      crop | pad   (how to handle aspect mismatch)
        """
        from pathlib import Path as _Path
        image_path = _Path(image_path)

        preset      = meta.get("image_preset")
        filter_name = meta.get("image_filter")
        brightness  = float(meta.get("image_brightness",  1.0))
        contrast    = float(meta.get("image_contrast",    1.0))
        saturation  = float(meta.get("image_saturation",  1.0))
        sharpness   = float(meta.get("image_sharpness",   1.0))
        auto_enh    = bool(meta.get("image_auto_enhance", False))
        mode        = meta.get("image_mode", "crop")

        # Nothing to do — return original path unchanged
        needs_edit = any([
            preset, filter_name, auto_enh,
            brightness != 1.0, contrast != 1.0,
            saturation != 1.0, sharpness != 1.0,
        ])
        if not needs_edit:
            return image_path

        self._lp(f"Pre-processing  {image_path.name}  preset={preset}  filter={filter_name}", "info")

        editor = ImageEditor(image_path)

        if preset:
            editor.resize(preset, mode=mode)
        if auto_enh:
            editor.auto_enhance()
        if filter_name and filter_name != "none":
            editor.apply_filter(filter_name)
        editor.adjust(brightness, contrast, saturation, sharpness)

        out = editor.save()
        self._lp(f"Saved processed image  {out.name}  {editor.size[0]}x{editor.size[1]}", "success")
        return out

    # ── DISPATCH: pick the right method from meta.yaml type ──────────────────

    def publish_from_folder(self, post_dir: Path) -> dict:
        """
        Read a post folder, pick the right upload method, execute it.
        Returns {ok, pk, type, error?}
        """
        meta      = load_meta(post_dir)
        post_type = meta.get("type", "photo")
        self._lp(f"Publishing  {post_dir.name}  type={post_type}", "info")

        if post_type == "photo":
            images = collect_images(post_dir)
            if not images:
                return {"ok": False, "error": "No image files found", "type": post_type}
            return self.post_photo(images[0], meta)

        elif post_type == "carousel":
            images = collect_images(post_dir)
            if len(images) < 2:
                return {"ok": False, "error": "Carousel needs at least 2 images", "type": post_type}
            return self.post_carousel(images, meta)

        elif post_type == "story_photo":
            images = collect_images(post_dir)
            if not images:
                return {"ok": False, "error": "No image files found", "type": post_type}
            return self.post_story_photo(images[0], meta)

        elif post_type == "story_video":
            video = collect_video(post_dir)
            if not video:
                return {"ok": False, "error": "No video file found", "type": post_type}
            return self.post_story_video(video, meta)

        else:
            return {"ok": False, "error": f"Unknown post type: {post_type}", "type": post_type}


# ─────────────────────────────────────────────────────────────────────────────
# MUSIC SEARCH HELPER  (standalone — not tied to a bot instance)
# ─────────────────────────────────────────────────────────────────────────────

def find_track_id_from_reels(cl, keyword: str, sample: int = 50) -> list:
    """
    Search recent reels mentioning a keyword and collect unique track IDs.
    Since instagrapi has no music search endpoint, this is the best available
    method for discovering a song's canonical ID.

    Returns list of {track_id, title, artist} dicts.
    """
    results  = []
    seen_ids = set()
    try:
        medias = cl.hashtag_medias_recent(keyword.replace(" ", ""), sample)
        for media in medias:
            cm = getattr(media, "clips_metadata", {}) or {}
            cid = cm.get("music_canonical_id") or cm.get("audio_canonical_id")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                try:
                    track = cl.track_info_by_canonical_id(str(cid))
                    results.append({
                        "track_id": str(cid),
                        "title":    getattr(track, "title", "?"),
                        "artist":   getattr(track, "display_artist", "?"),
                    })
                except Exception:
                    results.append({"track_id": str(cid), "title": "?", "artist": "?"})
    except Exception as e:
        logging.warning(f"Music search failed: {e}")
    return results


def get_track_info(cl, track_id: str) -> dict:
    """Look up title and artist for a known canonical track ID."""
    try:
        track = cl.track_info_by_canonical_id(str(track_id))
        return {
            "track_id": str(track_id),
            "title":    getattr(track, "title", "?"),
            "artist":   getattr(track, "display_artist", "?"),
            "uri":      getattr(track, "uri", ""),
        }
    except Exception as e:
        return {"track_id": str(track_id), "error": str(e)}