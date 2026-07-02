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

    def _persist_job(self, job):
        job["updatedAt"] = datetime.utcnow()
        job_repo.update_one({"jobId": job["jobId"]}, job, upsert=True)
        self._job_cache[job["jobId"]] = job
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
        if row.get(f"{platform}_url") or row.get("profile_url") or row.get("profileLink"):
            return (
            row.get(f"{platform}_url")
            or row.get("profile_url")
            or row.get("profileLink")
            or ""
        )
        if platform == "codeforces":
            return f"https://codeforces.com/profile/{platform_id}"
        if platform == "codechef":
            return f"https://www.codechef.com/users/{platform_id}"
        if platform == "leetcode":
            return f"https://leetcode.com/u/{platform_id}"
        return ""

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

    def _prepare_rows(self, rows):
        seen = set()
        prepared = []
        for row in rows:
            for platform in self._platforms_for_row(row):
                platform_id = (row.get(platform) or "").strip()
                key = f"{platform}:{platform_id}"
                if key in seen:
                    continue
                seen.add(key)
                prepared.append((row, platform))
        return prepared

    def process_job_step(self, job_id):
        job = self.get_job(job_id)
        if not job or job.get("status") in {"completed", "cancelled"}:
            return job
        rows = job.get("rows", [])
        prepared = job.get("_prepared")
        if prepared is None:
            prepared = self._prepare_rows(rows)
            job["_prepared"] = prepared
            job["_cursor"] = 0
        cursor = job.get("_cursor", 0)
        batch_size = max(1, int(settings.BATCH_SIZE))
        batch = prepared[cursor: cursor + batch_size]
        if not batch:
            job["status"] = "completed"
            job["finishedAt"] = datetime.utcnow()
            self._persist_job(job)
            compute_rankings()
            return job

        job["status"] = "running"
        processed = job.get("processed", 0)
        success = job.get("success", 0)
        failed = job.get("failed", 0)
        skipped = job.get("skipped", 0)
        results = job.get("results", [])
        started_at = job.get("startedAt") or datetime.utcnow()
        job["startedAt"] = started_at

        for row, platform in batch:
            if job.get("cancelled"):
                break
            platform_id = (row.get(platform) or "").strip()
            idx = processed + 1
            job["currentStudent"] = row.get("studentName") or row.get("name") or ""
            job["currentPlatformId"] = platform_id
            job["currentPlatform"] = platform
            self._persist_job(job)
            result = self._run_single(platform, row, idx, job.get("classId", ""))
            processed += 1
            if result.ok:
                success += 1
                results.append(result.data)
            else:
                failed += 1
            time.sleep(1 / max(settings.MAX_CONCURRENT_FETCHES, 1))

        job["rows"] = rows
        job["_prepared"] = prepared
        job["_cursor"] = cursor + len(batch)
        job["processed"] = processed
        job["success"] = success
        job["failed"] = failed
        job["skipped"] = skipped
        job["remaining"] = max(0, len(prepared) - job["_cursor"])
        job["elapsedSeconds"] = max(0, (datetime.utcnow() - started_at).total_seconds())
        total_done = max(processed, 1)
        job["rpm"] = round((success + failed) / max(job["elapsedSeconds"] / 60, 1), 2)
        job["etaSeconds"] = max(0, (job["remaining"] * settings.MAX_CONCURRENT_FETCHES))
        if job.get("cancelled"):
            job["status"] = "cancelled"
            job["finishedAt"] = datetime.utcnow()
        elif job["remaining"] == 0:
            job["status"] = "completed"
            job["finishedAt"] = datetime.utcnow()
            compute_rankings()
        self._persist_job(job)

        history_repo.create({
            "requestId": job["jobId"],
            "classId": job.get("classId", ""),
            "status": job["status"],
            "processed": processed,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "elapsedSeconds": job.get("elapsedSeconds", 0),
            "remaining": job["remaining"],
            "createdAt": datetime.utcnow(),
        })
        job["results"] = results
        return job

    def run_job(self, job):
        rows = job.get("rows", [])
        job["rows"] = rows
        self._persist_job(job)
        while job.get("status") not in {"completed", "cancelled"}:
            job = self.process_job_step(job["jobId"])
        return job

    def resume_job(self, job_id):
        job = self.get_job(job_id)
        if not job:
            return None
        job.setdefault("rows", [])
        job["cancelled"] = False
        job["status"] = "queued"
        self._persist_job(job)
        return self.process_job_step(job_id)


fetch_engine = FetchEngine()
