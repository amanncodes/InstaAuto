"""
cli/menu_publish.py  —  Publish Content menu.

Handles: single photo, carousel, photo story, video story,
         post queue, queue viewer, post history, music track finder.
"""

import os
from pathlib import Path

from rich.prompt import Prompt, Confirm
from rich.table  import Table
from rich.panel  import Panel
from rich        import box

import poster as _poster
import stats_store
from cli.shared import (
    console, hdr, rule, ok, info, warn, done,
    pick_accounts, run_on_bots, ask_concurrent,
)


def menu_publish(manager, cfg):
    hdr("PUBLISH CONTENT")
    console.print("[dim]  Post photos, carousels, and stories with location, mentions, and music.[/dim]\n")
    opts = [
        ("1", "Post single photo          caption  location  usertags"),
        ("2", "Post carousel              2-10 images  caption  location"),
        ("3", "Post photo story           location  mentions  hashtag  link  music"),
        ("4", "Post video story           location  mentions  hashtag  link  music"),
        ("5", "Run post queue             publish ready posts from posts/queue/"),
        ("6", "View queue                 see pending scheduled posts"),
        ("7", "Post history               published posts per account"),
        ("8", "Find music track ID        search reels by hashtag to discover track IDs"),
        ("0", "Back"),
    ]
    for k, v in opts:
        console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0":
        return

    # ── 1. Single photo ──────────────────────────────────────────────────────
    if choice == "1":
        image_path = Prompt.ask("  Full path to image file")
        if not os.path.exists(image_path):
            warn(f"File not found: {image_path}"); return
        caption  = Prompt.ask("  Caption")
        raw_tags = Prompt.ask("  Hashtags  [space-separated, no #, leave blank to skip]", default="")
        location = Prompt.ask("  Location name  [leave blank to skip]", default="")
        meta = {
            "caption":  caption,
            "hashtags": [t.strip() for t in raw_tags.split() if t.strip()],
        }
        if location: meta["location"] = location
        bots = pick_accounts(manager)
        if not bots: return
        for bot in bots:
            result = bot.post_photo(image_path, meta)
            if result["ok"]:
                ok(f"Posted  @{bot.username}  pk={result['pk']}")
            else:
                warn(f"Failed  @{bot.username}  {result.get('error')}")

    # ── 2. Carousel ──────────────────────────────────────────────────────────
    elif choice == "2":
        raw    = Prompt.ask("  Image paths  [comma-separated, in order]")
        paths  = [p.strip() for p in raw.split(",") if p.strip()]
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            warn(f"Files not found: {missing}"); return
        if len(paths) < 2:
            warn("Need at least 2 images for a carousel"); return
        caption  = Prompt.ask("  Caption")
        raw_tags = Prompt.ask("  Hashtags  [space-separated, no #]", default="")
        location = Prompt.ask("  Location name  [leave blank to skip]", default="")
        meta = {
            "caption":  caption,
            "hashtags": [t.strip() for t in raw_tags.split() if t.strip()],
        }
        if location: meta["location"] = location
        bots = pick_accounts(manager)
        if not bots: return
        for bot in bots:
            result = bot.post_carousel([Path(p) for p in paths], meta)
            if result["ok"]:
                ok(f"Carousel posted  @{bot.username}  pk={result['pk']}")
            else:
                warn(f"Failed  @{bot.username}  {result.get('error')}")

    # ── 3. Photo story ───────────────────────────────────────────────────────
    elif choice == "3":
        image_path = Prompt.ask("  Full path to image file")
        if not os.path.exists(image_path):
            warn(f"File not found: {image_path}"); return
        meta = {}
        location = Prompt.ask("  Location name  [blank to skip]", default="")
        if location: meta["location"] = location
        raw_mentions = Prompt.ask("  Mention usernames  [comma-separated, blank to skip]", default="")
        if raw_mentions.strip():
            meta["mentions"] = [u.strip().lstrip("@") for u in raw_mentions.split(",") if u.strip()]
        hashtag_s = Prompt.ask("  Hashtag sticker  [single tag, blank to skip]", default="")
        if hashtag_s.strip(): meta["hashtag_sticker"] = hashtag_s.strip().lstrip("#")
        link = Prompt.ask("  Link sticker URL  [blank to skip]", default="")
        if link.strip(): meta["link"] = link.strip()
        track_id = Prompt.ask("  Music track ID  [blank to skip — use option 8 to find IDs]", default="")
        if track_id.strip():
            meta["music_track_id"] = track_id.strip()
            meta["music_start_ms"] = int(Prompt.ask("  Music start position  [milliseconds]", default="0"))
        bots = pick_accounts(manager)
        if not bots: return
        for bot in bots:
            result = bot.post_story_photo(image_path, meta)
            if result["ok"]:
                ok(f"Story posted  @{bot.username}  pk={result['pk']}")
            else:
                warn(f"Failed  @{bot.username}  {result.get('error')}")

    # ── 4. Video story ───────────────────────────────────────────────────────
    elif choice == "4":
        video_path = Prompt.ask("  Full path to video file  [mp4]")
        if not os.path.exists(video_path):
            warn(f"File not found: {video_path}"); return
        meta = {}
        location = Prompt.ask("  Location name  [blank to skip]", default="")
        if location: meta["location"] = location
        raw_mentions = Prompt.ask("  Mention usernames  [comma-separated, blank to skip]", default="")
        if raw_mentions.strip():
            meta["mentions"] = [u.strip().lstrip("@") for u in raw_mentions.split(",") if u.strip()]
        hashtag_s = Prompt.ask("  Hashtag sticker  [blank to skip]", default="")
        if hashtag_s.strip(): meta["hashtag_sticker"] = hashtag_s.strip().lstrip("#")
        link = Prompt.ask("  Link sticker URL  [blank to skip]", default="")
        if link.strip(): meta["link"] = link.strip()
        track_id = Prompt.ask("  Music track ID  [blank to skip]", default="")
        if track_id.strip():
            meta["music_track_id"] = track_id.strip()
            meta["music_start_ms"] = int(Prompt.ask("  Music start position  [milliseconds]", default="0"))
        bots = pick_accounts(manager)
        if not bots: return
        for bot in bots:
            result = bot.post_story_video(video_path, meta)
            if result["ok"]:
                ok(f"Story video posted  @{bot.username}  pk={result['pk']}")
            else:
                warn(f"Failed  @{bot.username}  {result.get('error')}")

    # ── 5. Run queue ─────────────────────────────────────────────────────────
    elif choice == "5":
        pending = _poster.list_queue()
        ready   = [p for p in pending if p["ready"]]
        if not ready:
            warn("No ready posts in queue  —  add folders to posts/queue/"); return
        info(f"Ready to publish:  {len(ready)} post(s)")
        for p in ready:
            console.print(f"  [dim]{p['name']}[/dim]  type={p['type']}  scheduled={p['scheduled_time']}")
        rule()
        if not Confirm.ask("  Publish all ready posts now?", default=True): return
        bots = pick_accounts(manager)
        if not bots: return
        run_on_bots(bots, lambda b: b.publish_from_queue(), ask_concurrent())
        done()

    # ── 6. View queue ─────────────────────────────────────────────────────────
    elif choice == "6":
        posts = _poster.list_queue()
        if not posts:
            info("Queue is empty  —  add folders to posts/queue/"); return
        t = Table(title="  POST QUEUE", show_header=True,
                  header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("Folder",    style="bold white", min_width=20)
        t.add_column("Type",      min_width=12)
        t.add_column("Files",     justify="right")
        t.add_column("Scheduled", min_width=16)
        t.add_column("Accounts",  style="dim")
        t.add_column("Ready",     justify="center")
        for p in posts:
            file_count = len(p["images"]) + (1 if p["video"] else 0)
            accounts   = ", ".join(p["meta"].get("accounts", [])) or "all"
            ready_str  = "[bright_green]YES[/bright_green]" if p["ready"] else "[dim]waiting[/dim]"
            t.add_row(p["name"], p["type"], str(file_count),
                      str(p["scheduled_time"]), accounts, ready_str)
        console.print(t)
        info("Queue folder:  posts/queue/  |  Done: posts/done/  |  Failed: posts/failed/")

    # ── 7. Post history ───────────────────────────────────────────────────────
    elif choice == "7":
        usernames = stats_store.get_all_usernames()
        if not usernames:
            warn("No accounts found in database"); return
        username = usernames[0] if len(usernames) == 1 else Prompt.ask(
            "  Account",
            choices=usernames,
        )
        history = stats_store.get_post_history(username, limit=30)
        summary = stats_store.get_post_summary(username)
        console.print(Panel(
            f"  Total: [bold]{summary['total']}[/bold]   "
            f"Photos: [white]{summary['photo']}[/white]   "
            f"Carousels: [white]{summary['carousel']}[/white]   "
            f"Stories: [white]{summary['story_photo'] + summary['story_video']}[/white]   "
            f"Last 7 days: [bright_cyan]{summary['last_7_days']}[/bright_cyan]",
            title=f"  PUBLISH SUMMARY  @{username}",
            border_style="cyan", title_align="left",
        ))
        if not history:
            info("No posts recorded yet"); return
        t = Table(title=f"  LAST 30 POSTS  @{username}", show_header=True,
                  header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("Time",     style="dim",  min_width=16)
        t.add_column("Type",     min_width=12)
        t.add_column("Caption",  min_width=30)
        t.add_column("Location", style="dim")
        t.add_column("Music",    justify="center")
        t.add_column("Media PK", style="dim")
        for row in history:
            caption = (row["caption"] or "")[:40] + ("..." if len(row.get("caption","")) > 40 else "")
            music   = "[bright_cyan]YES[/bright_cyan]" if row["has_music"] else "—"
            ts      = (row["ts"] or "")[:16].replace("T", " ")
            t.add_row(ts, row.get("type", row.get("post_type","?")),
                      caption, row.get("location","") or "—", music,
                      str(row.get("media_pk",""))[:12])
        console.print(t)

    # ── 8. Find music track ID ────────────────────────────────────────────────
    elif choice == "8":
        console.print("  [dim]Searches recent reels using a hashtag to find track IDs.[/dim]")
        console.print("  [dim]Copy the track_id into your meta.yaml music_track_id field.[/dim]\n")
        bots = [b for b in manager.bots if b.logged_in]
        if not bots:
            warn("Need at least one logged-in account to search"); return
        keyword = Prompt.ask("  Search hashtag  [e.g. bollywood  hiphop  lofi]")
        sample  = int(Prompt.ask("  Reels to sample", default="30"))
        with console.status("[bold cyan]  Searching reels for music...[/bold cyan]"):
            tracks = _poster.find_track_id_from_reels(bots[0].cl, keyword, sample)
        if not tracks:
            warn("No tracks found — try a different hashtag or larger sample size"); return
        t = Table(title=f"  MUSIC TRACKS FOUND  #{keyword}",
                  show_header=True, header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("Track ID", style="bold white", min_width=22)
        t.add_column("Title",    min_width=28)
        t.add_column("Artist",   min_width=20)
        for tr in tracks:
            t.add_row(tr["track_id"], tr.get("title","?"), tr.get("artist","?"))
        console.print(t)
        info("Copy a Track ID and use it as  music_track_id  in your meta.yaml")