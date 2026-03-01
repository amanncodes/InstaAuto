"""
InstaBot CLI  v2.1
Clean board-style interface. No emojis. Concurrent threading.
Persistent stats — all-time and 14-day history across sessions.
"""

import sys
import time
import os
import logging
import threading
from datetime import datetime

from rich.console import Console
from rich.table   import Table
from rich.prompt  import Prompt, Confirm
from rich.panel   import Panel
from rich.live    import Live
from rich.text    import Text
from rich         import box

from config_loader   import load_config
from account_manager import AccountManager
from scheduler       import build_scheduler_from_config
from task_runner     import menu_manual_trigger
import stats_store
import poster as _poster
import image_editor as _editor

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# THEME
# ─────────────────────────────────────────────────────────────────────────────

SEP  = "─" * 62
SEP2 = "═" * 62

BANNER = """\
[bold white]
  ██╗███╗   ██╗███████╗████████╗ █████╗ ██████╗  ██████╗ ████████╗
  ██║████╗  ██║██╔════╝╚══██╔══╝██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝
  ██║██╔██╗ ██║███████╗   ██║   ███████║██████╔╝██║   ██║   ██║
  ██║██║╚██╗██║╚════██║   ██║   ██╔══██║██╔══██╗██║   ██║   ██║
  ██║██║ ╚████║███████║   ██║   ██║  ██║██████╔╝╚██████╔╝   ██║
  ╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═════╝  ╚═════╝    ╚═╝
[/bold white][dim]  Multi-Account Instagram Automation  ·  v2.1[/dim]
"""

def hdr(title: str):
    console.print(f"\n[bold cyan]{SEP2}[/bold cyan]")
    console.print(f"[bold cyan]  {title}[/bold cyan]")
    console.print(f"[bold cyan]{SEP2}[/bold cyan]")

def rule(label: str = ""):
    if label:
        console.print(f"[dim]{SEP}  {label}[/dim]")
    else:
        console.print(f"[dim]{SEP}[/dim]")

def ok(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    console.print(f"[dim]{ts}[/dim]  [bright_green] OK   {msg}[/bright_green]")

def info(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    console.print(f"[dim]{ts}[/dim]  [white]  ·   {msg}[/white]")

def warn(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    console.print(f"[dim]{ts}[/dim]  [bright_red]  !   {msg}[/bright_red]")


# ─────────────────────────────────────────────────────────────────────────────
# LIVE DASHBOARD  (current session only — fast, no disk read)
# ─────────────────────────────────────────────────────────────────────────────

def build_dashboard(manager) -> Table:
    t = Table(
        title=f"  DASHBOARD   {datetime.now().strftime('%H:%M:%S')}",
        show_header=True, header_style="bold cyan",
        box=box.SIMPLE_HEAD, expand=True,
    )
    t.add_column("Account",   style="bold white",   min_width=18)
    t.add_column("Status",    min_width=10)
    t.add_column("Device",    style="dim",          min_width=16)
    t.add_column("Likes",     justify="right")
    t.add_column("Comments",  justify="right")
    t.add_column("Follows",   justify="right")
    t.add_column("Unfollow",  justify="right")
    t.add_column("DMs",       justify="right")
    t.add_column("Stories",   justify="right")
    t.add_column("Fatigue",   justify="center")

    for bot in manager.bots:
        s      = bot.session
        status = "[bright_green]ACTIVE[/bright_green]" if bot.logged_in else "[bright_red]OFFLINE[/bright_red]"
        device = f"{bot._device['manufacturer']} {bot._device['model']}" if hasattr(bot,"_device") else "—"
        f      = s.fatigue_level
        fatigue = (
            f"[bright_green]{f:.0%}[/bright_green]"  if f < 0.3 else
            f"[yellow]{f:.0%}[/yellow]"              if f < 0.7 else
            f"[bright_red]{f:.0%}[/bright_red]"
        )
        a, lim = s.actions_today, s.daily_limits
        t.add_row(
            bot.username, status, device,
            f"{a['likes']}/{lim['likes']}",
            f"{a['comments']}/{lim['comments']}",
            f"{a['follows']}/{lim['follows']}",
            f"{a['unfollows']}/{lim['unfollows']}",
            f"{a['dms']}/{lim['dms']}",
            f"{a['story_views']}/{lim['story_views']}",
            fatigue,
        )
    return t

def show_live_dashboard(manager, seconds=30):
    with Live(console=console, refresh_per_second=1) as live:
        for _ in range(seconds):
            live.update(build_dashboard(manager))
            time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def print_accounts_table(manager):
    t = Table(show_header=True, header_style="bold cyan",
              box=box.SIMPLE_HEAD, title="  ACCOUNTS")
    t.add_column("#",        style="dim", width=4)
    t.add_column("Username", style="bold white", min_width=18)
    t.add_column("Status",   min_width=10)
    t.add_column("Profile",  min_width=8)
    t.add_column("Device",   style="dim", min_width=20)
    t.add_column("Locale",   style="dim")
    t.add_column("Proxy",    style="dim")
    for i, bot in enumerate(manager.bots, 1):
        status  = "[bright_green]ACTIVE[/bright_green]"  if bot.logged_in else "[bright_red]OFFLINE[/bright_red]"
        device  = f"{bot._device['manufacturer']} {bot._device['model']}" if hasattr(bot,"_device") else "—"
        locale  = bot._locale["locale"] if hasattr(bot,"_locale") else "—"
        proxy   = (bot.proxy[:28] if bot.proxy else "none")
        t.add_row(str(i), bot.username, status, bot.session.profile, device, locale, proxy)
    console.print(t)

def print_stats_table(stats):
    t = Table(show_header=True, header_style="bold cyan",
              box=box.SIMPLE_HEAD, title="  ACCOUNT STATS  (this session)")
    for col, kw in [
        ("Username",       {"style":"bold white","min_width":18}),
        ("Followers",      {"justify":"right"}),
        ("Following",      {"justify":"right"}),
        ("Posts",          {"justify":"right"}),
        ("Verified",       {"justify":"center"}),
        ("Likes Today",    {"justify":"right"}),
        ("Comments Today", {"justify":"right"}),
        ("Fatigue",        {"justify":"center"}),
    ]:
        t.add_column(col, **kw)
    for s in stats:
        if "error" in s:
            t.add_row(s["username"], "[bright_red]ERROR[/bright_red]", *[""] * 6)
        else:
            td = s.get("today", {})
            t.add_row(
                s["username"],
                str(s.get("followers","?")),
                str(s.get("following","?")),
                str(s.get("media_count","?")),
                "YES" if s.get("is_verified") else "no",
                str(td.get("likes",0)),
                str(td.get("comments",0)),
                s.get("fatigue","?"),
            )
    console.print(t)

def pick_accounts(manager):
    active = [b for b in manager.bots if b.logged_in]
    if not active:
        warn("No logged-in accounts available")
        return []
    choices = ["all"] + [b.username for b in active]
    console.print(f"  [dim]Available: {', '.join(b.username for b in active)}[/dim]")
    choice  = Prompt.ask("  Run on", choices=choices, default="all")
    return active if choice == "all" else [b for b in active if b.username == choice]

def run_on_bots(bots, fn, concurrent=True):
    if not bots: return
    if concurrent and len(bots) > 1:
        threads = [threading.Thread(target=fn, args=(b,), daemon=True) for b in bots]
        for t in threads: t.start()
        for t in threads: t.join()
    else:
        for b in bots: fn(b)

def done():
    ok("Task complete")


# ─────────────────────────────────────────────────────────────────────────────
# MENU HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def ask_concurrent() -> bool:
    return Confirm.ask("  Run accounts concurrently?", default=True)


# ─────────────────────────────────────────────────────────────────────────────
# ALL-TIME PERSISTENT STATS  (reads from data/stats.json)
# ─────────────────────────────────────────────────────────────────────────────

def menu_alltime_stats(manager):
    hdr("ALL-TIME STATS  —  data/stats.json")

    opts = [
        ("1", "All accounts overview          totals + 7-day summary"),
        ("2", "14-day daily breakdown         one account at a time"),
        ("3", "Follower growth history        up to 30 snapshots"),
        ("0", "Back"),
    ]
    for k, v in opts: console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0": return

    # ── 1. All accounts overview ─────────────────────────────────────────────
    if choice == "1":
        summaries = stats_store.get_all_accounts_summary()
        if not summaries:
            warn("No persistent stats found yet — run some tasks first")
            return

        t = Table(
            title="  ALL-TIME OVERVIEW",
            show_header=True, header_style="bold cyan",
            box=box.SIMPLE_HEAD, expand=True,
        )
        t.add_column("Account",       style="bold white", min_width=18)
        t.add_column("First Seen",    style="dim",        min_width=10)
        t.add_column("Last Active",   style="dim",        min_width=16)
        t.add_column("Followers",     justify="right")
        t.add_column("Likes ∑",       justify="right")
        t.add_column("Comments ∑",    justify="right")
        t.add_column("Follows ∑",     justify="right")
        t.add_column("Unfollow ∑",    justify="right")
        t.add_column("DMs ∑",         justify="right")
        t.add_column("Stories ∑",     justify="right")
        t.add_column("Likes 7d",      justify="right", style="dim")
        t.add_column("Follows 7d",    justify="right", style="dim")

        for s in summaries:
            at   = s["all_time"]
            w7   = s["last_7_days"]
            first = (s["first_seen"] or "—")[:10]
            last  = (s["last_active"] or "—")[:16].replace("T", " ")
            t.add_row(
                s["username"],
                first,
                last,
                str(s["followers"]),
                str(at["likes"]),
                str(at["comments"]),
                str(at["follows"]),
                str(at["unfollows"]),
                str(at["dms"]),
                str(at["story_views"]),
                str(w7["likes"]),
                str(w7["follows"]),
            )
        console.print(t)

    # ── 2. 14-day daily breakdown ────────────────────────────────────────────
    elif choice == "2":
        summaries = stats_store.get_all_accounts_summary()
        if not summaries:
            warn("No persistent stats found yet")
            return

        usernames = [s["username"] for s in summaries]
        if len(usernames) == 1:
            username = usernames[0]
        else:
            console.print("  [dim]Known accounts: " + ", ".join(usernames) + "[/dim]")
            username = Prompt.ask("  Account username", choices=usernames)

        series = stats_store.get_daily_series(username, days=14)

        t = Table(
            title=f"  14-DAY DAILY BREAKDOWN  @{username}",
            show_header=True, header_style="bold cyan",
            box=box.SIMPLE_HEAD,
        )
        t.add_column("Date",       style="bold white", min_width=12)
        t.add_column("Likes",      justify="right")
        t.add_column("Comments",   justify="right")
        t.add_column("Follows",    justify="right")
        t.add_column("Unfollows",  justify="right")
        t.add_column("DMs",        justify="right")
        t.add_column("Stories",    justify="right")
        t.add_column("Total",      justify="right", style="bold")

        for day in series:
            total = sum(day.get(k, 0) for k in stats_store.ACTION_KEYS)
            # Highlight today's row
            date_str = day["date"]
            if date_str == datetime.now().strftime("%Y-%m-%d"):
                date_str = f"[bright_cyan]{date_str}  ◄[/bright_cyan]"
            t.add_row(
                date_str,
                str(day.get("likes", 0)),
                str(day.get("comments", 0)),
                str(day.get("follows", 0)),
                str(day.get("unfollows", 0)),
                str(day.get("dms", 0)),
                str(day.get("story_views", 0)),
                f"[bold]{total}[/bold]" if total else "[dim]—[/dim]",
            )
        console.print(t)

    # ── 3. Follower growth ───────────────────────────────────────────────────
    elif choice == "3":
        summaries = stats_store.get_all_accounts_summary()
        if not summaries:
            warn("No persistent stats found yet")
            return

        usernames = [s["username"] for s in summaries]
        if len(usernames) == 1:
            username = usernames[0]
        else:
            console.print("  [dim]Known accounts: " + ", ".join(usernames) + "[/dim]")
            username = Prompt.ask("  Account username", choices=usernames)

        snapshots = stats_store.get_follower_growth(username)
        if not snapshots:
            warn(f"No follower snapshots for @{username} yet — run Account Stats (option 9) to capture one")
            return

        t = Table(
            title=f"  FOLLOWER GROWTH  @{username}  [{len(snapshots)} snapshots]",
            show_header=True, header_style="bold cyan",
            box=box.SIMPLE_HEAD,
        )
        t.add_column("Timestamp",   style="dim",        min_width=19)
        t.add_column("Followers",   justify="right",    style="bold white")
        t.add_column("Change",      justify="right")
        t.add_column("Following",   justify="right")
        t.add_column("Posts",       justify="right")

        prev_followers = None
        for snap in snapshots:
            followers = snap.get("followers", 0)
            if prev_followers is not None:
                delta = followers - prev_followers
                if delta > 0:
                    change = f"[bright_green]+{delta}[/bright_green]"
                elif delta < 0:
                    change = f"[bright_red]{delta}[/bright_red]"
                else:
                    change = "[dim]—[/dim]"
            else:
                change = "[dim]first[/dim]"
            prev_followers = followers

            t.add_row(
                snap.get("ts", "?")[:19].replace("T", " "),
                str(followers),
                change,
                str(snap.get("following", "?")),
                str(snap.get("media_count", "?")),
            )
        console.print(t)

        # Quick growth summary
        if len(snapshots) >= 2:
            first_f = snapshots[0].get("followers", 0)
            last_f  = snapshots[-1].get("followers", 0)
            net     = last_f - first_f
            sign    = "+" if net >= 0 else ""
            info(f"Net change since first snapshot:  {sign}{net} followers")


# ─────────────────────────────────────────────────────────────────────────────
# SUB-MENUS
# ─────────────────────────────────────────────────────────────────────────────

def menu_human_behaviour(manager, cfg):
    hdr("HUMAN BEHAVIOUR SIMULATION")
    console.print("[dim]  Mimics real Instagram use: warmup, feed, explore, reels, stories.[/dim]")
    console.print("[dim]  Typing simulation, fatigue modelling, activity windows, random breaks.[/dim]\n")
    opts = [
        ("1", "Full human session  [warmup + feed + explore + reels]"),
        ("2", "Scroll home feed only"),
        ("3", "Browse explore page only"),
        ("4", "Watch reels only"),
        ("5", "Watch feed stories passively"),
        ("0", "Back"),
    ]
    for k, v in opts: console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return
    engage     = Confirm.ask("  Allow incidental likes while browsing?", default=True)
    concurrent = ask_concurrent()

    if   choice == "1": fn = lambda b: b.run_human_session(engage=engage)
    elif choice == "2":
        n = int(Prompt.ask("  Posts to scroll", default="10"))
        fn = lambda b: b.scroll_feed(posts=n, engage=engage)
    elif choice == "3":
        n = int(Prompt.ask("  Posts to browse", default="15"))
        fn = lambda b: b.browse_explore(posts=n, engage=engage)
    elif choice == "4":
        n = int(Prompt.ask("  Reels to watch", default="10"))
        fn = lambda b: b.browse_reels(count=n, engage=engage)
    elif choice == "5":
        n = int(Prompt.ask("  Accounts' stories to watch", default="10"))
        fn = lambda b: b.watch_following_stories(count=n)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_like(manager, cfg):
    hdr("LIKE POSTS")
    console.print("  [1]  Like posts from a user")
    console.print("  [2]  Like posts from a hashtag")
    console.print("  [0]  Back")
    rule()
    choice = Prompt.ask("  Select", choices=["1","2","0"])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()

    if choice == "1":
        target = Prompt.ask("  Target username")
        count  = int(Prompt.ask("  Posts to like", default="5"))
        fn = lambda b: b.like_user_posts(target, count)
    else:
        hashtag = Prompt.ask("  Hashtag  [without #]")
        count   = int(Prompt.ask("  Posts to like", default="10"))
        fn = lambda b: b.like_hashtag_posts(hashtag, count)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_comment(manager, cfg):
    hdr("COMMENT ON POSTS")
    console.print("  [1]  Comment on a user's posts")
    console.print("  [2]  Comment on hashtag posts")
    console.print("  [0]  Back")
    rule()
    choice = Prompt.ask("  Select", choices=["1","2","0"])
    if choice == "0": return

    pool = cfg.get("defaults",{}).get("comments",["Great content!","Really inspiring!"])
    if Confirm.ask(f"  Use default comment pool?  [{len(pool)} comments]", default=True):
        comments = pool
    else:
        raw      = Prompt.ask("  Enter comments separated by  |")
        comments = [c.strip() for c in raw.split("|") if c.strip()]

    bots = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()

    if choice == "1":
        target = Prompt.ask("  Target username")
        count  = int(Prompt.ask("  Posts to comment on", default="3"))
        fn = lambda b: b.comment_on_user_posts(target, comments, count)
    else:
        hashtag = Prompt.ask("  Hashtag  [without #]")
        count   = int(Prompt.ask("  Posts to comment on", default="5"))
        fn = lambda b: b.comment_on_hashtag_posts(hashtag, comments, count)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_follow(manager, cfg):
    hdr("FOLLOW / UNFOLLOW")
    opts = [
        ("1", "Follow a list of users"),
        ("2", "Follow followers of a target account"),
        ("3", "Unfollow a list of users"),
        ("4", "Unfollow non-followers  [cleanup]"),
        ("0", "Back"),
    ]
    for k, v in opts: console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()

    if choice == "1":
        usernames = [u.strip() for u in Prompt.ask("  Usernames  [comma-separated]").split(",")]
        fn = lambda b: b.follow_users(usernames)
    elif choice == "2":
        target = Prompt.ask("  Target username")
        count  = int(Prompt.ask("  How many followers", default="20"))
        fn = lambda b: b.follow_user_followers(target, count)
    elif choice == "3":
        usernames = [u.strip() for u in Prompt.ask("  Usernames  [comma-separated]").split(",")]
        fn = lambda b: b.unfollow_users(usernames)
    elif choice == "4":
        limit = int(Prompt.ask("  Max unfollows", default="50"))
        fn = lambda b: b.unfollow_non_followers(limit)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_stories(manager, cfg):
    hdr("WATCH STORIES")
    console.print("  [1]  Watch stories from a specific user")
    console.print("  [2]  Watch stories from your feed")
    console.print("  [0]  Back")
    rule()
    choice = Prompt.ask("  Select", choices=["1","2","0"])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()

    if choice == "1":
        target = Prompt.ask("  Target username")
        fn = lambda b: b.watch_user_stories(target)
    else:
        count = int(Prompt.ask("  Accounts' stories to watch", default="20"))
        fn = lambda b: b.watch_following_stories(count)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_dms(manager, cfg):
    hdr("DIRECT MESSAGES")
    opts = [
        ("1", "Send DM to one user"),
        ("2", "Bulk send to a list  [rotating messages]"),
        ("3", "Auto-reply to unread DMs  [keyword matching]"),
        ("4", "View inbox summary"),
        ("0", "Back"),
    ]
    for k, v in opts: console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return

    if choice == "1":
        target = Prompt.ask("  Target username")
        msg    = Prompt.ask("  Message")
        fn = lambda b: b.send_dm(target, msg)
        run_on_bots(bots, fn, concurrent=False)

    elif choice == "2":
        usernames = [u.strip() for u in Prompt.ask("  Usernames  [comma-separated]").split(",")]
        messages  = [m.strip() for m in Prompt.ask("  Messages  [pipe-separated |]").split("|")]
        fn = lambda b: b.send_dm_to_list(usernames, messages)
        run_on_bots(bots, fn, concurrent=False)

    elif choice == "3":
        reply_map  = cfg.get("defaults",{}).get("dm_replies",{"_default":"Thanks for reaching out!"})
        info(f"Reply map loaded  {len(reply_map)} keyword(s)")
        concurrent = ask_concurrent()
        fn = lambda b: b.auto_reply_dms(reply_map)
        run_on_bots(bots, fn, concurrent)

    elif choice == "4":
        for bot in bots:
            summary = bot.get_inbox_summary()
            t = Table(title=f"  INBOX  @{bot.username}", box=box.SIMPLE_HEAD,
                      show_header=True, header_style="bold cyan")
            t.add_column("Thread", style="dim")
            t.add_column("Users")
            t.add_column("Last Message")
            t.add_column("Unread", justify="center")
            for thread in summary.get("threads", []):
                users   = ", ".join(thread["users"])
                preview = (thread["last_message"] or "")[:60]
                unread  = "[bright_cyan]YES[/bright_cyan]" if thread["unread"] else "—"
                t.add_row(str(thread["id"])[:12], users, preview, unread)
            console.print(t)
            info(f"Total: {summary.get('total_threads',0)}  Unread: {summary.get('unread_threads',0)}")

    done()


def menu_hashtag(manager, cfg):
    hdr("HASHTAG ENGAGEMENT")
    hashtag    = Prompt.ask("  Hashtag  [without #]")
    count      = int(Prompt.ask("  Posts to process", default="10"))
    do_like    = Confirm.ask("  Like posts?",      default=True)
    do_comment = Confirm.ask("  Comment?",         default=False)
    do_follow  = Confirm.ask("  Follow posters?",  default=False)

    comments = []
    if do_comment:
        pool = cfg.get("defaults",{}).get("comments",["Great content!"])
        if Confirm.ask(f"  Use default comment pool?  [{len(pool)} comments]", default=True):
            comments = pool
        else:
            comments = [c.strip() for c in Prompt.ask("  Comments  [pipe |]").split("|")]

    actions    = {"like":do_like,"comment":do_comment,"follow":do_follow,
                  "count":count,"comments":comments}
    bots       = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()
    run_on_bots(bots, lambda b: b.engage_hashtag(hashtag, actions), concurrent)
    done()




def menu_edit_images(manager, cfg):
    hdr("IMAGE EDITOR")
    console.print(f"[dim]  Resize, filter, and adjust photos to Instagram specs before posting.[/dim]\n")

    # Show available presets and filters for reference
    preset_table = Table(title="  SIZE PRESETS", box=box.SIMPLE_HEAD,
                         header_style="bold cyan", show_header=True)
    preset_table.add_column("Name",       style="bold white")
    preset_table.add_column("Dimensions", style="cyan")
    preset_table.add_column("Ratio")
    preset_table.add_column("Best for")
    preset_rows = [
        ("portrait",  "1080 x 1350", "4:5",    "Feed posts — best reach in 2025"),
        ("square",    "1080 x 1080", "1:1",     "Feed posts — classic versatile"),
        ("landscape", "1080 x 566",  "1.91:1",  "Wide scenic shots"),
        ("story",     "1080 x 1920", "9:16",    "Stories and Reels"),
        ("carousel",  "1080 x 1350", "4:5",     "All slides in a carousel"),
    ]
    for row in preset_rows:
        preset_table.add_row(*row)
    console.print(preset_table)

    filter_table = Table(title="  FILTERS", box=box.SIMPLE_HEAD,
                         header_style="bold cyan", show_header=True)
    filter_table.add_column("Name",    style="bold white", min_width=10)
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

        # Show current info
        info_data = _editor.analyse_image(path)
        console.print(Panel(
            f"  Size:  [bold]{info_data['dimensions']}[/bold]   "
            f"({info_data['size_kb']} KB)   "
            f"Ratio: [cyan]{info_data['aspect_ratio']}[/cyan]\n"
            f"  Suggested preset: [bright_cyan]{info_data['suggested_preset']}[/bright_cyan]   "
            f"{info_data['note']}"
            + (f"\n  [yellow]Warning: {info_data['quality_warning']}[/yellow]"
               if info_data['quality_warning'] else ""),
            title="  IMAGE INFO",
            border_style="dim", title_align="left",
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
            "  Filter",
            choices=list(_editor.FILTERS.keys()),
            default="none",
        )

        do_adjust = Confirm.ask("  Fine-tune brightness / contrast / saturation / sharpness?", default=False)
        brightness = contrast = saturation = sharpness = 1.0
        if do_adjust:
            brightness = float(Prompt.ask("  Brightness  [0.5 dark → 2.0 bright, 1.0 = no change]", default="1.0"))
            contrast   = float(Prompt.ask("  Contrast    [0.5 flat → 2.0 punchy]",                  default="1.0"))
            saturation = float(Prompt.ask("  Saturation  [0.0 B&W  → 3.0 vivid]",                   default="1.0"))
            sharpness  = float(Prompt.ask("  Sharpness   [0.0 blur → 3.0 sharp]",                   default="1.0"))

        do_auto = Confirm.ask("  Apply auto-enhance (auto levels + light sharpen)?", default=False)
        do_vign = Confirm.ask("  Add vignette?",                                    default=False)

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
            if not p:
                break
            if not os.path.exists(p):
                warn(f"  File not found: {p}"); continue
            paths.append(p)

        if not paths:
            warn("No images entered"); return

        info(f"Processing {len(paths)} image(s)")

        preset = Prompt.ask(
            "  Size preset  [all images will use same preset]",
            choices=list(_editor.PRESETS.keys()) + ["none"],
            default="portrait",
        )
        filter_name = Prompt.ask(
            "  Filter",
            choices=list(_editor.FILTERS.keys()),
            default="none",
        )
        do_auto    = Confirm.ask("  Auto-enhance all?",  default=False)
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
        t.add_column("Source",  style="dim")
        t.add_column("Output",  style="bold white")
        t.add_column("Status",  justify="center")
        for src, out in zip(paths, results):
            status = "[bright_green]OK[/bright_green]" if out else "[red]FAILED[/red]"
            t.add_row(
                os.path.basename(src),
                os.path.basename(str(out)) if out else "—",
                status,
            )
        console.print(t)
        ok(f"Done  {sum(1 for r in results if r)} / {len(results)} processed")

    # ── 3. Analyse ───────────────────────────────────────────────────────────
    elif choice == "3":
        console.print("  [dim]Enter image paths one per line. Empty line to finish.[/dim]")
        paths = []
        while True:
            p = Prompt.ask(f"  Image {len(paths)+1}  [blank to finish]", default="")
            if not p:
                break
            if not os.path.exists(p):
                warn(f"  File not found: {p}"); continue
            paths.append(p)

        if not paths:
            return

        t = Table(title="  IMAGE ANALYSIS", show_header=True,
                  header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("File",       style="dim",        min_width=24)
        t.add_column("Size",       min_width=10)
        t.add_column("KB",         justify="right")
        t.add_column("Ratio",      justify="right")
        t.add_column("Suggested",  style="bright_cyan")
        t.add_column("Notes",      style="dim",        min_width=30)
        for p in paths:
            try:
                data = _editor.analyse_image(p)
                note = data["note"]
                if data["quality_warning"]:
                    note = f"[yellow]{data['quality_warning']}[/yellow]"
                t.add_row(
                    os.path.basename(p),
                    data["dimensions"],
                    str(data["size_kb"]),
                    data["aspect_ratio"],
                    data["suggested_preset"],
                    note,
                )
            except Exception as e:
                t.add_row(os.path.basename(p), "—", "—", "—", "—", f"[red]{e}[/red]")
        console.print(t)

    done()

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
        caption   = Prompt.ask("  Caption")
        raw_tags  = Prompt.ask("  Hashtags  [space-separated, no #, leave blank to skip]", default="")
        location  = Prompt.ask("  Location name  [leave blank to skip]", default="")
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
        raw = Prompt.ask("  Image paths  [comma-separated, in order]")
        paths = [p.strip() for p in raw.split(",") if p.strip()]
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            warn(f"Files not found: {missing}"); return
        if len(paths) < 2:
            warn("Need at least 2 images for a carousel"); return
        caption   = Prompt.ask("  Caption")
        raw_tags  = Prompt.ask("  Hashtags  [space-separated, no #]", default="")
        location  = Prompt.ask("  Location name  [leave blank to skip]", default="")
        meta = {
            "caption":  caption,
            "hashtags": [t.strip() for t in raw_tags.split() if t.strip()],
        }
        if location: meta["location"] = location
        bots = pick_accounts(manager)
        if not bots: return
        from pathlib import Path
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
            start_ms = Prompt.ask("  Music start position  [milliseconds]", default="0")
            meta["music_start_ms"] = int(start_ms)
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
            start_ms = Prompt.ask("  Music start position  [milliseconds]", default="0")
            meta["music_start_ms"] = int(start_ms)
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
            warn("No ready posts in queue  —  add folders to posts/queue/")
            return
        info(f"Ready to publish:  {len(ready)} post(s)")
        for p in ready:
            console.print(f"  [dim]{p['name']}[/dim]  type={p['type']}  scheduled={p['scheduled_time']}")
        rule()
        if not Confirm.ask("  Publish all ready posts now?", default=True):
            return
        bots = pick_accounts(manager)
        if not bots: return
        concurrent = ask_concurrent()
        run_on_bots(bots, lambda b: b.publish_from_queue(), concurrent)
        done()

    # ── 6. View queue ─────────────────────────────────────────────────────────
    elif choice == "6":
        posts = _poster.list_queue()
        if not posts:
            info("Queue is empty  —  add folders to posts/queue/")
            return
        t = Table(title="  POST QUEUE", show_header=True,
                  header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("Folder",     style="bold white", min_width=20)
        t.add_column("Type",       min_width=12)
        t.add_column("Files",      justify="right")
        t.add_column("Scheduled",  min_width=16)
        t.add_column("Accounts",   style="dim")
        t.add_column("Ready",      justify="center")
        for p in posts:
            file_count = len(p["images"]) + (1 if p["video"] else 0)
            accounts   = ", ".join(p["meta"].get("accounts", [])) or "all"
            ready_str  = "[bright_green]YES[/bright_green]" if p["ready"] else "[dim]waiting[/dim]"
            t.add_row(
                p["name"], p["type"], str(file_count),
                str(p["scheduled_time"]), accounts, ready_str,
            )
        console.print(t)
        info(f"Queue folder:  posts/queue/  |  Done: posts/done/  |  Failed: posts/failed/")

    # ── 7. Post history ───────────────────────────────────────────────────────
    elif choice == "7":
        usernames = stats_store.get_all_usernames()
        if not usernames:
            warn("No accounts found in database"); return
        if len(usernames) == 1:
            username = usernames[0]
        else:
            console.print("  [dim]Accounts: " + ", ".join(usernames) + "[/dim]")
            username = Prompt.ask("  Account", choices=usernames)

        history = stats_store.get_post_history(username, limit=30)
        summary = stats_store.get_post_summary(username)

        # Summary panel
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
            info("No posts recorded yet")
            return

        t = Table(title=f"  LAST 30 POSTS  @{username}", show_header=True,
                  header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("Time",     style="dim",        min_width=16)
        t.add_column("Type",     min_width=12)
        t.add_column("Caption",  min_width=30)
        t.add_column("Location", style="dim")
        t.add_column("Music",    justify="center")
        t.add_column("Media PK", style="dim")
        for row in history:
            caption  = (row["caption"] or "")[:40] + ("..." if len(row.get("caption","")) > 40 else "")
            music    = "[bright_cyan]YES[/bright_cyan]" if row["has_music"] else "—"
            ts       = (row["ts"] or "")[:16].replace("T", " ")
            t.add_row(ts, row["type"] if "type" in row else row.get("post_type","?"),
                      caption, row.get("location","") or "—", music, str(row.get("media_pk",""))[:12])
        console.print(t)

    # ── 8. Find music track ID ────────────────────────────────────────────────
    elif choice == "8":
        console.print("  [dim]Searches recent reels using a hashtag to find track IDs.[/dim]")
        console.print("  [dim]Copy the track_id into your meta.yaml music_track_id field.[/dim]\n")
        bots = [b for b in manager.bots if b.logged_in]
        if not bots:
            warn("Need at least one logged-in account to search"); return
        bot     = bots[0]
        keyword = Prompt.ask("  Search hashtag  [e.g. bollywood  hiphop  lofi]")
        sample  = int(Prompt.ask("  Reels to sample", default="30"))
        with console.status("[bold cyan]  Searching reels for music...[/bold cyan]"):
            tracks = _poster.find_track_id_from_reels(bot.cl, keyword, sample)
        if not tracks:
            warn("No tracks found — try a different hashtag or larger sample size")
            return
        t = Table(title=f"  MUSIC TRACKS FOUND  #{keyword}",
                  show_header=True, header_style="bold cyan", box=box.SIMPLE_HEAD)
        t.add_column("Track ID",  style="bold white", min_width=22)
        t.add_column("Title",     min_width=28)
        t.add_column("Artist",    min_width=20)
        for tr in tracks:
            t.add_row(tr["track_id"], tr.get("title","?"), tr.get("artist","?"))
        console.print(t)
        info("Copy a Track ID and use it as  music_track_id  in your meta.yaml or in the story poster above")

    done()

def menu_scheduler(manager, cfg):
    hdr("SCHEDULER")
    schedule_cfg = cfg.get("schedule", [])
    if not schedule_cfg:
        warn("No schedule defined in config.yaml")
        return
    info(f"Loading {len(schedule_cfg)} job(s) from config")
    scheduler = build_scheduler_from_config(manager, schedule_cfg)
    ok(f"Scheduler started  —  press Ctrl+C to stop")
    try:
        scheduler.start(blocking=True)
    except KeyboardInterrupt:
        scheduler.stop()
        warn("Scheduler stopped")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

MENU_ITEMS = [
    ("1", "Human Behaviour      feed  explore  reels  stories"),
    ("2", "Like Posts           user  or  hashtag"),
    ("3", "Comment on Posts     user  or  hashtag"),
    ("4", "Follow / Unfollow    list  or  followers of target"),
    ("5", "Watch Stories        user  or  feed"),
    ("6", "Direct Messages      send  bulk  auto-reply  inbox"),
    ("7", "Hashtag Engagement   like  comment  follow"),
    ("8", "Live Dashboard       real-time account stats  [this session]"),
    ("9", "Account Stats        followers  posts  today  [+saves snapshot]"),
    ("A", "All-Time Stats       persistent history  overview  daily  growth"),
    ("P", "Publish Content      photo  carousel  story  queue  music  history"),
    ("E", "Edit Images          resize  filter  adjust  batch  analyse"),
    ("M", "Manual Task Trigger  build  presets  history  quick-fire"),
    ("T", "Run Config Tasks     tasks defined in config.yaml"),
    ("S", "Scheduler            recurring automated jobs"),
    ("0", "Exit"),
]

def main():
    os.makedirs("logs",     exist_ok=True)
    os.makedirs("sessions", exist_ok=True)
    os.makedirs("data",     exist_ok=True)   # persistent stats directory
    os.makedirs("posts/queue",  exist_ok=True)
    os.makedirs("posts/done",   exist_ok=True)
    os.makedirs("posts/failed", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
        handlers=[logging.FileHandler("logs/system.log", encoding="utf-8")],
    )

    console.print(BANNER)

    try:
        cfg = load_config("config/config.yaml")
    except FileNotFoundError:
        warn("config/config.yaml not found — copy config.example.yaml and fill in your accounts")
        sys.exit(1)
    except Exception as e:
        warn(f"Config error: {e}")
        sys.exit(1)

    manager = AccountManager(cfg["accounts"])
    print_accounts_table(manager)

    if Confirm.ask("\n  Login all accounts now?", default=True):
        with console.status("[bold cyan]  Logging in all accounts...[/bold cyan]"):
            manager.login_all(concurrent=True)
        print_accounts_table(manager)

    while True:
        hdr("MAIN MENU")
        for key, label in MENU_ITEMS:
            console.print(f"  [{key}]  {label}")
        rule()

        valid = [k for k, _ in MENU_ITEMS] + [k.lower() for k, _ in MENU_ITEMS if k.isalpha()]
        choice = Prompt.ask("  Select", choices=valid).upper()

        if   choice == "0": info("Session ended"); break
        elif choice == "1": menu_human_behaviour(manager, cfg)
        elif choice == "2": menu_like(manager, cfg)
        elif choice == "3": menu_comment(manager, cfg)
        elif choice == "4": menu_follow(manager, cfg)
        elif choice == "5": menu_stories(manager, cfg)
        elif choice == "6": menu_dms(manager, cfg)
        elif choice == "7": menu_hashtag(manager, cfg)
        elif choice == "8":
            secs = int(Prompt.ask("  Refresh for how many seconds?", default="30"))
            show_live_dashboard(manager, secs)
        elif choice == "9":
            with console.status("[bold cyan]  Fetching stats...[/bold cyan]"):
                stats = manager.get_all_stats()
            print_stats_table(stats)
        elif choice == "A":
            menu_alltime_stats(manager)
        elif choice == "P": menu_publish(manager, cfg)
        elif choice == "E": menu_edit_images(manager, cfg)
        elif choice == "M": menu_manual_trigger(manager, cfg)
        elif choice == "T":
            tasks = cfg.get("tasks", [])
            if not tasks:
                warn("No tasks defined in config.yaml")
            else:
                info(f"Running {len(tasks)} task(s) from config")
                manager.run_all_tasks(tasks)
                done()
        elif choice == "S": menu_scheduler(manager, cfg)


if __name__ == "__main__":
    main()