"""
multi_control.py  —  Multi-Account Simultaneous Action Controller
Assign different actions to different accounts and run them all at once.
Live combined progress table auto-refreshes while jobs are running.

CONCEPTS
────────
  Job       — one (account, action, params) assignment
  Plan      — a collection of jobs to run together
  Preset    — a named saved plan stored in data/mc_presets.json

FLOW
────
  1. User builds a Plan — picks accounts, assigns each an action + params
  2. User optionally saves the Plan as a named Preset
  3. Runner spawns one thread per Job
  4. Rich Live panel shows combined live progress as jobs execute
  5. Summary table shows results when all threads finish
"""

import json
import threading
import time
from pathlib  import Path
from datetime import datetime
from copy     import deepcopy

from rich.console import Console
from rich.table   import Table
from rich.live    import Live
from rich.panel   import Panel
from rich.text    import Text
from rich         import box

# ─────────────────────────────────────────────────────────────────────────────
# PRESET STORAGE
# ─────────────────────────────────────────────────────────────────────────────

PRESETS_FILE = Path("data/mc_presets.json")


def load_presets() -> dict:
    try:
        return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_presets(presets: dict):
    PRESETS_FILE.parent.mkdir(exist_ok=True)
    PRESETS_FILE.write_text(
        json.dumps(presets, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ACTION CATALOGUE
# Maps action keys → human label + required params + bot method call
# ─────────────────────────────────────────────────────────────────────────────

ACTIONS = {
    "like_user":        "Like posts from a user",
    "like_hashtag":     "Like posts from a hashtag",
    "comment_user":     "Comment on a user's posts",
    "comment_hashtag":  "Comment on hashtag posts",
    "follow_user":      "Follow followers of a target account",
    "follow_list":      "Follow a list of users",
    "unfollow_non":     "Unfollow non-followers",
    "watch_stories":    "Watch stories of a user",
    "watch_feed":       "Watch feed stories passively",
    "hashtag_engage":   "Hashtag engagement (like+comment+follow)",
    "human_session":    "Run a full human browsing session",
    "send_dm":          "Send a DM to one user",
    "bulk_dm":          "Bulk DM a list of users",
    "post_photo":       "Post a single photo",
    "post_story":       "Post a photo story",
    "publish_queue":    "Publish ready posts from queue",
}

ACTION_KEYS = list(ACTIONS.keys())


def _run_action(bot, action: str, params: dict, state: dict):
    """
    Execute one action on one bot. Updates state dict in place for live display.
    state keys: status, result, error, started_at, finished_at
    """
    state["status"]     = "running"
    state["started_at"] = datetime.now().strftime("%H:%M:%S")

    try:
        r = None

        if action == "like_user":
            r = bot.like_user_posts(params["target"], params.get("count", 5))

        elif action == "like_hashtag":
            r = bot.like_hashtag_posts(params["hashtag"], params.get("count", 10))

        elif action == "comment_user":
            r = bot.comment_on_user_posts(
                params["target"],
                params.get("comments", ["Great!"]),
                params.get("count", 3),
            )

        elif action == "comment_hashtag":
            r = bot.comment_on_hashtag_posts(
                params["hashtag"],
                params.get("comments", ["Great!"]),
                params.get("count", 5),
            )

        elif action == "follow_user":
            r = bot.follow_user_followers(params["target"], params.get("count", 20))

        elif action == "follow_list":
            r = bot.follow_users(params.get("usernames", []))

        elif action == "unfollow_non":
            r = bot.unfollow_non_followers(params.get("limit", 50))

        elif action == "watch_stories":
            r = bot.watch_user_stories(params["target"])

        elif action == "watch_feed":
            r = bot.watch_following_stories(params.get("count", 20))

        elif action == "hashtag_engage":
            actions_cfg = {
                "like":     params.get("like",    True),
                "comment":  params.get("comment", False),
                "follow":   params.get("follow",  False),
                "count":    params.get("count",   10),
                "comments": params.get("comments", ["Great!"]),
            }
            r = bot.engage_hashtag(params["hashtag"], actions_cfg)

        elif action == "human_session":
            bot.run_human_session(engage=params.get("engage", True))
            r = "done"

        elif action == "send_dm":
            r = bot.send_dm(params["target"], params["message"])

        elif action == "bulk_dm":
            r = bot.send_dm_to_list(
                params.get("usernames", []),
                params.get("messages",  ["Hey!"]),
            )

        elif action == "post_photo":
            r = bot.post_photo(params["image_path"], params.get("meta", {}))

        elif action == "post_story":
            r = bot.post_story_photo(params["image_path"], params.get("meta", {}))

        elif action == "publish_queue":
            r = bot.publish_from_queue()

        state["status"]      = "done"
        state["result"]      = str(r) if r is not None else "ok"

    except Exception as e:
        state["status"] = "error"
        state["error"]  = str(e)[:80]

    state["finished_at"] = datetime.now().strftime("%H:%M:%S")


# ─────────────────────────────────────────────────────────────────────────────
# LIVE DASHBOARD BUILDER
# ─────────────────────────────────────────────────────────────────────────────

STATUS_STYLE = {
    "pending": "[dim]waiting[/dim]",
    "running": "[bold bright_cyan]running[/bold bright_cyan]",
    "done":    "[bright_green]done[/bright_green]",
    "error":   "[bright_red]error[/bright_red]",
}


def _build_progress_table(jobs: list, states: list) -> Table:
    t = Table(
        title=f"  MULTI-CONTROL  ·  {datetime.now().strftime('%H:%M:%S')}",
        show_header=True, header_style="bold cyan",
        box=box.SIMPLE_HEAD, expand=True,
    )
    t.add_column("Account",  style="bold white", min_width=18)
    t.add_column("Action",   min_width=22)
    t.add_column("Params",   style="dim",   min_width=28)
    t.add_column("Status",   justify="center", min_width=10)
    t.add_column("Started",  style="dim",   min_width=8)
    t.add_column("Finished", style="dim",   min_width=8)
    t.add_column("Result",   style="dim",   min_width=16)

    for job, st in zip(jobs, states):
        status_str = STATUS_STYLE.get(st["status"], st["status"])
        result_str = ""
        if st["status"] == "done":
            result_str = st.get("result", "ok")[:24]
        elif st["status"] == "error":
            result_str = f"[bright_red]{st.get('error','?')[:24]}[/bright_red]"

        # Build compact param summary
        p = job["params"]
        param_parts = []
        if "target"   in p: param_parts.append(f"@{p['target']}")
        if "hashtag"  in p: param_parts.append(f"#{p['hashtag']}")
        if "count"    in p: param_parts.append(f"n={p['count']}")
        if "limit"    in p: param_parts.append(f"limit={p['limit']}")
        if "message"  in p: param_parts.append(f"\"{p['message'][:20]}\"")
        if "usernames" in p: param_parts.append(f"{len(p['usernames'])} users")
        param_str = "  ".join(param_parts) or "—"

        t.add_row(
            f"@{job['username']}",
            ACTIONS.get(job["action"], job["action"]),
            param_str,
            status_str,
            st.get("started_at",  "—"),
            st.get("finished_at", "—"),
            result_str,
        )

    # Footer summary
    total   = len(states)
    running = sum(1 for s in states if s["status"] == "running")
    done_   = sum(1 for s in states if s["status"] == "done")
    errors  = sum(1 for s in states if s["status"] == "error")
    pending = sum(1 for s in states if s["status"] == "pending")

    t.caption = (
        f"  Total: {total}   "
        f"[bright_cyan]Running: {running}[/bright_cyan]   "
        f"[bright_green]Done: {done_}[/bright_green]   "
        f"[bright_red]Errors: {errors}[/bright_red]   "
        f"[dim]Pending: {pending}[/dim]"
    )
    return t


# ─────────────────────────────────────────────────────────────────────────────
# PLAN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_plan(bots_by_username: dict, jobs: list, console: Console):
    """
    Execute a list of jobs simultaneously, one thread per job.
    Shows a live auto-refreshing progress table until all threads finish.

    bots_by_username: {username: InstagramBot}
    jobs: [{"username", "action", "params"}, ...]
    """
    # Initialise per-job state objects
    states = [
        {"status": "pending", "result": "", "error": "",
         "started_at": "—", "finished_at": "—"}
        for _ in jobs
    ]

    # Spawn threads
    threads = []
    for job, state in zip(jobs, states):
        bot = bots_by_username.get(job["username"])
        if bot is None or not bot.logged_in:
            state["status"]      = "error"
            state["error"]       = "not logged in"
            state["started_at"]  = datetime.now().strftime("%H:%M:%S")
            state["finished_at"] = state["started_at"]
            continue

        t = threading.Thread(
            target=_run_action,
            args=(bot, job["action"], job["params"], state),
            daemon=True,
        )
        threads.append(t)

    # Start all at once
    for t in threads:
        t.start()

    # Live display while running
    with Live(console=console, refresh_per_second=2, screen=False) as live:
        while any(t.is_alive() for t in threads):
            live.update(_build_progress_table(jobs, states))
            time.sleep(0.5)
        # Final render
        live.update(_build_progress_table(jobs, states))

    # Print final table outside live so it stays on screen
    console.print(_build_progress_table(jobs, states))

    # Summary
    done_count  = sum(1 for s in states if s["status"] == "done")
    error_count = sum(1 for s in states if s["status"] == "error")
    console.print(
        f"\n  [bright_green]Completed: {done_count}[/bright_green]  "
        f"[bright_red]Errors: {error_count}[/bright_red]  "
        f"out of {len(jobs)} jobs"
    )

    return states