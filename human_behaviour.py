"""
Human Behaviour Simulator
Realistic timing, fatigue modelling, activity windows.
All output is clean, classy, no emojis.
Max wait cap: 150s (2.5 min).
"""

import time
import random
import logging
from datetime import datetime
from dataclasses import dataclass, field
from rich.console import Console
from rich.text import Text

console = Console()

MAX_WAIT = 150  # hard cap on any single delay in seconds

# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

LEVEL_STYLES = {
    "info":    ("dim white",      " ·  "),
    "action":  ("cyan",           " >>  "),
    "wait":    ("yellow",         " ~   "),
    "api":     ("bright_blue",    " API "),
    "skip":    ("dim",            " -   "),
    "warn":    ("bright_red",     " !   "),
    "success": ("bright_green",   " OK  "),
    "break":   ("magenta",        " ZZZ "),
    "header":  ("bold white",     " === "),
}

def lp(username: str, msg: str, level: str = "info"):
    """Live print — clean, aligned, classy."""
    ts    = datetime.now().strftime("%H:%M:%S")
    style, tag = LEVEL_STYLES.get(level, ("white", "  ·  "))
    user_col = f"[bold white]{username:<20}[/bold white]"
    tag_col  = f"[{style}]{tag}[/{style}]"
    msg_col  = f"[{style}]{msg}[/{style}]"
    console.print(f"[dim]{ts}[/dim]  {user_col}  {tag_col}  {msg_col}")


def lw(username: str, reason: str, seconds: float):
    """Capped, visible wait with reason."""
    seconds = min(seconds, MAX_WAIT)
    if seconds < 0.4:
        time.sleep(seconds)
        return
    lp(username, f"{reason}  [{seconds:.1f}s]", "wait")
    time.sleep(seconds)


# ─────────────────────────────────────────────────────────────────────────────
# TIMING PROFILES  (all delays now capped by MAX_WAIT)
# ─────────────────────────────────────────────────────────────────────────────

TIMING_PROFILES = {
    "casual": {
        "scroll_post_view": (3.0,  9.0),
        "between_posts":    (1.2,  3.5),
        "before_like":      (0.8,  2.5),
        "before_comment":   (5.0, 14.0),
        "typing_cpm":       (180,  280),
        "profile_browse":   (4.0, 14.0),
        "story_tap_delay":  (1.5,  5.0),
        "session_length":   (8,    20),
        "break_between":    (10,   40),
    },
    "active": {
        "scroll_post_view": (1.5,  5.0),
        "between_posts":    (0.6,  2.0),
        "before_like":      (0.4,  1.5),
        "before_comment":   (3.0, 10.0),
        "typing_cpm":       (250,  380),
        "profile_browse":   (2.5,  9.0),
        "story_tap_delay":  (1.0,  3.0),
        "session_length":   (5,    15),
        "break_between":    (5,    20),
    },
    "power": {
        "scroll_post_view": (0.8,  2.5),
        "between_posts":    (0.3,  1.0),
        "before_like":      (0.2,  0.8),
        "before_comment":   (2.0,  6.0),
        "typing_cpm":       (320,  480),
        "profile_browse":   (1.5,  5.0),
        "story_tap_delay":  (0.6,  1.8),
        "session_length":   (3,    10),
        "break_between":    (3,    12),
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY WINDOWS
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_ACTIVITY_WINDOWS = [
    {"start": "07:00", "end": "09:30"},
    {"start": "12:00", "end": "13:30"},
    {"start": "17:30", "end": "20:00"},
    {"start": "21:00", "end": "23:00"},
]

def is_within_activity_window(windows=None):
    windows = windows or DEFAULT_ACTIVITY_WINDOWS
    now     = datetime.now()
    cur     = now.hour * 60 + now.minute
    for w in windows:
        sh, sm = map(int, w["start"].split(":"))
        eh, em = map(int, w["end"].split(":"))
        if (sh*60+sm) <= cur <= (eh*60+em):
            return True
    return False

def minutes_until_next_window(windows=None):
    windows  = windows or DEFAULT_ACTIVITY_WINDOWS
    now      = datetime.now()
    cur      = now.hour * 60 + now.minute
    min_wait = 24 * 60
    for w in windows:
        sh, sm = map(int, w["start"].split(":"))
        start  = sh*60+sm
        wait   = (start - cur) % (24*60)
        if wait > 0:
            min_wait = min(min_wait, wait)
    return min_wait

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionState:
    username: str
    profile:  str   = "active"
    actions_today: dict = field(default_factory=lambda: {
        "likes": 0, "comments": 0, "follows": 0,
        "unfollows": 0, "dms": 0, "story_views": 0,
    })
    session_start:    float = field(default_factory=time.time)
    last_action_time: float = field(default_factory=time.time)
    fatigue_level:    float = 0.0

    daily_limits: dict = field(default_factory=lambda: {
        "likes": 120, "comments": 30, "follows": 60,
        "unfollows": 60, "dms": 40, "story_views": 300,
    })

    def record_action(self, action_type: str, count: int = 1):
        if action_type in self.actions_today:
            self.actions_today[action_type] += count
        self.last_action_time = time.time()
        weights = {"likes":0.003,"comments":0.015,"follows":0.010,
                   "unfollows":0.010,"dms":0.020,"story_views":0.001}
        self.fatigue_level = min(1.0, self.fatigue_level + weights.get(action_type, 0.005))

    def can_do(self, action_type: str) -> bool:
        return self.actions_today.get(action_type, 0) < self.daily_limits.get(action_type, 999)

    def remaining(self, action_type: str) -> int:
        return max(0, self.daily_limits.get(action_type, 0) - self.actions_today.get(action_type, 0))

    def fatigue_multiplier(self) -> float:
        return 1.0 + (self.fatigue_level * 1.5)   # softer than before

    def reset_daily(self):
        for k in self.actions_today:
            self.actions_today[k] = 0
        self.fatigue_level  = 0.0
        self.session_start  = time.time()

    def summary(self) -> str:
        parts = [f"{k}:{v}/{self.daily_limits.get(k,'?')}" for k,v in self.actions_today.items()]
        return f"[{self.username}]  " + "  ".join(parts) + f"  fatigue:{self.fatigue_level:.0%}"


# ─────────────────────────────────────────────────────────────────────────────
# HUMAN BEHAVIOUR
# ─────────────────────────────────────────────────────────────────────────────

class HumanBehaviour:

    def __init__(self, session: SessionState):
        self.session = session
        self.profile = TIMING_PROFILES.get(session.profile, TIMING_PROFILES["active"])
        self.u       = session.username

    def _t(self, key: str) -> float:
        lo, hi = self.profile[key]
        raw    = random.uniform(lo, hi) * self.session.fatigue_multiplier()
        return min(raw, MAX_WAIT)

    # ── micro-delays ─────────────────────────────────────────────────────────

    def pause_before_like(self):
        lw(self.u, "Hesitating before like", self._t("before_like"))

    def pause_viewing_post(self):
        lw(self.u, "Viewing post", self._t("scroll_post_view"))

    def pause_between_posts(self):
        d = self._t("between_posts")
        if random.random() < 0.06:
            extra = random.uniform(4, 18)
            lp(self.u, f"Distraction pause  +{extra:.0f}s", "break")
            d = min(d + extra, MAX_WAIT)
        lw(self.u, "Scrolling to next post", d)

    def pause_before_comment(self):
        lw(self.u, "Reading post before commenting", self._t("before_comment"))

    def simulate_typing(self, text: str):
        cpm_lo, cpm_hi = self.profile["typing_cpm"]
        cpm        = random.uniform(cpm_lo, cpm_hi) * self.session.fatigue_multiplier()
        base       = (len(text) / cpm) * 60
        typos      = max(0, int(len(text)/20) + random.randint(-1,2))
        typo_d     = typos * random.uniform(0.4, 1.5)
        think_d    = random.uniform(0.4, 2.0) if random.random() < 0.3 else 0
        total      = min(base + typo_d + think_d, MAX_WAIT)
        preview    = text[:45] + ("..." if len(text)>45 else "")
        lw(self.u, f"Typing  \"{preview}\"", total)

    def pause_on_profile(self):
        d = self._t("profile_browse")
        if random.random() < 0.4:
            d = min(d + random.uniform(2, 8), MAX_WAIT)
        lw(self.u, "Browsing profile", d)

    def pause_between_story_taps(self):
        lw(self.u, "Watching story frame", self._t("story_tap_delay"))

    def pause_reading_dm(self):
        d = min(random.uniform(2.5, 8.0) * self.session.fatigue_multiplier(), MAX_WAIT)
        lw(self.u, "Reading DM before replying", d)

    # ── session behaviour ────────────────────────────────────────────────────

    def maybe_take_break(self) -> bool:
        chance = 0.04 + (self.session.fatigue_level * 0.10)
        if random.random() < chance:
            mins = random.uniform(1, 5)      # capped break: 1–5 min
            lp(self.u, f"Short break  {mins:.1f} min  (fatigue {self.session.fatigue_level:.0%})", "break")
            time.sleep(mins * 60)
            self.session.fatigue_level = max(0.0, self.session.fatigue_level - 0.08)
            lp(self.u, "Break over — resuming", "info")
            return True
        return False

    def wait_for_activity_window(self, windows=None):
        if not is_within_activity_window(windows):
            wait   = minutes_until_next_window(windows)
            jitter = random.uniform(-3, 8)
            wait   = max(1, wait + jitter)
            lp(self.u, f"Outside activity window — sleeping {wait:.0f} min", "break")
            time.sleep(wait * 60)
            lp(self.u, "Activity window opened", "success")

    def session_warmup(self, cl):
        lp(self.u, "─── SESSION WARMUP ─────────────────────────", "header")
        lw(self.u, "App open delay", random.uniform(1.0, 3.0))
        lp(self.u, "Fetching timeline feed", "api")
        try:
            cl.get_timeline_feed()
            lp(self.u, "Timeline loaded", "success")
            lw(self.u, "Checking notifications", random.uniform(1.5, 4.0))
        except Exception as e:
            lp(self.u, f"Timeline fetch failed: {e}", "warn")

        n = random.randint(3, 7)
        lp(self.u, f"Warmup scroll  {n} posts  [no engagement]", "info")
        self.scroll_feed(cl, posts=n, engage=False)

        if random.random() < 0.6:
            lp(self.u, "Checking stories before main session", "info")
            self.browse_stories_passively(cl, count=random.randint(2,5))

        lp(self.u, "─── WARMUP COMPLETE ────────────────────────", "success")

    def session_cooldown(self):
        lp(self.u, "Winding down session", "info")
        lw(self.u, "Cooldown", random.uniform(2.0, 6.0))

    # ── scrolling ────────────────────────────────────────────────────────────

    def scroll_feed(self, cl, posts: int = 10, engage: bool = True) -> dict:
        actions = {"viewed": 0, "liked": 0, "profile_visits": 0}
        lp(self.u, "Requesting home feed from API", "api")
        try:
            feed  = cl.get_timeline_feed()
            items = feed.get("feed_items", [])[:posts]
            total = len(items)
            lp(self.u, f"Feed loaded  {total} posts", "success")

            for i, item in enumerate(items, 1):
                media    = item.get("media_or_ad", {})
                pk       = media.get("pk")
                uname    = media.get("user", {}).get("username", "unknown")
                mtype    = {1:"Photo",2:"Video",8:"Album"}.get(media.get("media_type"),"Post")
                lp(self.u, f"[{i}/{total}]  {mtype}  by  @{uname}", "info")
                self.pause_viewing_post()
                actions["viewed"] += 1

                if engage and pk and self.session.can_do("likes"):
                    if random.random() < 0.40:
                        lp(self.u, f"  Decided to like  @{uname}", "action")
                        self.pause_before_like()
                        try:
                            cl.media_like(pk)
                            self.session.record_action("likes")
                            actions["liked"] += 1
                            lp(self.u, f"  Liked  @{uname}  (today: {self.session.actions_today['likes']})", "success")
                        except Exception as e:
                            lp(self.u, f"  Like failed: {e}", "warn")
                    else:
                        lp(self.u, f"  Scrolled past  @{uname}", "skip")
                elif not engage:
                    lp(self.u, f"  Warmup — no engagement", "skip")

                if random.random() < 0.10:
                    upk = media.get("user", {}).get("pk")
                    if upk:
                        lp(self.u, f"  Tapped into  @{uname} profile", "action")
                        try:
                            cl.user_info(upk)
                            self.pause_on_profile()
                            actions["profile_visits"] += 1
                        except Exception as e:
                            lp(self.u, f"  Profile visit failed: {e}", "warn")

                self.pause_between_posts()
                self.maybe_take_break()

        except Exception as e:
            lp(self.u, f"scroll_feed error: {e}", "warn")

        lp(self.u, f"Feed scroll done  viewed:{actions['viewed']}  liked:{actions['liked']}  profiles:{actions['profile_visits']}", "success")
        return actions

    def browse_explore(self, cl, posts: int = 15, engage: bool = True) -> dict:
        actions = {"viewed": 0, "liked": 0, "profile_visits": 0}
        lp(self.u, "Requesting Explore page from API", "api")
        try:
            explore = cl.explore(max_id=None)
            items   = (explore.get("items") or [])[:posts]
            total   = len(items)
            lp(self.u, f"Explore loaded  {total} posts", "success")

            for i, item in enumerate(items, 1):
                pk    = item.get("pk") or item.get("id")
                uname = item.get("user", {}).get("username", "unknown")
                mtype = {1:"Photo",2:"Video",8:"Album"}.get(item.get("media_type"),"Post")
                lp(self.u, f"[{i}/{total}]  Explore  {mtype}  @{uname}", "info")
                self.pause_viewing_post()
                actions["viewed"] += 1

                if engage and pk and self.session.can_do("likes"):
                    if random.random() < 0.28:
                        lp(self.u, f"  Liking  @{uname} explore post", "action")
                        self.pause_before_like()
                        try:
                            cl.media_like(pk)
                            self.session.record_action("likes")
                            actions["liked"] += 1
                            lp(self.u, f"  Liked  (today: {self.session.actions_today['likes']})", "success")
                        except Exception as e:
                            lp(self.u, f"  Like failed: {e}", "warn")
                    else:
                        lp(self.u, f"  Scrolled past", "skip")

                if random.random() < 0.08:
                    upk = item.get("user", {}).get("pk")
                    if upk:
                        lp(self.u, f"  Visiting  @{uname} profile", "action")
                        try:
                            cl.user_info(upk)
                            self.pause_on_profile()
                            actions["profile_visits"] += 1
                        except Exception as e:
                            lp(self.u, f"  Profile visit failed: {e}", "warn")

                self.pause_between_posts()

        except Exception as e:
            lp(self.u, f"browse_explore error: {e}", "warn")

        lp(self.u, f"Explore done  viewed:{actions['viewed']}  liked:{actions['liked']}", "success")
        return actions

    def browse_reels(self, cl, count: int = 10, engage: bool = True) -> dict:
        actions = {"watched": 0, "liked": 0}
        lp(self.u, "Requesting Reels feed from API", "api")
        try:
            reels = cl.explore_clips(amount=count)
            total = len(reels)
            lp(self.u, f"Reels loaded  {total}", "success")

            for i, reel in enumerate(reels, 1):
                uname = getattr(getattr(reel,"user",None),"username","unknown")
                watch = random.uniform(3.0, 25.0)
                lp(self.u, f"[{i}/{total}]  Reel  @{uname}  watch:{watch:.0f}s", "info")
                time.sleep(watch)
                actions["watched"] += 1

                if engage and self.session.can_do("likes"):
                    if random.random() < 0.35:
                        lp(self.u, f"  Liking reel  @{uname}", "action")
                        self.pause_before_like()
                        try:
                            cl.media_like(reel.pk)
                            self.session.record_action("likes")
                            actions["liked"] += 1
                            lp(self.u, f"  Liked  (today: {self.session.actions_today['likes']})", "success")
                        except Exception as e:
                            lp(self.u, f"  Like failed: {e}", "warn")
                    else:
                        lp(self.u, f"  Swiped past reel", "skip")

                self.pause_between_posts()

        except Exception as e:
            lp(self.u, f"browse_reels error: {e}", "warn")

        lp(self.u, f"Reels done  watched:{actions['watched']}  liked:{actions['liked']}", "success")
        return actions

    def browse_stories_passively(self, cl, count: int = 5) -> int:
        watched = 0
        lp(self.u, "Requesting stories tray from API", "api")
        try:
            reels = cl.reels_tray()
            total = min(count, len(reels))
            lp(self.u, f"Stories tray loaded  {len(reels)} accounts  watching:{total}", "success")
            story_ids = []
            for i, reel in enumerate(reels[:count], 1):
                uname = getattr(getattr(reel,"user",None),"username",f"user_{i}")
                items = reel.items or []
                lp(self.u, f"[{i}/{total}]  Stories  @{uname}  frames:{len(items)}", "info")
                for item in items:
                    story_ids.append(item.pk)
                    self.pause_between_story_taps()
            if story_ids:
                lp(self.u, f"Marking {len(story_ids)} frames seen via API", "api")
                cl.story_seen(story_ids)
                watched = len(story_ids)
                self.session.record_action("story_views", watched)
                lp(self.u, f"Stories watched:{watched}  (today: {self.session.actions_today['story_views']})", "success")
        except Exception as e:
            lp(self.u, f"browse_stories_passively error: {e}", "warn")
        return watched

    def visit_profile_and_scroll(self, cl, user_id: int) -> dict:
        actions = {"post_views": 0, "liked": 0}
        lp(self.u, f"Fetching profile  user_id:{user_id}", "api")
        try:
            info  = cl.user_info(user_id)
            uname = getattr(info, "username", str(user_id))
            lp(self.u, f"Profile  @{uname}  followers:{info.follower_count}", "action")
            self.pause_on_profile()

            n     = random.randint(3, 8)
            posts = cl.user_medias(user_id, n)
            lp(self.u, f"Scrolling  @{uname}  last {len(posts)} posts", "info")

            for j, post in enumerate(posts, 1):
                lp(self.u, f"  [{j}/{len(posts)}]  @{uname} post", "info")
                self.pause_viewing_post()
                actions["post_views"] += 1

                if self.session.can_do("likes") and random.random() < 0.28:
                    lp(self.u, f"  Liking  @{uname} post", "action")
                    self.pause_before_like()
                    try:
                        cl.media_like(post.pk)
                        self.session.record_action("likes")
                        actions["liked"] += 1
                        lp(self.u, f"  Liked  (today: {self.session.actions_today['likes']})", "success")
                    except Exception as e:
                        lp(self.u, f"  Like failed: {e}", "warn")

                self.pause_between_posts()
                if random.random() < 0.15:
                    lp(self.u, f"  Left  @{uname} profile early", "skip")
                    break

        except Exception as e:
            lp(self.u, f"visit_profile_and_scroll error: {e}", "warn")
        return actions

    # ── full session ─────────────────────────────────────────────────────────

    def run_human_session(self, cl, windows=None, engage: bool = True):
        self.wait_for_activity_window(windows)
        self.session_warmup(cl)

        mins = random.uniform(*self.profile["session_length"])
        lp(self.u, f"Session planned  {mins:.0f} min", "info")
        end  = time.time() + mins * 60
        num  = 0

        while time.time() < end:
            if self.session.fatigue_level > 0.85:
                lp(self.u, f"Fatigue {self.session.fatigue_level:.0%} — ending session early", "break")
                break

            remaining = (end - time.time()) / 60
            lp(self.u, f"Time remaining  {remaining:.1f} min  fatigue:{self.session.fatigue_level:.0%}", "info")

            activity = random.choices(["feed","explore","reels","stories"], weights=[50,25,15,10])[0]
            num += 1
            lp(self.u, f"─── Activity #{num}: {activity.upper()} ───────────────────────", "header")

            if activity == "feed":
                self.scroll_feed(cl, posts=random.randint(5,12), engage=engage)
            elif activity == "explore":
                self.browse_explore(cl, posts=random.randint(6,15), engage=engage)
            elif activity == "reels":
                self.browse_reels(cl, count=random.randint(4,10), engage=engage)
            elif activity == "stories":
                self.browse_stories_passively(cl, count=random.randint(3,7))

            self.maybe_take_break()

        self.session_cooldown()
        lp(self.u, f"─── SESSION COMPLETE  {self.session.summary()}", "success")