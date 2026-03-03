"""
InstaAuto  cli.py  v3.0  —  Entry point

This file is intentionally thin: it wires together the cli/ package modules
and owns only startup logic (config, session restore, keep-alive, main loop).

Menu modules live in cli/:
  shared.py             — console, theme helpers, utilities
  menu_engagement.py    — human behaviour, like, comment, follow, stories, DMs, hashtag
  menu_stats.py         — session stats, all-time stats, follower growth
  menu_publish.py       — publish content
  menu_images.py        — image editor
  menu_accounts.py      — account manager + account creator
  menu_multicontrol.py  — multi-account simultaneous action runner

Supporting engines:
  bot_engine.py         — Instagram bot core
  account_creator.py    — new account registration
  multi_control.py      — parallel job runner
  poster.py             — publishing engine
  image_editor.py       — image processing
  stats_store.py        — SQLite persistence
"""

import sys
import os
import logging

from rich.prompt import Prompt, Confirm

from config_loader   import load_config
from account_manager import AccountManager
from scheduler       import build_scheduler_from_config
from task_runner     import menu_manual_trigger
import stats_store

# ── cli package ───────────────────────────────────────────────────────────────
from cli.shared           import (console, BANNER, hdr, rule, ok, info, warn, done,
                                  print_accounts_table, print_stats_table,
                                  show_live_dashboard, register_challenge_handler,
                                  save_config)
from cli.menu_engagement  import (menu_human_behaviour, menu_like, menu_comment,
                                  menu_follow, menu_stories, menu_dms, menu_hashtag)
from cli.menu_stats       import menu_alltime_stats, menu_account_stats
from cli.menu_publish     import menu_publish
from cli.menu_images      import menu_edit_images
from cli.menu_accounts    import menu_account_manager
from cli.menu_multicontrol import menu_multi_control
from cli.menu_proxy       import menu_proxy

# ─────────────────────────────────────────────────────────────────────────────
# MAIN MENU ITEMS
# ─────────────────────────────────────────────────────────────────────────────

MENU_ITEMS = [
    ("1", "Human Behaviour      simulate real browsing sessions"),
    ("2", "Like Posts           by user or hashtag"),
    ("3", "Comment              on user or hashtag posts"),
    ("4", "Follow / Unfollow    targeted follow + non-follower cleanup"),
    ("5", "Watch Stories        user or feed"),
    ("6", "Direct Messages      send DMs or auto-reply"),
    ("7", "Hashtag Engagement   like + comment + follow in one pass"),
    ("8", "Live Dashboard       real-time session monitor"),
    ("9", "Account Stats        fetch follower counts + session totals"),
    ("A", "All-Time Stats       persistent history + follower growth"),
    ("P", "Publish Content      photos  carousels  stories  queue"),
    ("E", "Edit Images          resize  filter  adjust  batch"),
    ("M", "Manual Trigger       run a task from config.yaml manually"),
    ("T", "Run All Tasks        execute every task in config.yaml"),
    ("S", "Scheduler            start the background cron scheduler"),
    ("C", "Account Manager      add  remove  login  keep-alive  new account"),
    ("X", "Multi-Control        simultaneous actions across accounts"),
    ("R", "Proxy Manager        configure providers  assign per-account proxies"),
    ("0", "Exit"),
]


def main():
    os.makedirs("logs",         exist_ok=True)
    os.makedirs("sessions",     exist_ok=True)
    os.makedirs("data",         exist_ok=True)
    os.makedirs("posts/queue",  exist_ok=True)
    os.makedirs("posts/done",   exist_ok=True)
    os.makedirs("posts/failed", exist_ok=True)
    logging.basicConfig(
        level    = logging.INFO,
        format   = "%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
        handlers = [logging.FileHandler("logs/system.log", encoding="utf-8")],
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

    # ── Apply stored proxies BEFORE login (proxy must be set first) ──────────
    from proxy_manager import get_proxy_manager
    _pm = get_proxy_manager()
    _applied = _pm.apply_to_all_bots(manager)
    _n = sum(1 for v in _applied.values() if v)
    if _n:
        info(f"Proxy loaded for {_n} account(s) from config/proxies.yaml")

    print_accounts_table(manager)

    # ── Session restore ───────────────────────────────────────────────────────
    # Accounts with a session file: bot.login() handles everything:
    #   fresh session (<6h old)  -> loaded instantly, zero API calls
    #   older session            -> verified with one timeline ping
    #   expired session          -> auto-relogin via cl.relogin()
    # Accounts without a session file: prompt once, then credential login.
    has_sessions = [b for b in manager.bots if b.session_file.exists()]
    no_sessions  = [b for b in manager.bots if not b.session_file.exists()]

    if has_sessions:
        _fresh = [b for b in has_sessions if not b._session_needs_verify()]
        _stale = [b for b in has_sessions if b._session_needs_verify()]
        if _fresh:
            info(f"{len(_fresh)} account(s) have fresh sessions — loading instantly")
        if _stale:
            info(f"{len(_stale)} account(s) have older sessions — will verify with Instagram")
        for bot in has_sessions:
            register_challenge_handler(bot)
            label = "Restoring" if not bot._session_needs_verify() else "Verifying"
            info(f"{label} @{bot.username}...")
            ok_ = bot.login()
            if ok_:
                ok(f"@{bot.username}  {'instant restore' if label == 'Restoring' else 'verified OK'}")
            else:
                warn(f"@{bot.username}  session expired — use [C] -> Login account to re-authenticate")

    if no_sessions:
        info(f"{len(no_sessions)} account(s) have no saved session")
        if Confirm.ask("  Login these accounts now?", default=True):
            for bot in no_sessions:
                register_challenge_handler(bot)
                info(f"Logging in @{bot.username}...")
                ok_ = bot.login()
                ok(f"@{bot.username} logged in") if ok_ else warn(f"@{bot.username} login failed")

    # ── Keep-alive: only if configured (default OFF) ──────────────────────────
    # Set keep_alive_hours: 2 in config.yaml to enable background pinging.
    # Only useful when leaving the CLI running for hours unattended.
    keepalive_hrs = cfg.get("keep_alive_hours", 0)
    if keepalive_hrs and keepalive_hrs > 0:
        started = 0
        for bot in manager.bots:
            if bot.logged_in:
                bot.start_keepalive(keepalive_hrs)
                started += 1
        if started:
            info(f"Keep-alive started for {started} account(s)  ping every {keepalive_hrs}h")
    else:
        info("Keep-alive off  (set keep_alive_hours: 2 in config.yaml to enable)")

    print_accounts_table(manager)

    # ── Main loop ─────────────────────────────────────────────────────────────
    while True:
        hdr("MAIN MENU")
        for key, label in MENU_ITEMS:
            console.print(f"  [{key}]  {label}")
        rule()

        valid  = [k for k, _ in MENU_ITEMS] + [k.lower() for k, _ in MENU_ITEMS if k.isalpha()]
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
            menu_account_stats(manager)
        elif choice == "A": menu_alltime_stats(manager)
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
        elif choice == "C": menu_account_manager(manager, cfg)
        elif choice == "X": menu_multi_control(manager, cfg)
        elif choice == "R": menu_proxy(manager, cfg)


def menu_scheduler(manager, cfg):
    hdr("SCHEDULER")
    schedule_cfg = cfg.get("schedule", [])
    if not schedule_cfg:
        warn("No schedule defined in config.yaml")
        return
    info(f"Loading {len(schedule_cfg)} job(s) from config")
    scheduler = build_scheduler_from_config(manager, schedule_cfg)
    ok("Scheduler started  —  press Ctrl+C to stop")
    try:
        scheduler.start(blocking=True)
    except KeyboardInterrupt:
        scheduler.stop()
        warn("Scheduler stopped")


if __name__ == "__main__":
    main()