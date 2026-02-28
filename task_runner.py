"""
Manual Task Runner
Build, save, run, and manage tasks on the fly.
No emojis. Clean board-style output.
"""

import json
import time
import threading
from pathlib   import Path
from datetime  import datetime
from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.prompt  import Prompt, Confirm
from rich.syntax  import Syntax
from rich         import box

console = Console()

PRESETS_FILE = Path("config/task_presets.json")
HISTORY_FILE = Path("logs/task_history.json")

SEP = "─" * 62

def hdr(title: str):
    console.print(f"\n[bold cyan]{'═'*62}[/bold cyan]")
    console.print(f"[bold cyan]  {title}[/bold cyan]")
    console.print(f"[bold cyan]{'═'*62}[/bold cyan]")

def info(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    console.print(f"[dim]{ts}[/dim]  [white]  ·   {msg}[/white]")

def ok(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    console.print(f"[dim]{ts}[/dim]  [bright_green] OK   {msg}[/bright_green]")

def warn(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    console.print(f"[dim]{ts}[/dim]  [bright_red]  !   {msg}[/bright_red]")

def rule():
    console.print(f"[dim]{SEP}[/dim]")


# ─────────────────────────────────────────────────────────────────────────────
# TASK DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

TASK_DEFINITIONS = {
    "like_user_posts":        {"label": "Like posts from a user",
        "fields": [
            {"key":"target", "prompt":"Target username",     "type":"str"},
            {"key":"count",  "prompt":"Number of posts",     "type":"int","default":5},
        ]},
    "like_hashtag":           {"label": "Like posts from a hashtag",
        "fields": [
            {"key":"hashtag","prompt":"Hashtag  [no #]",     "type":"str"},
            {"key":"count",  "prompt":"Number of posts",     "type":"int","default":10},
        ]},
    "comment_user_posts":     {"label": "Comment on a user's posts",
        "fields": [
            {"key":"target",   "prompt":"Target username",   "type":"str"},
            {"key":"comments", "prompt":"Comments  [pipe |]","type":"list"},
            {"key":"count",    "prompt":"Number of posts",   "type":"int","default":3},
        ]},
    "comment_hashtag":        {"label": "Comment on hashtag posts",
        "fields": [
            {"key":"hashtag",  "prompt":"Hashtag  [no #]",   "type":"str"},
            {"key":"comments", "prompt":"Comments  [pipe |]","type":"list"},
            {"key":"count",    "prompt":"Number of posts",   "type":"int","default":5},
        ]},
    "follow_users":           {"label": "Follow a list of users",
        "fields": [
            {"key":"usernames","prompt":"Usernames  [comma]","type":"list_comma"},
        ]},
    "follow_followers_of":    {"label": "Follow followers of a target",
        "fields": [
            {"key":"target","prompt":"Target username",      "type":"str"},
            {"key":"count", "prompt":"How many followers",   "type":"int","default":20},
        ]},
    "unfollow_users":         {"label": "Unfollow a list of users",
        "fields": [
            {"key":"usernames","prompt":"Usernames  [comma]","type":"list_comma"},
        ]},
    "unfollow_non_followers": {"label": "Unfollow non-followers",
        "fields": [
            {"key":"limit","prompt":"Max to unfollow",       "type":"int","default":50},
        ]},
    "watch_stories":          {"label": "Watch stories from a user",
        "fields": [
            {"key":"target","prompt":"Target username",      "type":"str"},
        ]},
    "watch_feed_stories":     {"label": "Watch your feed stories",
        "fields": [
            {"key":"count","prompt":"How many accounts",     "type":"int","default":20},
        ]},
    "send_dms":               {"label": "Send DMs to a list of users",
        "fields": [
            {"key":"usernames","prompt":"Usernames  [comma]","type":"list_comma"},
            {"key":"messages", "prompt":"Messages  [pipe |]","type":"list"},
        ]},
    "auto_reply_dms":         {"label": "Auto-reply to unread DMs",
        "fields": [
            {"key":"reply_map",   "prompt":"Reply map JSON","type":"json",
             "default":'{"_default":"Thanks for reaching out!"}'},
            {"key":"max_threads", "prompt":"Max threads",   "type":"int","default":20},
        ]},
    "engage_hashtag":         {"label": "Full hashtag engagement  [like + comment + follow]",
        "fields": [
            {"key":"hashtag", "prompt":"Hashtag  [no #]",   "type":"str"},
            {"key":"count",   "prompt":"Number of posts",   "type":"int","default":10},
            {"key":"like",    "prompt":"Like posts?",       "type":"bool","default":True},
            {"key":"comment", "prompt":"Comment?",          "type":"bool","default":False},
            {"key":"follow",  "prompt":"Follow posters?",   "type":"bool","default":False},
            {"key":"comments","prompt":"Comments  [pipe |]","type":"list_optional"},
        ]},
    "scroll_feed":            {"label": "Scroll home feed  [human behaviour]",
        "fields": [
            {"key":"posts",  "prompt":"Posts to scroll",    "type":"int","default":10},
            {"key":"engage", "prompt":"Allow likes?",       "type":"bool","default":True},
        ]},
    "browse_explore":         {"label": "Browse Explore page  [human behaviour]",
        "fields": [
            {"key":"posts",  "prompt":"Posts to browse",    "type":"int","default":15},
            {"key":"engage", "prompt":"Allow likes?",       "type":"bool","default":True},
        ]},
    "browse_reels":           {"label": "Watch Reels  [human behaviour]",
        "fields": [
            {"key":"count",  "prompt":"Reels to watch",     "type":"int","default":10},
            {"key":"engage", "prompt":"Allow likes?",       "type":"bool","default":True},
        ]},
    "run_human_session":      {"label": "Full human session  [warmup + all browsing]",
        "fields": [
            {"key":"engage","prompt":"Allow engagement?",   "type":"bool","default":True},
        ]},
}


# ─────────────────────────────────────────────────────────────────────────────
# STORAGE
# ─────────────────────────────────────────────────────────────────────────────

def load_presets() -> dict:
    if PRESETS_FILE.exists():
        try: return json.loads(PRESETS_FILE.read_text())
        except: return {}
    return {}

def save_presets(presets: dict):
    PRESETS_FILE.parent.mkdir(exist_ok=True)
    PRESETS_FILE.write_text(json.dumps(presets, indent=2))

def load_history() -> list:
    if HISTORY_FILE.exists():
        try: return json.loads(HISTORY_FILE.read_text())
        except: return []
    return []

def append_history(entry: dict):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    history = load_history()
    history.insert(0, entry)
    HISTORY_FILE.write_text(json.dumps(history[:100], indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# FIELD INPUT
# ─────────────────────────────────────────────────────────────────────────────

def prompt_field(field: dict):
    key     = field["key"]
    prompt  = field["prompt"]
    ftype   = field["type"]
    default = field.get("default")

    if ftype == "str":
        return Prompt.ask(f"  {prompt}")
    elif ftype == "int":
        return int(Prompt.ask(f"  {prompt}", default=str(default) if default is not None else ""))
    elif ftype == "bool":
        return Confirm.ask(f"  {prompt}", default=bool(default))
    elif ftype == "list":
        return [x.strip() for x in Prompt.ask(f"  {prompt}").split("|") if x.strip()]
    elif ftype == "list_comma":
        return [x.strip() for x in Prompt.ask(f"  {prompt}").split(",") if x.strip()]
    elif ftype == "list_optional":
        raw = Prompt.ask(f"  {prompt}  [leave blank to skip]", default="")
        return [x.strip() for x in raw.split("|") if x.strip()] if raw.strip() else []
    elif ftype == "json":
        raw = Prompt.ask(f"  {prompt}", default=default or "{}")
        try: return json.loads(raw)
        except: return json.loads(default or "{}")
    return Prompt.ask(f"  {prompt}")


# ─────────────────────────────────────────────────────────────────────────────
# TASK BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_task_interactively() -> dict | None:
    hdr("BUILD TASK  —  SELECT ACTION")
    keys = list(TASK_DEFINITIONS.keys())
    for i, key in enumerate(keys, 1):
        label = TASK_DEFINITIONS[key]["label"]
        console.print(f"  [{i:>2}]  {label}")
    console.print(f"  [ 0]  Cancel")
    rule()
    choice = Prompt.ask("  Action number", default="0")
    if choice == "0": return None
    try:
        idx = int(choice) - 1
        if not (0 <= idx < len(keys)):
            warn("Invalid selection"); return None
    except ValueError:
        warn("Invalid input"); return None

    action = keys[idx]
    defn   = TASK_DEFINITIONS[action]
    info(f"Configuring:  {defn['label']}")
    rule()

    task = {"action": action}
    for field in defn["fields"]:
        try:
            task[field["key"]] = prompt_field(field)
        except (KeyboardInterrupt, EOFError):
            warn("Cancelled"); return None
    return task


def preview_task(task: dict):
    syntax = Syntax(json.dumps(task, indent=2), "json", theme="monokai")
    console.print(Panel(syntax, title="  TASK PREVIEW", border_style="cyan",
                        title_align="left"))


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTOR
# ─────────────────────────────────────────────────────────────────────────────

def execute_task(task: dict, manager, bots: list, concurrent: bool = True) -> float:
    action = task.get("action")

    def run(bot):
        try:
            if   action == "like_user_posts":        bot.like_user_posts(task["target"], task.get("count",5))
            elif action == "like_hashtag":            bot.like_hashtag_posts(task["hashtag"], task.get("count",10))
            elif action == "comment_user_posts":      bot.comment_on_user_posts(task["target"],task["comments"],task.get("count",3))
            elif action == "comment_hashtag":         bot.comment_on_hashtag_posts(task["hashtag"],task["comments"],task.get("count",5))
            elif action == "follow_users":            bot.follow_users(task["usernames"])
            elif action == "follow_followers_of":     bot.follow_user_followers(task["target"],task.get("count",20))
            elif action == "unfollow_users":          bot.unfollow_users(task["usernames"])
            elif action == "unfollow_non_followers":  bot.unfollow_non_followers(task.get("limit",50))
            elif action == "watch_stories":           bot.watch_user_stories(task["target"])
            elif action == "watch_feed_stories":      bot.watch_following_stories(task.get("count",20))
            elif action == "send_dms":                bot.send_dm_to_list(task["usernames"],task["messages"])
            elif action == "auto_reply_dms":          bot.auto_reply_dms(task.get("reply_map",{"_default":"Thanks!"}),task.get("max_threads",20))
            elif action == "engage_hashtag":          bot.engage_hashtag(task["hashtag"],task)
            elif action == "scroll_feed":             bot.scroll_feed(task.get("posts",10),task.get("engage",True))
            elif action == "browse_explore":          bot.browse_explore(task.get("posts",15),task.get("engage",True))
            elif action == "browse_reels":            bot.browse_reels(task.get("count",10),task.get("engage",True))
            elif action == "run_human_session":       bot.run_human_session(task.get("engage",True))
            else: bot.log.warning(f"Unknown action: {action}")
        except Exception as e:
            bot.log.error(f"Task '{action}' error: {e}")

    start = time.time()
    if concurrent and len(bots) > 1:
        threads = [threading.Thread(target=run, args=(b,), daemon=True) for b in bots]
        for t in threads: t.start()
        for t in threads: t.join()
    else:
        for b in bots: run(b)
    return round(time.time() - start, 1)


# ─────────────────────────────────────────────────────────────────────────────
# TABLES
# ─────────────────────────────────────────────────────────────────────────────

def show_presets_table(presets: dict):
    if not presets:
        info("No saved presets yet"); return
    t = Table(title="  SAVED PRESETS", show_header=True,
              header_style="bold cyan", box=box.SIMPLE_HEAD)
    t.add_column("#",          style="dim", width=4)
    t.add_column("Name",       style="bold white", min_width=20)
    t.add_column("Action",     min_width=24)
    t.add_column("Key Fields", style="dim")
    for i, (name, task) in enumerate(presets.items(), 1):
        summary_keys = ["target","hashtag","count","limit","usernames"]
        summary = "  ".join(
            f"{k}={json.dumps(task[k])[:25]}"
            for k in summary_keys if k in task
        )
        t.add_row(str(i), name, task.get("action","?"), summary or "—")
    console.print(t)


def show_history_table():
    history = load_history()
    if not history:
        info("No task history yet"); return
    t = Table(title="  TASK HISTORY  [last 20]", show_header=True,
              header_style="bold cyan", box=box.SIMPLE_HEAD)
    t.add_column("Time",     style="dim",         min_width=17)
    t.add_column("Action",   min_width=24)
    t.add_column("Accounts", justify="center")
    t.add_column("Duration", justify="right")
    t.add_column("Status",   justify="center")
    for entry in history[:20]:
        status = "[bright_green]OK[/bright_green]" if entry.get("ok") else "[bright_red]ERR[/bright_red]"
        t.add_row(
            entry.get("time","?"),
            entry.get("action","?"),
            entry.get("accounts","?"),
            f"{entry.get('elapsed','?')}s",
            status,
        )
    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT PICKER
# ─────────────────────────────────────────────────────────────────────────────

def _pick_bots(manager) -> tuple:
    active = [b for b in manager.bots if b.logged_in]
    if not active:
        warn("No logged-in accounts"); return [], False

    console.print("\n  [dim]Active accounts:[/dim]")
    for i, b in enumerate(active, 1):
        console.print(f"  [{i}]  @{b.username}  [{b.session.profile}]")
    console.print("  [A]  All accounts")
    rule()
    choice = Prompt.ask("  Run on", default="A").strip().upper()
    if choice == "A":
        selected = active
    else:
        try:
            selected = [active[int(choice)-1]]
        except (ValueError, IndexError):
            warn("Invalid — using all"); selected = active

    concurrent = len(selected) > 1 and Confirm.ask("  Run concurrently?", default=True)
    return selected, concurrent


def _run_and_record(task, bots, concurrent, manager, preset_name=None):
    preview_task(task)
    accounts = ", ".join(b.username for b in bots)
    info(f"Target accounts:  {accounts}")
    if not Confirm.ask("  Execute now?", default=True):
        warn("Cancelled"); return

    ok_flag = True
    with console.status("[bold cyan]  Running task...[/bold cyan]"):
        try:
            elapsed = execute_task(task, manager, bots, concurrent)
        except Exception as e:
            warn(f"Task failed: {e}"); ok_flag = False; elapsed = 0

    if ok_flag:
        ok(f"Done in {elapsed}s")

    append_history({
        "time":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action":   task.get("action"),
        "accounts": accounts,
        "elapsed":  elapsed,
        "ok":       ok_flag,
        "preset":   preset_name,
        "task":     task,
    })


# ─────────────────────────────────────────────────────────────────────────────
# MAIN MANUAL TRIGGER MENU
# ─────────────────────────────────────────────────────────────────────────────

def menu_manual_trigger(manager, cfg: dict):
    while True:
        hdr("MANUAL TASK TRIGGER")
        opts = [
            ("1", "Build and run a new task"),
            ("2", "Run a saved preset"),
            ("3", "Manage presets          save  delete  rename  export"),
            ("4", "Task history            last 100 runs with status"),
            ("5", "Quick-fire              paste raw JSON task and execute"),
            ("0", "Back"),
        ]
        for k, v in opts: console.print(f"  [{k}]  {v}")
        rule()
        choice = Prompt.ask("  Select", choices=[o[0] for o in opts])

        if   choice == "0": break
        elif choice == "1": _run_new_task(manager, cfg)
        elif choice == "2": _run_preset(manager, cfg)
        elif choice == "3": _manage_presets()
        elif choice == "4": show_history_table()
        elif choice == "5": _quick_fire(manager, cfg)


def _run_new_task(manager, cfg):
    task = build_task_interactively()
    if not task: return
    bots, concurrent = _pick_bots(manager)
    if not bots: return
    _run_and_record(task, bots, concurrent, manager)
    if Confirm.ask("\n  Save as preset?", default=False):
        name = Prompt.ask("  Preset name")
        p = load_presets()
        p[name] = task
        save_presets(p)
        ok(f"Preset saved  '{name}'")


def _run_preset(manager, cfg):
    presets = load_presets()
    if not presets:
        warn("No saved presets — build one first via option 1"); return
    show_presets_table(presets)
    names = list(presets.keys())
    console.print()
    for i, n in enumerate(names, 1): console.print(f"  [{i}]  {n}")
    rule()
    choice = Prompt.ask("  Choose name or number").strip()
    try:
        name = names[int(choice)-1]
    except (ValueError, IndexError):
        name = choice
    if name not in presets:
        warn(f"Preset '{name}' not found"); return

    task = presets[name].copy()
    info(f"Loaded preset:  {name}")

    if Confirm.ask("  Edit any fields before running?", default=False):
        defn = TASK_DEFINITIONS.get(task.get("action"), {})
        for field in defn.get("fields", []):
            cur = task.get(field["key"])
            info(f"{field['key']} = {json.dumps(cur)[:60]}")
            if Confirm.ask(f"  Change '{field['key']}'?", default=False):
                task[field["key"]] = prompt_field(field)

    bots, concurrent = _pick_bots(manager)
    if not bots: return
    _run_and_record(task, bots, concurrent, manager, preset_name=name)


def _manage_presets():
    while True:
        presets = load_presets()
        show_presets_table(presets)
        console.print("\n  [1]  Delete a preset")
        console.print("  [2]  Rename a preset")
        console.print("  [3]  Export presets to JSON file")
        console.print("  [4]  Import presets from JSON file")
        console.print("  [0]  Back")
        rule()
        choice = Prompt.ask("  Select", choices=["0","1","2","3","4"])
        if choice == "0": break

        elif choice == "1":
            if not presets: info("No presets to delete"); continue
            name = Prompt.ask("  Preset name to delete")
            if name in presets:
                if Confirm.ask(f"  Delete '{name}'?", default=False):
                    del presets[name]; save_presets(presets)
                    ok(f"Deleted  '{name}'")
            else: warn(f"'{name}' not found")

        elif choice == "2":
            if not presets: continue
            old = Prompt.ask("  Current name")
            if old not in presets: warn("Not found"); continue
            new = Prompt.ask("  New name")
            presets[new] = presets.pop(old)
            save_presets(presets)
            ok(f"Renamed  '{old}'  to  '{new}'")

        elif choice == "3":
            path = Prompt.ask("  Export path", default="config/presets_export.json")
            Path(path).write_text(json.dumps(presets, indent=2))
            ok(f"Exported {len(presets)} preset(s) to  {path}")

        elif choice == "4":
            path = Prompt.ask("  Import path", default="config/presets_export.json")
            try:
                imported = json.loads(Path(path).read_text())
                presets.update(imported); save_presets(presets)
                ok(f"Imported {len(imported)} preset(s)")
            except Exception as e:
                warn(f"Import failed: {e}")


def _quick_fire(manager, cfg):
    hdr("QUICK-FIRE")
    console.print('[dim]  Paste a raw JSON task and fire immediately.[/dim]')
    console.print('[dim]  Example:  {"action": "like_hashtag", "hashtag": "cats", "count": 5}[/dim]')
    rule()
    raw = Prompt.ask("  Task JSON")
    try:
        task = json.loads(raw)
    except json.JSONDecodeError as e:
        warn(f"Invalid JSON: {e}"); return
    if "action" not in task:
        warn("Task must have an 'action' field"); return
    bots, concurrent = _pick_bots(manager)
    if not bots: return
    _run_and_record(task, bots, concurrent, manager)