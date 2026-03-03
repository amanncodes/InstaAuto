"""
cli/menu_images.py  —  Image Editor menu.
Resize, filter, adjust, batch-process, and analyse images.
"""

import os

from rich.prompt import Prompt, Confirm
from rich.table  import Table
from rich.panel  import Panel
from rich        import box

import image_editor as _editor
from cli.shared import console, hdr, rule, ok, info, warn, done


def menu_edit_images(manager, cfg):
    hdr("IMAGE EDITOR")
    console.print("[dim]  Resize, filter, and adjust photos to Instagram specs before posting.[/dim]\n")

    preset_table = Table(title="  SIZE PRESETS", box=box.SIMPLE_HEAD,
                         header_style="bold cyan", show_header=True)
    preset_table.add_column("Name",       style="bold white")
    preset_table.add_column("Dimensions", style="cyan")
    preset_table.add_column("Ratio")
    preset_table.add_column("Best for")
    for row in [
        ("portrait",  "1080 x 1350", "4:5",   "Feed posts — best reach in 2025"),
        ("square",    "1080 x 1080", "1:1",    "Feed posts — classic versatile"),
        ("landscape", "1080 x 566",  "1.91:1", "Wide scenic shots"),
        ("story",     "1080 x 1920", "9:16",   "Stories and Reels"),
        ("carousel",  "1080 x 1350", "4:5",    "All slides in a carousel"),
    ]:
        preset_table.add_row(*row)
    console.print(preset_table)

    filter_table = Table(title="  FILTERS", box=box.SIMPLE_HEAD,
                         header_style="bold cyan", show_header=True)
    filter_table.add_column("Name",        style="bold white", min_width=10)
    filter_table.add_column("Description")
    for name, desc in _editor.FILTER_DESCRIPTIONS.items():
        filter_table.add_row(name, desc)
    console.print(filter_table)

    opts = [
        ("1", "Edit single image     resize  filter  adjust"),
        ("2", "Edit batch / carousel resize all with same settings"),
        ("3", "Analyse image         check dimensions and get preset suggestion"),
        ("0", "Back"),
    ]
    for k, v in opts:
        console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0":
        return

    # ── 1. Single image ──────────────────────────────────────────────────────
    if choice == "1":
        path = Prompt.ask("  Image path")
        if not os.path.exists(path):
            warn(f"File not found: {path}"); return

        info_data = _editor.analyse_image(path)
        console.print(Panel(
            f"  Size:  [bold]{info_data['dimensions']}[/bold]   "
            f"({info_data['size_kb']} KB)   "
            f"Ratio: [cyan]{info_data['aspect_ratio']}[/cyan]\n"
            f"  Suggested preset: [bright_cyan]{info_data['suggested_preset']}[/bright_cyan]   "
            f"{info_data['note']}"
            + (f"\n  [yellow]Warning: {info_data['quality_warning']}[/yellow]"
               if info_data["quality_warning"] else ""),
            title="  IMAGE INFO", border_style="dim", title_align="left",
        ))

        preset = Prompt.ask(
            "  Size preset",
            choices=list(_editor.PRESETS.keys()) + ["none"],
            default=info_data["suggested_preset"],
        )
        crop_mode = "crop"
        if preset != "none":
            crop_mode = Prompt.ask(
                "  Fit mode  [crop = fill frame / pad = letterbox with white bars]",
                choices=["crop", "pad"], default="crop",
            )

        filter_name = Prompt.ask(
            "  Filter", choices=list(_editor.FILTERS.keys()), default="none",
        )

        brightness = contrast = saturation = sharpness = 1.0
        if Confirm.ask("  Fine-tune brightness / contrast / saturation / sharpness?", default=False):
            brightness = float(Prompt.ask("  Brightness  [0.5 dark → 2.0 bright, 1.0 = no change]", default="1.0"))
            contrast   = float(Prompt.ask("  Contrast    [0.5 flat → 2.0 punchy]",                  default="1.0"))
            saturation = float(Prompt.ask("  Saturation  [0.0 B&W  → 3.0 vivid]",                   default="1.0"))
            sharpness  = float(Prompt.ask("  Sharpness   [0.0 blur → 3.0 sharp]",                   default="1.0"))

        do_auto = Confirm.ask("  Apply auto-enhance (auto levels + light sharpen)?", default=False)
        do_vign = Confirm.ask("  Add vignette?",                                     default=False)
        out_path = Prompt.ask("  Output path  [leave blank for auto]", default="")

        with console.status("[bold cyan]  Processing image...[/bold cyan]"):
            try:
                editor = _editor.ImageEditor(path)
                if preset != "none":
                    editor.resize(preset, mode=crop_mode)
                if do_auto:
                    editor.auto_enhance()
                if filter_name != "none":
                    editor.apply_filter(filter_name)
                editor.adjust(brightness, contrast, saturation, sharpness)
                if do_vign:
                    strength = float(Prompt.ask("  Vignette strength [0.1–0.8]", default="0.35"))
                    editor.vignette(strength)
                saved = editor.save(out_path if out_path else None)
                ok(f"Saved  {saved}")
                info(f"Final size: {editor.size[0]}x{editor.size[1]}  |  Ops: {', '.join(editor.ops_log)}")
            except Exception as e:
                warn(f"Processing failed: {e}")

    # ── 2. Batch / carousel ──────────────────────────────────────────────────
    elif choice == "2":
        console.print("  [dim]Enter image paths one per line. Empty line to finish.[/dim]")
        paths = []
        while True:
            p = Prompt.ask(f"  Image {len(paths)+1}  [blank to finish]", default="")
            if not p: break
            if not os.path.exists(p):
                warn(f"  File not found: {p}"); continue
            paths.append(p)
        if not paths:
            warn("No images entered"); return

        preset = Prompt.ask(
            "  Size preset  [all images will use same preset]",
            choices=list(_editor.PRESETS.keys()) + ["none"],
            default="portrait",
        )
        filter_name = Prompt.ask(
            "  Filter", choices=list(_editor.FILTERS.keys()), default="none",
        )
        do_auto    = Confirm.ask("  Auto-enhance all?", default=False)
        brightness = float(Prompt.ask("  Brightness", default="1.0"))
        contrast   = float(Prompt.ask("  Contrast",   default="1.0"))
        saturation = float(Prompt.ask("  Saturation", default="1.0"))
        out_dir    = Prompt.ask("  Output directory  [blank for auto]", default="")

        with console.status(f"[bold cyan]  Processing {len(paths)} images...[/bold cyan]"):
            results = _editor.process_batch(
                paths,
                preset       = preset if preset != "none" else None,
                filter_name  = filter_name,
                brightness   = brightness,
                contrast     = contrast,
                saturation   = saturation,
                auto_enhance = do_auto,
                output_dir   = out_dir if out_dir else None,
            )

        t = Table(title="  BATCH RESULTS", show_header=True,
                  header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("Source", style="dim")
        t.add_column("Output", style="bold white")
        t.add_column("Status", justify="center")
        for src, out in zip(paths, results):
            status = "[bright_green]OK[/bright_green]" if out else "[red]FAILED[/red]"
            t.add_row(os.path.basename(src), os.path.basename(str(out)) if out else "—", status)
        console.print(t)
        ok(f"Done  {sum(1 for r in results if r)} / {len(results)} processed")

    # ── 3. Analyse ───────────────────────────────────────────────────────────
    elif choice == "3":
        console.print("  [dim]Enter image paths one per line. Empty line to finish.[/dim]")
        paths = []
        while True:
            p = Prompt.ask(f"  Image {len(paths)+1}  [blank to finish]", default="")
            if not p: break
            if not os.path.exists(p):
                warn(f"  File not found: {p}"); continue
            paths.append(p)
        if not paths: return

        t = Table(title="  IMAGE ANALYSIS", show_header=True,
                  header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("File",      style="dim",        min_width=24)
        t.add_column("Size",      min_width=10)
        t.add_column("KB",        justify="right")
        t.add_column("Ratio",     justify="right")
        t.add_column("Suggested", style="bright_cyan")
        t.add_column("Notes",     style="dim",        min_width=30)
        for p in paths:
            try:
                data = _editor.analyse_image(p)
                note = data["note"]
                if data["quality_warning"]:
                    note = f"[yellow]{data['quality_warning']}[/yellow]"
                t.add_row(os.path.basename(p), data["dimensions"], str(data["size_kb"]),
                          data["aspect_ratio"], data["suggested_preset"], note)
            except Exception as e:
                t.add_row(os.path.basename(p), "—", "—", "—", "—", f"[red]{e}[/red]")
        console.print(t)

    done()