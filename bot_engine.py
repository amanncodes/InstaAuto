"""
Instagram Bot Engine
- cl.relogin() for seamless session recovery
- cl.delay_range for native per-request jitter
- Device fingerprint: locale, timezone, country code
- Full exception handler: BadPassword, ReloginAttemptExceeded,
  FeedbackRequired, PleaseWaitFewMinutes, ChallengeRequired
- No emojis. Max wait capped at 150s.
- Persistent stats via stats_store (survives across sessions).
"""

import time
import random
import logging
from pathlib import Path
from datetime import datetime

from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired, ChallengeRequired, BadPassword,
    ReloginAttemptExceeded, FeedbackRequired,
    PleaseWaitFewMinutes, UserNotFound, RateLimitError,
)

from human_behaviour import HumanBehaviour, SessionState, lp, lw, MAX_WAIT
from stats_store import (
    record_action as _persist_action,
    record_snapshot as _persist_snapshot,
    get_daily_series as _get_daily_series,
)
from poster import Publisher

# ─────────────────────────────────────────────────────────────────────────────
# DEVICE PRESETS  — randomised per account so each looks like a different phone
# ─────────────────────────────────────────────────────────────────────────────

DEVICE_PRESETS = [
    {"manufacturer":"Samsung","model":"SM-G991B","android_release":"12","android_version":31,"dpi":"480dpi","resolution":"1080x2400"},
    {"manufacturer":"OnePlus","model":"EB2103",  "android_release":"11","android_version":30,"dpi":"420dpi","resolution":"1080x2400"},
    {"manufacturer":"Xiaomi", "model":"M2012K11G","android_release":"11","android_version":30,"dpi":"440dpi","resolution":"1080x2340"},
    {"manufacturer":"Google", "model":"Pixel 5", "android_release":"12","android_version":31,"dpi":"432dpi","resolution":"1080x2340"},
    {"manufacturer":"Samsung","model":"SM-A525F","android_release":"11","android_version":30,"dpi":"420dpi","resolution":"1080x2400"},
    {"manufacturer":"Oppo",   "model":"CPH2197", "android_release":"11","android_version":30,"dpi":"400dpi","resolution":"1080x2400"},
]

LOCALE_PRESETS = [
    {"locale":"en_US","country":"US","country_code":1, "tz_offset":-5*3600},
    {"locale":"en_GB","country":"GB","country_code":44,"tz_offset": 0},
    {"locale":"en_IN","country":"IN","country_code":91,"tz_offset": 5*3600+1800},
    {"locale":"en_AU","country":"AU","country_code":61,"tz_offset":10*3600},
    {"locale":"en_CA","country":"CA","country_code":1, "tz_offset":-5*3600},
]


def get_logger(username: str) -> logging.Logger:
    logger = logging.getLogger(username)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        Path("logs").mkdir(exist_ok=True)
        fh = logging.FileHandler(f"logs/{username}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s  [%(levelname)s]  %(message)s"))
        logger.addHandler(fh)
    return logger


# ─────────────────────────────────────────────────────────────────────────────
# BOT
# ─────────────────────────────────────────────────────────────────────────────

class InstagramBot:

    def __init__(self, account_cfg: dict):
        self.username  = account_cfg["username"]
        self.password  = account_cfg["password"]
        self.proxy     = account_cfg.get("proxy", "")
        self.cfg       = account_cfg
        self.log       = get_logger(self.username)
        self.logged_in = False

        profile = account_cfg.get("behaviour_profile", "active")
        self.session  = SessionState(username=self.username, profile=profile)
        self.human    = HumanBehaviour(self.session)
        self.activity_windows = account_cfg.get("activity_windows", None)

        # ── Seed today's counters from the persistent DB ──────────────────
        # Without this, the in-memory session always starts at 0 even if
        # the bot already did work earlier today in a previous run.
        self._seed_today_from_db()

        Path("sessions").mkdir(exist_ok=True)
        self.session_file = Path(f"sessions/{self.username}.json")

        self.cl = Client()

        # Native per-request delay — instagrapi adds this automatically to every call
        self.cl.delay_range = [1, 3]

        # Stable device fingerprint per account (seeded by username for consistency)
        rng    = random.Random(self.username)
        device = rng.choice(DEVICE_PRESETS)
        locale = rng.choice(LOCALE_PRESETS)
        self.cl.set_locale(locale["locale"])
        self.cl.set_country_code(locale["country_code"])
        self.cl.set_timezone_offset(locale["tz_offset"])
        self._device  = device
        self._locale  = locale

        if self.proxy:
            self.cl.set_proxy(self.proxy)

        # Publisher is lazy-initialised on first use after login
        self._publisher: Publisher | None = None

    @property
    def publisher(self) -> Publisher:
        if self._publisher is None:
            self._publisher = Publisher(self)
        return self._publisher

    def _lp(self, msg: str, level: str = "info"):
        lp(self.username, msg, level)

    # ── STARTUP: seed today’s counts from DB ───────────────────────────────────────────

    def _seed_today_from_db(self):
        """
        Load today’s action totals from SQLite into the in-memory session.
        Called once in __init__ so the dashboard and daily limits are correct
        even after the terminal was closed and reopened mid-day.
        """
        try:
            series = _get_daily_series(self.username, days=1)
            if series:
                today = series[0]
                for key in self.session.actions_today:
                    if key in today and today[key] > 0:
                        self.session.actions_today[key] = today[key]
        except Exception:
            pass  # DB may not exist yet on very first run

    # ── PERSIST HELPER ────────────────────────────────────────────────────────

    def _record(self, action_type: str, count: int = 1):
        """Record action in both the in-memory session AND the persistent store."""
        self.session.record_action(action_type, count)
        _persist_action(self.username, action_type, count)

    # ── AUTH & RELOGIN ────────────────────────────────────────────────────────

    def login(self) -> bool:
        self._lp("Login sequence starting", "api")
        self._lp(f"Device   {self._device['manufacturer']} {self._device['model']}  /  Locale {self._locale['locale']}", "info")

        try:
            if self.session_file.exists():
                self._lp(f"Loading saved session  {self.session_file}", "info")
                self.cl.load_settings(str(self.session_file))
                self._lp("Authenticating with saved session via API", "api")
                self.cl.login(self.username, self.password)
                # Verify session is actually valid
                self._lp("Verifying session with timeline feed request", "api")
                self.cl.get_timeline_feed()
                self._lp("Session verified", "success")
            else:
                self._lp("No saved session — fresh credential login", "info")
                self._lp("Sending credentials to Instagram API", "api")
                self.cl.login(self.username, self.password)
                self._lp(f"Saving session to  {self.session_file}", "info")
                self.cl.dump_settings(str(self.session_file))

            self.logged_in = True
            self._lp(f"Logged in as  @{self.username}", "success")
            return True

        except LoginRequired:
            self._lp("Session expired — attempting relogin via cl.relogin()", "warn")
            return self._do_relogin()

        except BadPassword:
            self._lp("Bad password — check credentials in config.yaml", "warn")
            return False

        except ChallengeRequired:
            self._lp("Challenge required — check your email or SMS inbox", "warn")
            return False

        except Exception as e:
            # Session may be stale — wipe it and retry once
            if self.session_file.exists():
                self._lp(f"Login error: {e}  — wiping stale session and retrying", "warn")
                self.session_file.unlink(missing_ok=True)
                try:
                    self.cl.login(self.username, self.password)
                    self.cl.dump_settings(str(self.session_file))
                    self.logged_in = True
                    self._lp(f"Logged in (fresh retry)  @{self.username}", "success")
                    return True
                except Exception as e2:
                    self._lp(f"Fresh retry also failed: {e2}", "warn")
                    return False
            self._lp(f"Login failed: {e}", "warn")
            return False

    def _do_relogin(self) -> bool:
        """Use instagrapi's built-in relogin() — reuses device/session data, less suspicious."""
        try:
            self._lp("Calling cl.relogin()  [native session refresh]", "api")
            self.cl.relogin()
            self.cl.dump_settings(str(self.session_file))
            self.logged_in = True
            self._lp(f"Relogin successful  @{self.username}", "success")
            return True
        except ReloginAttemptExceeded:
            self._lp("Relogin attempts exceeded — account may be restricted", "warn")
            return False
        except Exception as e:
            self._lp(f"Relogin failed: {e}", "warn")
            return False

    def _handle_exception(self, e: Exception, action: str) -> bool:
        """
        Centralised exception handler — mirrors instagrapi best-practices docs.
        Returns True if caller should retry, False if should abort.
        """
        if isinstance(e, PleaseWaitFewMinutes):
            wait = random.uniform(60, MAX_WAIT)
            self._lp(f"Instagram says wait a few minutes  — pausing {wait:.0f}s", "warn")
            time.sleep(wait)
            return True

        elif isinstance(e, FeedbackRequired):
            self._lp(f"FeedbackRequired on {action} — Instagram flagged this action, pausing 5 min", "warn")
            time.sleep(min(300, MAX_WAIT))
            return False

        elif isinstance(e, RateLimitError):
            wait = random.uniform(60, MAX_WAIT)
            self._lp(f"Rate limit on {action}  — pausing {wait:.0f}s", "warn")
            time.sleep(wait)
            return True

        elif isinstance(e, LoginRequired):
            self._lp(f"Session dropped during {action}  — attempting relogin", "warn")
            return self._do_relogin()

        elif isinstance(e, ChallengeRequired):
            self._lp(f"Challenge required during {action}  — check inbox", "warn")
            return False

        elif isinstance(e, BadPassword):
            self._lp("Bad password error  — stopping this account", "warn")
            self.logged_in = False
            return False

        else:
            self._lp(f"Unexpected error on {action}: {e}", "warn")
            return False

    def _guard(self, action_type: str = None) -> bool:
        if not self.logged_in:
            self._lp("Account not logged in — skipping", "warn")
            return False
        if action_type and not self.session.can_do(action_type):
            done  = self.session.actions_today.get(action_type, 0)
            limit = self.session.daily_limits.get(action_type, 0)
            self._lp(f"Daily limit reached  {action_type}  {done}/{limit}", "warn")
            return False
        return True

    # ── HUMAN SESSIONS ────────────────────────────────────────────────────────

    def run_human_session(self, engage=True):
        if not self._guard(): return
        self.human.run_human_session(self.cl, windows=self.activity_windows, engage=engage)

    def scroll_feed(self, posts=10, engage=True):
        if not self._guard(): return {}
        return self.human.scroll_feed(self.cl, posts=posts, engage=engage)

    def browse_explore(self, posts=15, engage=True):
        if not self._guard(): return {}
        return self.human.browse_explore(self.cl, posts=posts, engage=engage)

    def browse_reels(self, count=10, engage=True):
        if not self._guard(): return {}
        return self.human.browse_reels(self.cl, count=count, engage=engage)

    # ── LIKES ─────────────────────────────────────────────────────────────────

    def like_user_posts(self, target_username: str, count: int = 5) -> int:
        if not self._guard("likes"): return 0
        self._lp(f"─── LIKE USER  @{target_username}  up to {count} posts", "header")
        liked = 0
        try:
            self._lp(f"Resolving user ID  @{target_username}", "api")
            user_id = self.cl.user_id_from_username(target_username)
            self._lp(f"User ID resolved  {user_id}", "success")
            self.human.visit_profile_and_scroll(self.cl, user_id)
            self._lp(f"Fetching posts  @{target_username}  count:{count}", "api")
            medias = self.cl.user_medias(user_id, count)
            self._lp(f"Got {len(medias)} posts", "success")

            for i, media in enumerate(medias, 1):
                if not self.session.can_do("likes"): break
                self._lp(f"[{i}/{len(medias)}]  Post  {media.pk}", "info")
                self.human.pause_viewing_post()
                self.human.pause_before_like()
                try:
                    self._lp(f"  Sending like  {media.pk}", "api")
                    self.cl.media_like(media.pk)
                    self._record("likes")   # ← persists to disk
                    liked += 1
                    self._lp(f"  Liked  @{target_username}  {media.pk}  (today:{self.session.actions_today['likes']})", "success")
                    self.human.pause_between_posts()
                    self.human.maybe_take_break()
                except Exception as e:
                    if not self._handle_exception(e, "like"): break

        except UserNotFound:
            self._lp(f"User not found  @{target_username}", "warn")
        except Exception as e:
            self._handle_exception(e, "like_user_posts")

        self._lp(f"─── DONE  liked {liked}/{count}  @{target_username}", "success")
        return liked

    def like_hashtag_posts(self, hashtag: str, count: int = 10) -> int:
        if not self._guard("likes"): return 0
        self._lp(f"─── LIKE HASHTAG  #{hashtag}  up to {count}", "header")
        liked = 0
        try:
            self._lp(f"Fetching recent posts  #{hashtag}", "api")
            medias = self.cl.hashtag_medias_recent(hashtag, count)
            self._lp(f"Got {len(medias)} posts", "success")

            for i, media in enumerate(medias, 1):
                if not self.session.can_do("likes"): break
                uname = getattr(getattr(media,"user",None),"username","unknown")
                self._lp(f"[{i}/{len(medias)}]  #{hashtag}  @{uname}", "info")
                self.human.pause_viewing_post()
                self.human.pause_before_like()
                try:
                    self._lp(f"  Sending like", "api")
                    self.cl.media_like(media.pk)
                    self._record("likes")   # ← persists to disk
                    liked += 1
                    self._lp(f"  Liked  @{uname}  (today:{self.session.actions_today['likes']})", "success")
                    self.human.pause_between_posts()
                    self.human.maybe_take_break()
                except Exception as e:
                    if not self._handle_exception(e, "like"): break

        except Exception as e:
            self._handle_exception(e, "like_hashtag_posts")

        self._lp(f"─── DONE  liked {liked}  #{hashtag}", "success")
        return liked

    # ── COMMENTS ──────────────────────────────────────────────────────────────

    def comment_on_user_posts(self, target_username: str, comments: list, count: int = 3) -> int:
        if not self._guard("comments"): return 0
        self._lp(f"─── COMMENT  @{target_username}  {count} posts", "header")
        commented = 0
        try:
            self._lp(f"Resolving  @{target_username}", "api")
            user_id = self.cl.user_id_from_username(target_username)
            self.human.visit_profile_and_scroll(self.cl, user_id)
            self._lp(f"Fetching {count} posts", "api")
            medias = self.cl.user_medias(user_id, count)
            self._lp(f"Got {len(medias)} posts", "success")

            for i, media in enumerate(medias, 1):
                if not self.session.can_do("comments"): break
                text = random.choice(comments)
                self._lp(f"[{i}/{len(medias)}]  Reading post  {media.pk}", "info")
                self.human.pause_viewing_post()
                self.human.pause_before_comment()
                self.human.simulate_typing(text)
                try:
                    self._lp(f"  Posting comment  \"{text}\"", "api")
                    self.cl.media_comment(media.pk, text)
                    self._record("comments")   # ← persists to disk
                    commented += 1
                    self._lp(f"  Commented  (today:{self.session.actions_today['comments']})", "success")
                    self.human.pause_between_posts()
                    self.human.maybe_take_break()
                except Exception as e:
                    if not self._handle_exception(e, "comment"): break

        except UserNotFound:
            self._lp(f"User not found  @{target_username}", "warn")
        except Exception as e:
            self._handle_exception(e, "comment_on_user_posts")

        self._lp(f"─── DONE  commented {commented}", "success")
        return commented

    def comment_on_hashtag_posts(self, hashtag: str, comments: list, count: int = 5) -> int:
        if not self._guard("comments"): return 0
        self._lp(f"─── COMMENT HASHTAG  #{hashtag}  {count} posts", "header")
        commented = 0
        try:
            self._lp(f"Fetching #{hashtag}", "api")
            medias = self.cl.hashtag_medias_recent(hashtag, count)
            self._lp(f"Got {len(medias)} posts", "success")

            for i, media in enumerate(medias, 1):
                if not self.session.can_do("comments"): break
                text  = random.choice(comments)
                uname = getattr(getattr(media,"user",None),"username","unknown")
                self._lp(f"[{i}/{len(medias)}]  #{hashtag}  @{uname}", "info")
                self.human.pause_viewing_post()
                self.human.pause_before_comment()
                self.human.simulate_typing(text)
                try:
                    self._lp(f"  Posting comment  \"{text}\"", "api")
                    self.cl.media_comment(media.pk, text)
                    self._record("comments")   # ← persists to disk
                    commented += 1
                    self._lp(f"  Commented  @{uname}  (today:{self.session.actions_today['comments']})", "success")
                    self.human.pause_between_posts()
                    self.human.maybe_take_break()
                except Exception as e:
                    if not self._handle_exception(e, "comment"): break

        except Exception as e:
            self._handle_exception(e, "comment_on_hashtag_posts")

        self._lp(f"─── DONE  commented {commented}", "success")
        return commented

    # ── FOLLOW / UNFOLLOW ─────────────────────────────────────────────────────

    def follow_users(self, usernames: list) -> int:
        if not self._guard("follows"): return 0
        self._lp(f"─── FOLLOW  {len(usernames)} users", "header")
        followed = 0
        for i, username in enumerate(usernames, 1):
            if not self.session.can_do("follows"):
                self._lp(f"Daily follow limit reached  {self.session.actions_today['follows']}", "warn")
                break
            self._lp(f"[{i}/{len(usernames)}]  Resolving  @{username}", "api")
            try:
                user_id = self.cl.user_id_from_username(username)
                self.human.visit_profile_and_scroll(self.cl, user_id)
                self._lp(f"  Sending follow  @{username}", "api")
                self.cl.user_follow(user_id)
                self._record("follows")   # ← persists to disk
                followed += 1
                self._lp(f"  Followed  @{username}  (today:{self.session.actions_today['follows']})", "success")
                self.human.pause_between_posts()
                self.human.maybe_take_break()
            except Exception as e:
                if not self._handle_exception(e, "follow"): break

        self._lp(f"─── DONE  followed {followed}/{len(usernames)}", "success")
        return followed

    def follow_user_followers(self, target_username: str, count: int = 20) -> int:
        if not self._guard("follows"): return 0
        self._lp(f"─── FOLLOW FOLLOWERS OF  @{target_username}  up to {count}", "header")
        try:
            self._lp(f"Resolving  @{target_username}", "api")
            user_id   = self.cl.user_id_from_username(target_username)
            self._lp(f"Fetching {count} followers", "api")
            followers = self.cl.user_followers(user_id, amount=count)
            usernames = [u.username for u in followers.values()]
            self._lp(f"Got {len(usernames)} followers to process", "success")
            return self.follow_users(usernames)
        except Exception as e:
            self._handle_exception(e, "follow_user_followers")
            return 0

    def unfollow_users(self, usernames: list) -> int:
        if not self._guard("unfollows"): return 0
        self._lp(f"─── UNFOLLOW  {len(usernames)} users", "header")
        unfollowed = 0
        for i, username in enumerate(usernames, 1):
            if not self.session.can_do("unfollows"):
                self._lp(f"Daily unfollow limit reached", "warn")
                break
            self._lp(f"[{i}/{len(usernames)}]  @{username}", "api")
            try:
                user_id = self.cl.user_id_from_username(username)
                self.cl.user_unfollow(user_id)
                self._record("unfollows")   # ← persists to disk
                unfollowed += 1
                self._lp(f"  Unfollowed  @{username}  (today:{self.session.actions_today['unfollows']})", "success")
                self.human.pause_between_posts()
                self.human.maybe_take_break()
            except Exception as e:
                if not self._handle_exception(e, "unfollow"): break

        self._lp(f"─── DONE  unfollowed {unfollowed}", "success")
        return unfollowed

    def unfollow_non_followers(self, limit: int = 50) -> int:
        if not self._guard("unfollows"): return 0
        self._lp(f"─── UNFOLLOW NON-FOLLOWERS  limit:{limit}", "header")
        try:
            my_id = self.cl.user_id_from_username(self.username)
            self._lp("Fetching following list", "api")
            following = self.cl.user_following(my_id, amount=limit)
            self._lp("Fetching followers list", "api")
            followers    = self.cl.user_followers(my_id, amount=limit)
            follower_ids = set(followers.keys())
            non_followers = [u.username for uid, u in following.items() if uid not in follower_ids]
            self._lp(f"Non-followers found  {len(non_followers)}", "info")
            return self.unfollow_users(non_followers[:limit])
        except Exception as e:
            self._handle_exception(e, "unfollow_non_followers")
            return 0

    # ── STORIES ───────────────────────────────────────────────────────────────

    def watch_user_stories(self, target_username: str) -> int:
        if not self._guard(): return 0
        self._lp(f"─── WATCH STORIES  @{target_username}", "header")
        watched = 0
        try:
            self._lp(f"Resolving  @{target_username}", "api")
            user_id = self.cl.user_id_from_username(target_username)
            self._lp(f"Fetching stories", "api")
            stories = self.cl.user_stories(user_id)
            if not stories:
                self._lp(f"No active stories  @{target_username}", "skip")
                return 0
            self._lp(f"Found {len(stories)} frames", "success")
            story_ids = []
            for j, story in enumerate(stories, 1):
                self._lp(f"  [{j}/{len(stories)}]  Frame  {story.pk}", "info")
                story_ids.append(story.pk)
                self.human.pause_between_story_taps()
            self._lp(f"Marking {len(story_ids)} frames seen", "api")
            self.cl.story_seen(story_ids)
            self._record("story_views", len(story_ids))   # ← persists to disk
            watched = len(story_ids)
            self._lp(f"Stories watched:{watched}  (today:{self.session.actions_today['story_views']})", "success")
        except UserNotFound:
            self._lp(f"User not found  @{target_username}", "warn")
        except Exception as e:
            self._handle_exception(e, "watch_user_stories")

        self._lp(f"─── DONE", "success")
        return watched

    def watch_following_stories(self, count: int = 20) -> int:
        if not self._guard(): return 0
        self._lp(f"─── WATCH FEED STORIES  {count} accounts", "header")
        return self.human.browse_stories_passively(self.cl, count=count)

    # ── DIRECT MESSAGES ───────────────────────────────────────────────────────

    def send_dm(self, target_username: str, message: str) -> bool:
        if not self._guard("dms"): return False
        self._lp(f"─── SEND DM  @{target_username}", "header")
        try:
            self._lp(f"Resolving  @{target_username}", "api")
            user_id = self.cl.user_id_from_username(target_username)
            self.human.pause_reading_dm()
            self.human.simulate_typing(message)
            self._lp(f"Sending DM via API", "api")
            self.cl.direct_send(message, [user_id])
            self._record("dms")   # ← persists to disk
            self._lp(f"DM sent  @{target_username}  (today:{self.session.actions_today['dms']})", "success")
            self.human.pause_between_posts()
            return True
        except Exception as e:
            self._handle_exception(e, "send_dm")
            return False

    def send_dm_to_list(self, usernames: list, messages: list) -> int:
        self._lp(f"─── BULK DM  {len(usernames)} users", "header")
        sent = 0
        for i, username in enumerate(usernames, 1):
            if not self.session.can_do("dms"):
                self._lp("Daily DM limit reached", "warn")
                break
            self._lp(f"[{i}/{len(usernames)}]  @{username}", "info")
            if self.send_dm(username, random.choice(messages)):
                sent += 1
            lw(self.username, "Anti-spam pause between DMs", random.uniform(15, 45))
        self._lp(f"─── DONE  sent {sent}/{len(usernames)}", "success")
        return sent

    def auto_reply_dms(self, reply_map: dict, max_threads: int = 20) -> int:
        if not self._guard(): return 0
        self._lp(f"─── AUTO-REPLY DMs  checking {max_threads} threads", "header")
        replied = 0
        try:
            self._lp("Fetching unread threads from API", "api")
            threads = self.cl.direct_threads(amount=max_threads, selected_filter="unread")
            self._lp(f"Unread threads  {len(threads)}", "success")

            for i, thread in enumerate(threads, 1):
                if not thread.messages:
                    self._lp(f"  [{i}]  Thread {thread.id}  no messages — skip", "skip")
                    continue
                last_msg = thread.messages[0]
                if str(last_msg.user_id) == str(self.cl.user_id):
                    self._lp(f"  [{i}]  Thread {thread.id}  last message is ours — skip", "skip")
                    continue

                text  = (last_msg.text or "").lower()
                users = ", ".join(u.username for u in thread.users)
                self._lp(f"  [{i}]  From [{users}]  \"{text[:60]}\"", "info")

                reply   = reply_map.get("_default", "")
                matched = None
                for keyword, response in reply_map.items():
                    if keyword != "_default" and keyword.lower() in text:
                        reply   = response
                        matched = keyword
                        break

                if matched:
                    self._lp(f"  Keyword match  \"{matched}\"  reply:\"{reply[:60]}\"", "info")
                else:
                    self._lp(f"  No keyword match  using default reply", "info")

                if reply:
                    self.human.pause_reading_dm()
                    self.human.simulate_typing(reply)
                    self._lp(f"  Sending reply via API", "api")
                    self.cl.direct_answer(thread.id, reply)
                    replied += 1
                    self._lp(f"  Replied to [{users}]", "success")
                    self.human.pause_between_posts()
                else:
                    self._lp(f"  No reply configured — skip", "skip")

        except Exception as e:
            self._handle_exception(e, "auto_reply_dms")

        self._lp(f"─── DONE  replied {replied}", "success")
        return replied

    def get_inbox_summary(self) -> dict:
        if not self._guard(): return {}
        self._lp("Fetching DM inbox from API", "api")
        try:
            threads = self.cl.direct_threads(amount=30)
            unread  = [t for t in threads if t.read_state != 0]
            self._lp(f"Inbox  total:{len(threads)}  unread:{len(unread)}", "success")
            return {
                "total_threads":  len(threads),
                "unread_threads": len(unread),
                "threads": [
                    {
                        "id":           t.id,
                        "users":        [u.username for u in t.users],
                        "last_message": t.messages[0].text if t.messages else "",
                        "unread":       t.read_state != 0,
                    }
                    for t in threads[:10]
                ],
            }
        except Exception as e:
            self._handle_exception(e, "get_inbox_summary")
            return {}

    # ── HASHTAG ENGAGEMENT ────────────────────────────────────────────────────

    def engage_hashtag(self, hashtag: str, actions: dict) -> dict:
        if not self._guard(): return {}
        count = actions.get("count", 10)
        self._lp(f"─── HASHTAG ENGAGE  #{hashtag}  {count} posts", "header")
        self._lp(f"    like:{actions.get('like')}  comment:{actions.get('comment')}  follow:{actions.get('follow')}", "info")
        results = {"liked": 0, "commented": 0, "followed": 0}
        try:
            self._lp(f"Fetching #{hashtag} from API", "api")
            medias = self.cl.hashtag_medias_recent(hashtag, count)
            self._lp(f"Got {len(medias)} posts", "success")

            for i, media in enumerate(medias, 1):
                uname = getattr(getattr(media,"user",None),"username","unknown")
                self._lp(f"[{i}/{len(medias)}]  @{uname}  {media.pk}", "info")
                self.human.pause_viewing_post()

                if actions.get("like") and self.session.can_do("likes"):
                    self.human.pause_before_like()
                    try:
                        self._lp(f"  Sending like", "api")
                        self.cl.media_like(media.pk)
                        self._record("likes")   # ← persists to disk
                        results["liked"] += 1
                        self._lp(f"  Liked  @{uname}  (today:{self.session.actions_today['likes']})", "success")
                    except Exception as e:
                        self._handle_exception(e, "like")

                if actions.get("comment") and actions.get("comments") and self.session.can_do("comments"):
                    text = random.choice(actions["comments"])
                    self.human.pause_before_comment()
                    self.human.simulate_typing(text)
                    try:
                        self._lp(f"  Posting comment  \"{text}\"", "api")
                        self.cl.media_comment(media.pk, text)
                        self._record("comments")   # ← persists to disk
                        results["commented"] += 1
                        self._lp(f"  Commented  (today:{self.session.actions_today['comments']})", "success")
                    except Exception as e:
                        self._handle_exception(e, "comment")

                if actions.get("follow") and self.session.can_do("follows"):
                    self.human.visit_profile_and_scroll(self.cl, media.user.pk)
                    try:
                        self._lp(f"  Sending follow  @{uname}", "api")
                        self.cl.user_follow(media.user.pk)
                        self._record("follows")   # ← persists to disk
                        results["followed"] += 1
                        self._lp(f"  Followed  @{uname}  (today:{self.session.actions_today['follows']})", "success")
                    except Exception as e:
                        self._handle_exception(e, "follow")

                self.human.pause_between_posts()
                self.human.maybe_take_break()

        except Exception as e:
            self._handle_exception(e, "engage_hashtag")

        self._lp(f"─── DONE  liked:{results['liked']}  commented:{results['commented']}  followed:{results['followed']}", "success")
        return results


    # ── PUBLISHING ────────────────────────────────────────────────────────────

    def post_photo(self, image_path: str, meta: dict = None) -> dict:
        """Post a single photo. meta keys: caption, hashtags, location, usertags."""
        if not self._guard(): return {"ok": False, "error": "not logged in"}
        return self.publisher.post_photo(image_path, meta or {})

    def post_carousel(self, image_paths: list, meta: dict = None) -> dict:
        """Post a carousel (2-10 images). meta keys: caption, hashtags, location."""
        if not self._guard(): return {"ok": False, "error": "not logged in"}
        return self.publisher.post_carousel(image_paths, meta or {})

    def post_story_photo(self, image_path: str, meta: dict = None) -> dict:
        """Post a photo story. meta keys: mentions, hashtag_sticker, location,
        link, music_track_id, music_from_reel."""
        if not self._guard(): return {"ok": False, "error": "not logged in"}
        return self.publisher.post_story_photo(image_path, meta or {})

    def post_story_video(self, video_path: str, meta: dict = None) -> dict:
        """Post a video story. Same meta keys as post_story_photo."""
        if not self._guard(): return {"ok": False, "error": "not logged in"}
        return self.publisher.post_story_video(video_path, meta or {})

    def publish_from_queue(self) -> list:
        """
        Scan posts/queue/ and publish all ready posts assigned to this account.
        Returns list of result dicts.
        """
        if not self._guard(): return []
        from poster import list_queue, mark_done, mark_failed
        results  = []
        pending  = list_queue()

        for post in pending:
            if not post["ready"]:
                self._lp(f"Skipping  {post['name']}  not yet scheduled", "info")
                continue

            # Check if this post is meant for this account
            target_accounts = post["meta"].get("accounts", [])
            if target_accounts and self.username not in target_accounts:
                continue

            self._lp(f"Publishing from queue  {post['name']}", "header")
            result = self.publisher.publish_from_folder(post["path"])
            result["name"] = post["name"]
            results.append(result)

            if result["ok"]:
                mark_done(post["path"])
                self._lp(f"Queued post done  {post['name']}", "success")
            else:
                mark_failed(post["path"], result.get("error", "unknown error"))
                self._lp(f"Queued post failed  {post['name']}  {result.get('error')}", "warn")

            # Human-like pause between posts
            self.human.pause_between_posts()

        return results

    # ── STATS ─────────────────────────────────────────────────────────────────

    def get_account_stats(self) -> dict:
        if not self._guard(): return {"username": self.username, "error": "not logged in"}
        self._lp("Fetching account info from API", "api")
        try:
            user_id = self.cl.user_id_from_username(self.username)
            info    = self.cl.user_info(user_id)
            self._lp(f"Stats fetched  @{self.username}", "success")

            # ── Persist a follower snapshot so growth is tracked over time ──
            _persist_snapshot(
                self.username,
                followers   = info.follower_count,
                following   = info.following_count,
                media_count = info.media_count,
            )

            return {
                "username":    self.username,
                "full_name":   info.full_name,
                "followers":   info.follower_count,
                "following":   info.following_count,
                "media_count": info.media_count,
                "is_private":  info.is_private,
                "is_verified": info.is_verified,
                "today":       dict(self.session.actions_today),
                "fatigue":     f"{self.session.fatigue_level:.0%}",
            }
        except Exception as e:
            self._handle_exception(e, "get_account_stats")
            return {"username": self.username, "error": str(e)}

    def get_session_summary(self) -> str:
        return self.session.summary()