"""
Account Manager
Loads all accounts from config, runs tasks concurrently via threading.
"""

import threading
import time
import logging
from typing import Optional
from bot_engine import InstagramBot

logger = logging.getLogger("manager")


class AccountManager:
    """
    Manages a pool of Instagram bots (one per account).
    Supports running tasks on all accounts concurrently or sequentially.
    """

    def __init__(self, accounts_cfg: list):
        self.bots: list[InstagramBot] = []
        for acc in accounts_cfg:
            bot = InstagramBot(acc)
            self.bots.append(bot)
        logger.info(f"AccountManager initialized with {len(self.bots)} account(s)")

    def login_all(self, concurrent: bool = True):
        """Login all accounts."""
        if concurrent:
            threads = [threading.Thread(target=bot.login, daemon=True) for bot in self.bots]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        else:
            for bot in self.bots:
                bot.login()
                time.sleep(2)

    def _run_on_all(self, task_fn, concurrent: bool = True):
        """Run a task function on all logged-in bots."""
        active_bots = [b for b in self.bots if b.logged_in]
        if not active_bots:
            logger.warning("No logged-in bots available")
            return

        if concurrent:
            threads = [threading.Thread(target=task_fn, args=(bot,), daemon=True) for bot in active_bots]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        else:
            for bot in active_bots:
                task_fn(bot)

    # ─────────────────────────────────────────────
    # BULK ACTIONS
    # ─────────────────────────────────────────────

    def run_task_from_config(self, task_cfg: dict, concurrent: bool = True):
        """
        Execute a task defined in config on all accounts.
        task_cfg example:
          { "action": "like_hashtag", "hashtag": "photography", "count": 10 }
        """
        action = task_cfg.get("action")

        def execute(bot: InstagramBot):
            try:
                if action == "like_user_posts":
                    bot.like_user_posts(task_cfg["target"], task_cfg.get("count", 5))

                elif action == "like_hashtag":
                    bot.like_hashtag_posts(task_cfg["hashtag"], task_cfg.get("count", 10))

                elif action == "comment_user_posts":
                    bot.comment_on_user_posts(
                        task_cfg["target"],
                        task_cfg["comments"],
                        task_cfg.get("count", 3)
                    )

                elif action == "comment_hashtag":
                    bot.comment_on_hashtag_posts(
                        task_cfg["hashtag"],
                        task_cfg["comments"],
                        task_cfg.get("count", 5)
                    )

                elif action == "follow_users":
                    bot.follow_users(task_cfg["usernames"])

                elif action == "follow_followers_of":
                    bot.follow_user_followers(task_cfg["target"], task_cfg.get("count", 20))

                elif action == "unfollow_users":
                    bot.unfollow_users(task_cfg["usernames"])

                elif action == "unfollow_non_followers":
                    bot.unfollow_non_followers(task_cfg.get("limit", 50))

                elif action == "watch_stories":
                    bot.watch_user_stories(task_cfg["target"])

                elif action == "watch_feed_stories":
                    bot.watch_following_stories(task_cfg.get("count", 20))

                elif action == "send_dms":
                    bot.send_dm_to_list(task_cfg["usernames"], task_cfg["messages"])

                elif action == "auto_reply_dms":
                    bot.auto_reply_dms(task_cfg["reply_map"], task_cfg.get("max_threads", 20))

                elif action == "engage_hashtag":
                    bot.engage_hashtag(task_cfg["hashtag"], task_cfg)

                else:
                    bot.log.warning(f"Unknown action: {action}")

            except Exception as e:
                bot.log.error(f"Task '{action}' failed: {e}")

        self._run_on_all(execute, concurrent=concurrent)

    def run_all_tasks(self, tasks: list, concurrent: bool = True):
        """Run a list of task configs sequentially (tasks run one after another, accounts run concurrently per task)."""
        for task in tasks:
            logger.info(f"▶️  Running task: {task.get('action')} ...")
            self.run_task_from_config(task, concurrent=concurrent)
            delay = task.get("delay_after", 5)
            if delay:
                time.sleep(delay)

    def get_all_stats(self) -> list:
        """Fetch account stats for all logged-in accounts."""
        results = []
        for bot in self.bots:
            if bot.logged_in:
                stats = bot.get_account_stats()
                results.append(stats)
        return results

    def get_bot(self, username: str) -> Optional[InstagramBot]:
        """Get a specific bot by username."""
        for bot in self.bots:
            if bot.username == username:
                return bot
        return None