"""
cli/menu_multicontrol.py  —  Multi-Account Simultaneous Action Controller menu.
"""

import copy
import os
from datetime import datetime

from rich.prompt import Prompt, Confirm
from rich.table  import Table
from rich        import box

import multi_control as _mc
from cli.shared import console, hdr, rule, ok, info, warn


def _print_plan(plan: list):
    if not plan:
        console.print("  [dim]No jobs in plan yet.[/dim]")
        return
    t = Table(title="  CURRENT PLAN", show_header=True,
              header_style="bold cyan", box=box.SIMPLE_HEAD)
    t.add_column("#",          style="dim", width=3)
    t.add_column("Account",    style="bold white", min_width=18)
    t.add_column("Action",     min_width=22)
    t.add_column("Key params", style="dim")
    for i, job in enumerate(plan, 1):
        p = job["params"]
        parts = []
        if "target"     in p: parts.append(f"@{p['target']}")
        if "hashtag"    in p: parts.append(f"#{p['hashtag']}")
        if "count"      in p: parts.append(f"n={p['count']}")
        if "limit"      in p: parts.append(f"limit={p['limit']}")
        if "message"    in p: parts.append(f'"{p["message"][:20]}"')
        if "usernames"  in p: parts.append(f"{len(p['usernames'])} users")
        if "image_path" in p: parts.append(os.path.basename(p["image_path"]))
        t.add_row(str(i), f"@{job['username']}",
                  _mc.ACTIONS.get(job["action"], job["action"]),
                  "  ".join(parts) or "—")
    console.print(t)


def _show_actions_table():
    t = Table(show_header=True, header_style="bold cyan",
              box=box.SIMPLE_HEAD, title="  AVAILABLE ACTIONS")
    t.add_column("#",           style="dim", width=4)
    t.add_column("Key",         style="bold white", min_width=16)
    t.add_column("Description")
    for i, (k, v) in enumerate(_mc.ACTIONS.items(), 1):
        t.add_row(str(i), k, v)
    console.print(t)


def _prompt_action_params(action: str, cfg: dict) -> dict | None:
    console.print(f"  [dim]Configuring: {_mc.ACTIONS[action]}[/dim]")
    params = {}

    if action in ("like_user", "comment_user", "follow_user", "watch_stories", "send_dm"):
        params["target"] = Prompt.ask("    Target username").strip().lstrip("@")
        if not params["target"]: return None

    if action in ("like_hashtag", "comment_hashtag", "hashtag_engage"):
        params["hashtag"] = Prompt.ask("    Hashtag [without #]").strip().lstrip("#")
        if not params["hashtag"]: return None

    if action in ("like_user", "comment_user"):
        params["count"] = int(Prompt.ask("    Posts", default="5"))
    if action in ("like_hashtag", "comment_hashtag"):
        params["count"] = int(Prompt.ask("    Posts", default="10"))
    if action == "follow_user":
        params["count"] = int(Prompt.ask("    Followers to follow", default="20"))
    if action == "watch_feed":
        params["count"] = int(Prompt.ask("    Accounts' stories to watch", default="20"))
    if action == "unfollow_non":
        params["limit"] = int(Prompt.ask("    Max unfollows", default="50"))
    if action == "follow_list":
        raw = Prompt.ask("    Usernames [comma-separated]")
        params["usernames"] = [u.strip() for u in raw.split(",") if u.strip()]
        if not params["usernames"]: return None

    if action in ("comment_user", "comment_hashtag", "hashtag_engage"):
        pool = cfg.get("defaults", {}).get("comments", ["Great content!", "Really inspiring!"])
        if Confirm.ask(f"    Use default comment pool? [{len(pool)} comments]", default=True):
            params["comments"] = pool
        else:
            raw = Prompt.ask("    Comments [pipe-separated |]")
            params["comments"] = [c.strip() for c in raw.split("|") if c.strip()]

    if action == "hashtag_engage":
        params["count"]   = int(Prompt.ask("    Posts to process", default="10"))
        params["like"]    = Confirm.ask("    Like?",    default=True)
        params["comment"] = Confirm.ask("    Comment?", default=False)
        params["follow"]  = Confirm.ask("    Follow?",  default=False)

    if action == "send_dm":
        params["message"] = Prompt.ask("    Message")
        if not params["message"]: return None
    if action == "bulk_dm":
        raw = Prompt.ask("    Usernames [comma-separated]")
        params["usernames"] = [u.strip() for u in raw.split(",") if u.strip()]
        raw_msgs = Prompt.ask("    Messages [pipe-separated |]")
        params["messages"] = [m.strip() for m in raw_msgs.split("|") if m.strip()]
        if not params["usernames"] or not params["messages"]: return None

    if action == "human_session":
        params["engage"] = Confirm.ask("    Allow incidental likes while browsing?", default=True)

    if action in ("post_photo", "post_story"):
        params["image_path"] = Prompt.ask("    Full path to image file")
        if not params["image_path"]: return None
        caption  = Prompt.ask("    Caption", default="")
        raw_tags = Prompt.ask("    Hashtags [space-separated, no #]", default="")
        params["meta"] = {
            "caption":  caption,
            "hashtags": [t.strip() for t in raw_tags.split() if t.strip()],
        }
        loc = Prompt.ask("    Location [blank to skip]", default="")
        if loc: params["meta"]["location"] = loc

    return params


def menu_multi_control(manager, cfg):
    plan: list = []

    while True:
        hdr("MULTI-CONTROL  —  SIMULTANEOUS ACTION RUNNER")
        console.print("[dim]  Assign different actions to different accounts, then run them all at once.[/dim]\n")
        _print_plan(plan)
        rule()

        active_bots = [b for b in manager.bots if b.logged_in]
        if not active_bots:
            warn("No logged-in accounts. Use [C] Account Manager to login first.")
            return

        opts = [
            ("1", "Add job           assign an action to one account"),
            ("2", "Add same job      same action to multiple / all accounts"),
            ("3", "Remove job        delete a job from the plan"),
            ("4", "Clear plan        start fresh"),
            ("5", "Run plan          execute all jobs simultaneously"),
            ("6", "Save as preset    save this plan for reuse"),
            ("7", "Load preset       load a saved plan"),
            ("8", "Delete preset     remove a saved plan"),
            ("0", "Back"),
        ]
        for k, v in opts:
            console.print(f"  [{k}]  {v}")
        rule()
        choice = Prompt.ask("  Select", choices=[o[0] for o in opts])

        if choice == "0":
            break

        elif choice == "1":
            username = Prompt.ask("  Account", choices=[b.username for b in active_bots])
            console.print()
            _show_actions_table()
            action = Prompt.ask("  Action key", choices=_mc.ACTION_KEYS)
            params = _prompt_action_params(action, cfg)
            if params is None:
                warn("Cancelled"); continue
            plan.append({"username": username, "action": action, "params": params})
            ok(f"Job added: @{username} → {_mc.ACTIONS[action]}")

        elif choice == "2":
            usernames_all = [b.username for b in active_bots]
            _show_actions_table()
            action = Prompt.ask("  Action key", choices=_mc.ACTION_KEYS)
            params = _prompt_action_params(action, cfg)
            if params is None:
                warn("Cancelled"); continue
            console.print(f"  [dim]Accounts: {', '.join(usernames_all)}[/dim]")
            sel     = Prompt.ask("  Apply to", choices=["all"] + usernames_all, default="all")
            targets = usernames_all if sel == "all" else [sel]
            for uname in targets:
                plan.append({"username": uname, "action": action,
                             "params": copy.deepcopy(params)})
            ok(f"Added {len(targets)} job(s): {action}")

        elif choice == "3":
            if not plan:
                warn("Plan is empty"); continue
            _print_plan(plan)
            idx = int(Prompt.ask("  Remove job #", default="1")) - 1
            if 0 <= idx < len(plan):
                removed = plan.pop(idx)
                ok(f"Removed job {idx+1}: @{removed['username']} → {removed['action']}")
            else:
                warn("Invalid job number")

        elif choice == "4":
            if plan and Confirm.ask("  Clear all jobs?", default=False):
                plan.clear()
                ok("Plan cleared")

        elif choice == "5":
            if not plan:
                warn("Plan is empty — add at least one job first"); continue
            _print_plan(plan)
            if not Confirm.ask(f"\n  Run {len(plan)} job(s) simultaneously now?", default=True):
                continue
            bots_map = {b.username: b for b in active_bots}
            info(f"Launching {len(plan)} job(s) across {len(set(j['username'] for j in plan))} account(s)...")
            _mc.run_plan(bots_map, plan, console)

        elif choice == "6":
            if not plan:
                warn("Plan is empty — nothing to save"); continue
            name = Prompt.ask("  Preset name  [e.g. morning_routine]").strip()
            if not name:
                warn("Name cannot be empty"); continue
            presets = _mc.load_presets()
            if name in presets and not Confirm.ask(f"  Preset '{name}' already exists. Overwrite?", default=False):
                continue
            presets[name] = {"jobs": plan, "saved_at": datetime.now().isoformat(timespec="seconds")}
            _mc.save_presets(presets)
            ok(f"Preset '{name}' saved  ({len(plan)} jobs)")

        elif choice == "7":
            presets = _mc.load_presets()
            if not presets:
                warn("No saved presets found"); continue
            t = Table(title="  SAVED PRESETS", show_header=True,
                      header_style="bold cyan", box=box.SIMPLE_HEAD)
            t.add_column("Name",     style="bold white")
            t.add_column("Jobs",     justify="right")
            t.add_column("Saved at", style="dim")
            t.add_column("Accounts", style="dim")
            for pname, pdata in presets.items():
                jobs     = pdata.get("jobs", [])
                accounts = ", ".join(sorted(set(j["username"] for j in jobs)))
                t.add_row(pname, str(len(jobs)),
                          pdata.get("saved_at","?")[:16].replace("T"," "),
                          accounts[:40])
            console.print(t)
            name        = Prompt.ask("  Load preset", choices=list(presets.keys()))
            loaded_jobs = presets[name]["jobs"]
            loaded_set  = {b.username for b in manager.bots}
            missing     = [j["username"] for j in loaded_jobs if j["username"] not in loaded_set]
            if missing:
                warn(f"These accounts aren't in this session: {', '.join(set(missing))}")
                warn("Their jobs will fail. Use [C] Account Manager to add them first.")
            if Confirm.ask(f"  Replace current plan with '{name}'?", default=True):
                plan = loaded_jobs[:]
                ok(f"Loaded preset '{name}'  ({len(plan)} jobs)")

        elif choice == "8":
            presets = _mc.load_presets()
            if not presets:
                warn("No saved presets found"); continue
            name = Prompt.ask("  Delete preset", choices=list(presets.keys()))
            if Confirm.ask(f"  Delete preset '{name}'?", default=False):
                del presets[name]
                _mc.save_presets(presets)
                ok(f"Preset '{name}' deleted")