"""
Scheduler
Runs tasks on a defined schedule (cron-like or interval-based).
"""

import time
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("scheduler")


class TaskScheduler:
    """
    Simple interval-based task scheduler.
    Supports one-time tasks, repeating tasks, and scheduled windows.
    """

    def __init__(self, manager):
        self.manager = manager
        self.jobs = []
        self._stop_event = threading.Event()

    def add_job(self, task_cfg: dict, interval_minutes: int = 60,
                run_at: str = None, concurrent: bool = True):
        """
        Add a scheduled job.
        - interval_minutes: run every N minutes
        - run_at: run at specific HH:MM time daily (overrides interval)
        - concurrent: whether to run accounts concurrently
        """
        job = {
            "task": task_cfg,
            "interval_minutes": interval_minutes,
            "run_at": run_at,
            "concurrent": concurrent,
            "last_run": None,
            "next_run": self._calc_next_run(run_at, interval_minutes),
        }
        self.jobs.append(job)
        logger.info(
            f"📅 Scheduled '{task_cfg.get('action')}' "
            f"{'at ' + run_at if run_at else f'every {interval_minutes}m'}"
        )

    def _calc_next_run(self, run_at: str, interval_minutes: int) -> datetime:
        now = datetime.now()
        if run_at:
            h, m = map(int, run_at.split(":"))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target
        return now + timedelta(minutes=interval_minutes)

    def start(self, blocking: bool = True):
        """Start the scheduler loop."""
        logger.info("🚀 Scheduler started")
        self._stop_event.clear()
        if blocking:
            self._run_loop()
        else:
            t = threading.Thread(target=self._run_loop, daemon=True)
            t.start()
            return t

    def stop(self):
        """Stop the scheduler."""
        self._stop_event.set()
        logger.info("🛑 Scheduler stopped")

    def _run_loop(self):
        while not self._stop_event.is_set():
            now = datetime.now()
            for job in self.jobs:
                if now >= job["next_run"]:
                    logger.info(f"⏰ Running scheduled task: {job['task'].get('action')}")
                    try:
                        self.manager.run_task_from_config(
                            job["task"],
                            concurrent=job["concurrent"]
                        )
                    except Exception as e:
                        logger.error(f"Scheduled task failed: {e}")
                    job["last_run"] = now
                    job["next_run"] = self._calc_next_run(
                        job["run_at"], job["interval_minutes"]
                    )
                    logger.info(f"Next run at: {job['next_run'].strftime('%H:%M')}")
            time.sleep(30)  # check every 30 seconds


def build_scheduler_from_config(manager, schedule_cfg: list) -> TaskScheduler:
    """
    Build a TaskScheduler from config YAML schedule section.
    """
    scheduler = TaskScheduler(manager)
    for entry in schedule_cfg:
        scheduler.add_job(
            task_cfg=entry["task"],
            interval_minutes=entry.get("interval_minutes", 60),
            run_at=entry.get("run_at"),
            concurrent=entry.get("concurrent", True),
        )
    return scheduler