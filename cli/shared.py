"""
cli/shared.py  —  Shared console helpers, theme primitives, and utility functions.

Every cli/menu_*.py module imports from here.  Nothing in this file imports
from any other cli/ module, so there are no circular dependencies.
"""

import os
import threading
import logging
import yaml
from datetime import datetime

from rich.console import Console
from rich.table   import Table
from rich.prompt  import Prompt, Confirm
from rich.live    import Live
from rich         import box

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
[/bold white][dim]  Multi-Account Instagram Automation  ·  v3.0[/dim]
"""

# ─────────────────────────────────────────────────────────────────────────────
# LOG PRINTERS
# ─────────────────────────────────────────────────────────────────────────────

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

def done():
    ok("Task complete")

# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT TABLE
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
        status = "[bright_green]ACTIVE[/bright_green]" if bot.logged_in else "[bright_red]OFFLINE[/bright_red]"
        device = f"{bot._device['manufacturer']} {bot._device['model']}" if hasattr(bot, "_device") else "—"
        locale = bot._locale["locale"] if hasattr(bot, "_locale") else "—"
        proxy  = (bot.proxy[:28] if bot.proxy else "none")
        t.add_row(str(i), bot.username, status, bot.session.profile, device, locale, proxy)
    console.print(t)

def print_stats_table(stats):
    t = Table(show_header=True, header_style="bold cyan",
              box=box.SIMPLE_HEAD, title="  ACCOUNT STATS  (this session)")
    for col, kw in [
        ("Username",       {"style": "bold white", "min_width": 18}),
        ("Followers",      {"justify": "right"}),
        ("Following",      {"justify": "right"}),
        ("Posts",          {"justify": "right"}),
        ("Verified",       {"justify": "center"}),
        ("Likes Today",    {"justify": "right"}),
        ("Comments Today", {"justify": "right"}),
        ("Fatigue",        {"justify": "center"}),
    ]:
        t.add_column(col, **kw)
    for s in stats:
        if "error" in s:
            t.add_row(s["username"], "[bright_red]ERROR[/bright_red]", *[""] * 6)
        else:
            td = s.get("today", {})
            t.add_row(
                s["username"],
                str(s.get("followers", "?")),
                str(s.get("following", "?")),
                str(s.get("media_count", "?")),
                "YES" if s.get("is_verified") else "no",
                str(td.get("likes", 0)),
                str(td.get("comments", 0)),
                s.get("fatigue", "?"),
            )
    console.print(t)

# ─────────────────────────────────────────────────────────────────────────────
# LIVE DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

def build_dashboard(manager) -> Table:
    t = Table(
        title=f"  DASHBOARD   {datetime.now().strftime('%H:%M:%S')}",
        show_header=True, header_style="bold cyan",
        box=box.SIMPLE_HEAD, expand=True,
    )
    t.add_column("Account",      style="bold white", min_width=18)
    t.add_column("Status",       min_width=8)
    t.add_column("Likes",        justify="right")
    t.add_column("Comments",     justify="right")
    t.add_column("Follows",      justify="right")
    t.add_column("Unfollows",    justify="right")
    t.add_column("DMs",          justify="right")
    t.add_column("Story Views",  justify="right")
    t.add_column("Fatigue",      justify="center")
    for bot in manager.bots:
        status  = "[bright_green]ACTIVE[/bright_green]" if bot.logged_in else "[dim]offline[/dim]"
        lim     = bot.session.daily_limits
        today   = bot.session.actions_today
        fatigue = f"{bot.session.fatigue_level:.0%}"
        t.add_row(
            bot.username, status,
            f"{today['likes']}/{lim['likes']}",
            f"{today['comments']}/{lim['comments']}",
            f"{today['follows']}/{lim['follows']}",
            f"{today['unfollows']}/{lim['unfollows']}",
            f"{today['dms']}/{lim['dms']}",
            f"{today['story_views']}/{lim['story_views']}",
            fatigue,
        )
    return t

def show_live_dashboard(manager, seconds=30):
    with Live(console=console, refresh_per_second=1) as live:
        for _ in range(seconds):
            live.update(build_dashboard(manager))
            import time; time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT SELECTION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def pick_accounts(manager):
    active = [b for b in manager.bots if b.logged_in]
    if not active:
        warn("No logged-in accounts available")
        return []
    choices = ["all"] + [b.username for b in active]
    console.print(f"  [dim]Available: {', '.join(b.username for b in active)}[/dim]")
    choice = Prompt.ask("  Run on", choices=choices, default="all")
    return active if choice == "all" else [b for b in active if b.username == choice]

def run_on_bots(bots, fn, concurrent=True):
    if not bots:
        return
    if concurrent and len(bots) > 1:
        threads = [threading.Thread(target=fn, args=(b,), daemon=True) for b in bots]
        for t in threads: t.start()
        for t in threads: t.join()
    else:
        for b in bots:
            fn(b)

def ask_concurrent() -> bool:
    return Confirm.ask("  Run accounts concurrently?", default=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def save_config(cfg: dict):
    """Write config dict back to config/config.yaml."""
    with open("config/config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# CHALLENGE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def register_challenge_handler(bot):
    """
    Attach an interactive terminal OTP prompt to a bot before login.

    Uses plain print() + input() intentionally — NOT Rich Prompt.ask() —
    because instagrapi fires this callback while an active console.status()
    spinner may be running.  Rich's input() raises KeyboardInterrupt inside
    a spinner; plain builtins.input() always works.
    """
    try:
        from instagrapi.mixins.challenge import ChallengeChoice as _CC
    except ImportError:
        _CC = None

    def _ask_code(username, choice):
        import builtins
        if _CC and choice == _CC.EMAIL:
            kind = "EMAIL"
        elif _CC and choice == _CC.SMS:
            kind = "SMS"
        else:
            kind = "EMAIL/SMS"

        # console.print is safe (output only) — only input() was the problem
        console.print()
        console.print(f"  [bold bright_yellow]>> CHALLENGE: @{username}[/bold bright_yellow]")
        console.print(f"  Instagram sent a [bold]{kind}[/bold] code to your inbox.")
        console.print(f"  Check your inbox and type the code below, then press Enter.")
        console.print()

        while True:
            code = builtins.input(f"  6-digit code for @{username}: ").strip()
            if len(code) == 6 and code.isdigit():
                return code
            builtins.print(f"  '{code}' is not valid — must be exactly 6 digits. Try again.")

    bot.set_challenge_code_handler(_ask_code)