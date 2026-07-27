import threading
import time
import logging
from datetime import datetime, timedelta
from services.contest_service import contest_service
from repositories import ReminderRepository, ContestRepository
from services.notification_service import notification_manager

logger = logging.getLogger("platstat.scheduler")

reminder_repo = ReminderRepository()
contest_repo = ContestRepository()

INTERVAL_SECONDS_MAP = {
    "1h": 3600,
    "30m": 1800,
    "live": 0
}


class ContestScheduler:
    def __init__(self, sync_interval_seconds=1800):
        self.sync_interval_seconds = sync_interval_seconds
        self._running = False
        self._thread = None
        self._last_sync_time = 0

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("ContestScheduler thread started.")

    def stop(self):
        self._running = False

    def _run_loop(self):
        # Initial sync on startup
        time.sleep(2)
        try:
            contest_service.sync_contests()
            self._last_sync_time = time.time()
        except Exception as e:
            logger.error("Initial contest sync error: %s", e)

        while self._running:
            now_ts = time.time()
            # Check if sync interval reached
            if now_ts - self._last_sync_time >= self.sync_interval_seconds:
                try:
                    contest_service.sync_contests()
                    self._last_sync_time = now_ts
                except Exception as e:
                    logger.error("Periodic contest sync error: %s", e)

            # Process reminders
            try:
                self._process_reminder_notifications()
            except Exception as e:
                logger.error("Error processing reminders: %s", e)

            # Sleep 30 seconds before next check
            time.sleep(30)

    def _process_reminder_notifications(self):
        now_dt = datetime.utcnow()
        reminders = reminder_repo.find()

        for rem in reminders:
            contest_id = rem.get("contestId")
            user_id = rem.get("userId", "default_user")
            intervals = rem.get("intervals") or []
            triggered = rem.get("triggeredIntervals") or []

            if not contest_id or not intervals:
                continue

            contest = contest_repo.find_one({"contestId": contest_id})
            if not contest:
                continue

            st = contest.get("startTime")
            if isinstance(st, str):
                try:
                    st = datetime.fromisoformat(st.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    continue

            if not st:
                continue

            dur = contest.get("duration", 7200) or 7200
            secs_to_start = (st - now_dt).total_seconds()

            # Skip if contest ended
            if secs_to_start + dur < 0:
                continue

            for interval_code in intervals:
                if interval_code in triggered:
                    continue

                target_secs = INTERVAL_SECONDS_MAP.get(interval_code)
                if target_secs is None:
                    continue

                should_trigger = False
                if interval_code == "live":
                    # Trigger when contest starts (between 60s before start and 180s after start)
                    if -180 <= secs_to_start <= 60:
                        should_trigger = True
                        title = f"CONTEST LIVE: {contest.get('platform', '').capitalize()}"
                        msg = f"🔥 {contest.get('title')} is NOW LIVE! Join the contest now."
                else:
                    # Trigger for 1h or 30m before start
                    if target_secs - 180 <= secs_to_start <= target_secs + 180:
                        should_trigger = True
                        title = f"Contest Reminder: {contest.get('platform', '').capitalize()}"
                        formatted_time = "1 hour" if interval_code == "1h" else "30 minutes"
                        msg = f"⏰ {contest.get('title')} starts in {formatted_time}."

                if should_trigger:
                    notification_manager.send_notification(
                        user_id=user_id,
                        title=title,
                        message=msg,
                        contest_id=contest_id,
                        n_type="reminder"
                    )

                    # Update triggered intervals in reminder
                    triggered.append(interval_code)
                    reminder_repo.update_one(
                        {"_id": rem["_id"]},
                        {"triggeredIntervals": triggered}
                    )
                    logger.info("Sent %s reminder notification for contest %s to user %s", interval_code, contest_id, user_id)


contest_scheduler = ContestScheduler(sync_interval_seconds=1800)
