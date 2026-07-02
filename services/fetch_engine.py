from dataclasses import dataclass
from datetime import datetime
import time
import uuid

from config import settings
from repositories import HistoryRepository, JobRepository, StatRepository, StudentRepository
from services.codechef_service import get_cc_summary
from services.codeforces_service import get_cf_summary
from services.leetcode_service import get_lc_summary
from services.ranking_service import compute_rankings
from utils.ranking_utils import month_key, week_key, year_key
from db import store


job_repo = JobRepository()
stat_repo = StatRepository()
history_repo = HistoryRepository()
student_repo = StudentRepository()


@dataclass
class FetchResult:
    ok: bool
    data: dict | None = None
    error: str | None = None


class FetchEngine:
    def __init__(self):
        self._job_cache = {}

    def create_job(self, rows, class_id=""):
        job = job_repo.create_job({"jobId": str(uuid.uuid4()), "classId": class_id, "total": len(rows)})
        job["rows"] = rows
        job_repo.update_one({"jobId": job["jobId"]}, {"rows": rows}, upsert=True)
        self._job_cache[job["jobId"]] = job
        history_repo.create({
            "requestId": job["jobId"],
            "classId": class_id,
            "status": "queued",
            "total": len(rows),
            "createdAt": datetime.utcnow(),
        })
        return job

    def get_job(self, job_id):
        if job_id in self._job_cache:
            return self._job_cache[job_id]
        return job_repo.find_one({"jobId": job_id})

    def cancel_job(self, job_id):
        job = self._job_cache.get(job_id)
        if job:
            job["status"] = "cancelled"
            job["cancelled"] = True
            job["updatedAt"] = datetime.utcnow()
            job_repo.update_one({"jobId": job_id}, job, upsert=True)
            return job
        existing = job_repo.find_one({"jobId": job_id})
        if existing:
            existing["status"] = "cancelled"
            existing["cancelled"] = True
            job_repo.update_one({"jobId": job_id}, existing, upsert=True)
        return existing

    def _platforms_for_row(self, row):
        platforms = []
        for platform in ("codeforces", "codechef", "leetcode"):
            if (row.get(platform) or "").strip():
                platforms.append(platform)
        return platforms

    def _build_profile_url(self, platform, platform_id, row):
        return (
            row.get(f"{platform}_url")
            or row.get("profile_url")
            or row.get("profileLink")
            or ""
        )

    def _call_scraper(self, platform, row, idx):
        name = (row.get("studentName") or row.get("name") or "").strip()
        regno = (row.get("register_no") or row.get("registerNo") or "").strip()
        dept = (row.get("department") or "").strip()
        platform_id = (row.get(platform) or "").strip()
        if not name or not platform_id:
            return None
        if platform == "codeforces":
            return get_cf_summary(idx, name, regno, dept, platform_id)
        if platform == "codechef":
            return get_cc_summary(idx, name, regno, dept, platform_id)
        if platform == "leetcode":
            return get_lc_summary(idx, name, regno, dept, platform_id)
        return None

    def _run_single(self, platform, row, idx, class_id):
        platform_id = (row.get(platform) or "").strip()
        profile_url = self._build_profile_url(platform, platform_id, row)
        for attempt in range(settings.FETCH_RETRIES):
            try:
                result = self._call_scraper(platform, row, idx)
                if not result:
                    continue
                snapshot = {
                    "classId": class_id or row.get("classId", ""),
                    "studentId": row.get("studentId", ""),
                    "studentName": row.get("studentName") or row.get("name") or "",
                    "registerNo": row.get("register_no") or row.get("registerNo") or "",
                    "platformId": platform_id,
                    "username": platform_id,
                    "platformName": platform.capitalize(),
                    "platform": platform,
                    "profileUrl": profile_url,
                    "fetchDate": datetime.utcnow(),
                    "rawResponse": result,
                    "status": "success",
                    "source": "existing_scraper",
                    "rankingPeriod": "overall",
                    "weekKey": week_key(),
                    "monthKey": month_key(),
                    "yearKey": year_key(),
                }
                snapshot.update(result)
                stat_repo.append_snapshot(snapshot)
                return FetchResult(ok=True, data=snapshot)
            except Exception as exc:
                store.fetch_logs.insert_one({
                    "type": "fetch_error",
                    "platform": platform,
                    "platformId": platform_id,
                    "attempt": attempt + 1,
                    "error": str(exc),
                    "createdAt": datetime.utcnow(),
                })
                time.sleep(min(2 ** attempt, 8))
        history_repo.create({
            "requestId": str(uuid.uuid4()),
            "status": "failed",
            "platform": platform,
            "platformId": platform_id,
            "createdAt": datetime.utcnow(),
        })
        return FetchResult(ok=False, error=f"Failed {platform}:{platform_id}")

    def run_job(self, job):
        rows = job.get("rows", [])
        class_id = job.get("classId", "")
        job["status"] = "running"
        job["startedAt"] = job.get("startedAt") or datetime.utcnow()
        job["rows"] = rows
        job_repo.update_one({"jobId": job["jobId"]}, job, upsert=True)
        start = time.time()
        seen = set()
        results = []
        processed = success = failed = skipped = 0

        for idx, row in enumerate(rows, start=1):
            if job.get("cancelled"):
                break
            for platform in self._platforms_for_row(row):
                platform_id = (row.get(platform) or "").strip()
                dedupe_key = f"{platform}:{platform_id}"
                if dedupe_key in seen:
                    skipped += 1
                    continue
                seen.add(dedupe_key)
                job["currentStudent"] = row.get("studentName") or row.get("name") or ""
                job["currentPlatformId"] = platform_id
                job["processed"] = processed
                job["success"] = success
                job["failed"] = failed
                job["remaining"] = max(0, len(rows) - processed)
                job["updatedAt"] = datetime.utcnow()
                job_repo.update_one({"jobId": job["jobId"]}, job, upsert=True)

                result = self._run_single(platform, row, idx, class_id)
                processed += 1
                if result.ok:
                    success += 1
                    results.append(result.data)
                else:
                    failed += 1

                time.sleep(1 / max(settings.MAX_CONCURRENT_FETCHES, 1))

        elapsed = time.time() - start
        job["processed"] = processed
        job["success"] = success
        job["failed"] = failed
        job["skipped"] = skipped
        job["elapsedSeconds"] = elapsed
        job["etaSeconds"] = 0
        job["status"] = "cancelled" if job.get("cancelled") else "completed"
        job["finishedAt"] = datetime.utcnow()
        job_repo.update_one({"jobId": job["jobId"]}, job, upsert=True)

        history_repo.create({
            "requestId": job["jobId"],
            "classId": class_id,
            "status": job["status"],
            "processed": processed,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "elapsedSeconds": elapsed,
            "createdAt": datetime.utcnow(),
        })
        compute_rankings()
        self._job_cache[job["jobId"]] = job
        job["results"] = results
        return job

    def resume_job(self, job_id):
        job = self.get_job(job_id)
        if not job:
            return None
        job.setdefault("rows", [])
        job["cancelled"] = False
        job["status"] = "queued"
        return self.run_job(job)


fetch_engine = FetchEngine()
