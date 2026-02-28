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
    ("M", "Manual Task Trigger  build  presets  history  quick-fire"),
    ("T", "Run Config Tasks     tasks defined in config.yaml"),
    ("S", "Scheduler            recurring automated jobs"),
    ("0", "Exit"),
]

def main():
    os.makedirs("logs",     exist_ok=True)
    os.makedirs("sessions", exist_ok=True)
    os.makedirs("data",     exist_ok=True)   # persistent stats directory
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

        valid = [k for k, _ in MENU_ITEMS] + [k.lower() for k, _ in MENU_ITEMS]
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