"""
cli/menu_stats.py  —  Stats menus: session stats, all-time stats, follower growth.
"""

from datetime import datetime

from rich.prompt import Prompt
from rich.table  import Table
from rich.panel  import Panel
from rich        import box

import stats_store
from cli.shared import (
    console, hdr, rule, ok, info, warn,
    print_stats_table, show_live_dashboard,
)


def menu_account_stats(manager):
    """Option 9 — live API fetch of current session stats with snapshot save."""
    with console.status("[bold cyan]  Fetching stats...[/bold cyan]"):
        stats = manager.get_all_stats()
    print_stats_table(stats)


def menu_alltime_stats(manager):
    hdr("ALL-TIME STATS")

    opts = [
        ("1", "All accounts overview          totals + 7-day summary"),
        ("2", "14-day daily breakdown         one account at a time"),
        ("3", "Follower growth history        up to 30 snapshots"),
        ("0", "Back"),
    ]
    for k, v in opts:
        console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0":
        return

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
        t.add_column("Account",    style="bold white", min_width=18)
        t.add_column("First Seen", style="dim",        min_width=10)
        t.add_column("Last Active",style="dim",        min_width=16)
        t.add_column("Followers",  justify="right")
        t.add_column("Likes ∑",    justify="right")
        t.add_column("Comments ∑", justify="right")
        t.add_column("Follows ∑",  justify="right")
        t.add_column("Unfollow ∑", justify="right")
        t.add_column("DMs ∑",      justify="right")
        t.add_column("Stories ∑",  justify="right")
        t.add_column("Likes 7d",   justify="right", style="dim")
        t.add_column("Follows 7d", justify="right", style="dim")

        for s in summaries:
            at    = s["all_time"]
            w7    = s["last_7_days"]
            first = (s["first_seen"] or "—")[:10]
            last  = (s["last_active"] or "—")[:16].replace("T", " ")
            t.add_row(
                s["username"], first, last,
                str(s["followers"]),
                str(at["likes"]),   str(at["comments"]),
                str(at["follows"]), str(at["unfollows"]),
                str(at["dms"]),     str(at["story_views"]),
                str(w7["likes"]),   str(w7["follows"]),
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
        t.add_column("Date",      style="bold white", min_width=12)
        t.add_column("Likes",     justify="right")
        t.add_column("Comments",  justify="right")
        t.add_column("Follows",   justify="right")
        t.add_column("Unfollows", justify="right")
        t.add_column("DMs",       justify="right")
        t.add_column("Stories",   justify="right")
        t.add_column("Total",     justify="right", style="bold")

        for day in series:
            total    = sum(day.get(k, 0) for k in stats_store.ACTION_KEYS)
            date_str = day["date"]
            if date_str == datetime.now().strftime("%Y-%m-%d"):
                date_str = f"[bright_cyan]{date_str}  ◄[/bright_cyan]"
            t.add_row(
                date_str,
                str(day.get("likes",        0)),
                str(day.get("comments",     0)),
                str(day.get("follows",      0)),
                str(day.get("unfollows",    0)),
                str(day.get("dms",          0)),
                str(day.get("story_views",  0)),
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
        t.add_column("Timestamp", style="dim",       min_width=19)
        t.add_column("Followers", justify="right",   style="bold white")
        t.add_column("Change",    justify="right")
        t.add_column("Following", justify="right")
        t.add_column("Posts",     justify="right")

        prev_followers = None
        for snap in snapshots:
            followers = snap.get("followers", 0)
            if prev_followers is not None:
                delta  = followers - prev_followers
                change = (f"[bright_green]+{delta}[/bright_green]" if delta > 0
                          else f"[bright_red]{delta}[/bright_red]" if delta < 0
                          else "[dim]—[/dim]")
            else:
                change = "[dim]first[/dim]"
            prev_followers = followers
            t.add_row(
                snap.get("ts", "?")[:19].replace("T", " "),
                str(followers), change,
                str(snap.get("following",  "?")),
                str(snap.get("media_count","?")),
            )
        console.print(t)

        if len(snapshots) >= 2:
            first_f = snapshots[0].get("followers", 0)
            last_f  = snapshots[-1].get("followers", 0)
            net     = last_f - first_f
            info(f"Net change since first snapshot:  {'+' if net >= 0 else ''}{net} followers")