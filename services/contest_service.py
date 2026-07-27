import logging
from datetime import datetime, timedelta, timezone
from repositories import ContestRepository, ReminderRepository, ContestSyncStateRepository
from services.contest_sources import ContestSourceAggregator
from services.notification_service import notification_manager

logger = logging.getLogger("platstat.contest_service")

contest_repo = ContestRepository()
reminder_repo = ReminderRepository()
sync_state_repo = ContestSyncStateRepository()


class ContestService:
    def __init__(self):
        self.aggregator = ContestSourceAggregator()
        self.contest_repo = contest_repo
        self.reminder_repo = reminder_repo
        self.sync_state_repo = sync_state_repo

    def sync_contests(self):
        """Synchronize upcoming contests from all sources, remove duplicates, and purge expired contests."""
        logger.info("Starting contest synchronization...")
        try:
            raw_contests = self.aggregator.fetch_all()
            sync_count = 0
            now = datetime.utcnow()

            # Upsert contests into collection
            for c_doc in raw_contests:
                st = c_doc.get("startTime")
                dur = c_doc.get("duration") or 0
                if st:
                    # Purge if expired more than 1 hour ago
                    if st + timedelta(seconds=dur) < now - timedelta(hours=1):
                        continue
                contest_repo.upsert_contest(c_doc)
                sync_count += 1

            # Cleanup expired contests in database
            self.purge_expired_contests()

            sync_state_repo.record_sync(status="success", sync_count=sync_count)
            logger.info("Contest synchronization complete. Synced %d contests.", sync_count)
            return {"status": "success", "synced": sync_count}

        except Exception as exc:
            logger.exception("Contest sync failed: %s", exc)
            sync_state_repo.record_sync(status="error", errors=[str(exc)])
            return {"status": "error", "error": str(exc)}

    def purge_expired_contests(self):
        """Remove contests from database that have ended."""
        now = datetime.utcnow()
        all_contests = contest_repo.find()
        expired_ids = []
        for c in all_contests:
            st = c.get("startTime")
            dur = c.get("duration", 0) or 0
            if isinstance(st, str):
                try:
                    st = datetime.fromisoformat(st.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    continue
            if not st or st < datetime(2020, 1, 1) or st + timedelta(seconds=dur) < now or dur > 864000:
                expired_ids.append(c["_id"])

        if expired_ids:
            contest_repo.collection.delete_many({"_id": {"$in": expired_ids}})
            logger.info("Purged %d expired contests.", len(expired_ids))

    def get_upcoming_contests(self, platform=None, search=None, favorites_only=False, sort_by="nearest", user_id="default_user", page=1, page_size=50):
        """Fetch and filter upcoming contests with user reminder/favorite annotations."""
        now = datetime.utcnow()

        all_docs = contest_repo.find()
        user_reminders = reminder_repo.get_user_reminders(user_id)
        reminder_map = {r["contestId"]: r for r in user_reminders}

        upcoming = []
        for c in all_docs:
            st = c.get("startTime")
            dur = c.get("duration", 0) or 0

            if isinstance(st, str):
                try:
                    st = datetime.fromisoformat(st.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    continue

            # Exclude finished contests
            if not st or st + timedelta(seconds=dur) < now:
                continue

            # Apply platform filter
            c_plat = (c.get("platform") or "").lower()
            if platform and platform.lower() != "all" and c_plat != platform.lower():
                continue

            # Apply search filter
            title = c.get("title", "")
            if search and search.lower() not in title.lower():
                continue

            # Annotation
            cid = c.get("contestId") or f"{c_plat}_{c.get('externalId')}"
            rem_info = reminder_map.get(cid, {})
            is_fav = rem_info.get("favorite", False)
            subscribed = bool(rem_info.get("intervals"))

            if favorites_only and not is_fav:
                continue

            # Time calculation
            seconds_remaining = max(0, int((st - now).total_seconds()))
            status = "CODING" if st <= now and st + timedelta(seconds=dur) >= now else "UPCOMING"

            formatted_c = {
                "contestId": cid,
                "externalId": c.get("externalId"),
                "platform": c_plat,
                "title": title,
                "startTime": st.isoformat() + "Z",
                "startTimeFormatted": st.strftime("%b %d, %Y - %I:%M %p UTC"),
                "durationSeconds": dur,
                "durationFormatted": f"{dur // 3600}h {(dur % 3600) // 60}m" if dur >= 3600 else f"{dur // 60}m",
                "url": c.get("url", "#"),
                "source": c.get("source", "api"),
                "status": status,
                "secondsRemaining": seconds_remaining,
                "isFavorite": is_fav,
                "isSubscribed": subscribed,
                "subscribedIntervals": rem_info.get("intervals", []),
            }
            upcoming.append(formatted_c)

        # Sorting
        if sort_by == "platform":
            upcoming.sort(key=lambda x: (x["platform"], x["secondsRemaining"]))
        elif sort_by == "duration":
            upcoming.sort(key=lambda x: x["durationSeconds"])
        else:
            # default nearest
            upcoming.sort(key=lambda x: x["secondsRemaining"])

        total_count = len(upcoming)
        if page_size:
            start_idx = (max(page, 1) - 1) * page_size
            upcoming = upcoming[start_idx:start_idx + page_size]

        return upcoming, total_count

    def toggle_favorite(self, user_id, contest_id, platform, favorite=True):
        return reminder_repo.set_favorite(user_id, contest_id, platform, favorite=favorite)

    def subscribe_reminder(self, user_id, contest_id, platform, intervals=None):
        intervals = intervals or ["1h", "30m", "live"]
        rem = reminder_repo.set_reminder(user_id, contest_id, platform, intervals=intervals)
        
        # Send confirmation notification
        notification_manager.send_notification(
            user_id=user_id,
            title="Reminder Subscribed",
            message=f"Subscribed to reminders ({', '.join(intervals)}) for contest.",
            contest_id=contest_id
        )
        return rem

    def unsubscribe_reminder(self, user_id, contest_id):
        return reminder_repo.delete({"userId": user_id, "contestId": contest_id})

    def get_dashboard_contest_summary(self, user_id="default_user"):
        upcoming, total = self.get_upcoming_contests(user_id=user_id, page_size=0)
        
        now = datetime.utcnow()
        week_end = now + timedelta(days=7)

        next_contest = upcoming[0] if upcoming else None
        
        contests_this_week = 0
        platform_counts = {"leetcode": 0, "codeforces": 0, "codechef": 0, "atcoder": 0}

        for c in upcoming:
            plat = c["platform"]
            if plat in platform_counts:
                platform_counts[plat] += 1
            st_dt = datetime.fromisoformat(c["startTime"].replace("Z", "+00:00")).replace(tzinfo=None)
            if st_dt <= week_end:
                contests_this_week += 1

        return {
            "nextContest": next_contest,
            "contestsThisWeek": contests_this_week,
            "platformCounts": platform_counts,
            "totalUpcoming": total
        }


contest_service = ContestService()
