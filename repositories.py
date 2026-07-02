from datetime import datetime
import uuid

from db import store


class BaseRepository:
    def __init__(self, collection_name):
        self.collection_name = collection_name

    @property
    def collection(self):
        return store.collection(self.collection_name)

    def create(self, doc):
        now = datetime.utcnow()
        payload = {**doc, "createdAt": doc.get("createdAt", now), "updatedAt": now}
        self.collection.insert_one(payload)
        return payload

    def update_one(self, query, payload, upsert=False):
        payload = {**payload, "updatedAt": datetime.utcnow()}
        return self.collection.update_one(query, {"$set": payload}, upsert=upsert)

    def find(self, query=None, sort=None, limit=0):
        return self.collection.find(query=query or {}, sort=sort, limit=limit)

    def find_one(self, query=None, sort=None):
        return self.collection.find_one(query=query or {}, sort=sort)


class ClassRepository(BaseRepository):
    def __init__(self):
        super().__init__("classes")

    def create_class(self, data):
        class_id = data.get("classId") or str(uuid.uuid4())
        payload = {
            "classId": class_id,
            "className": data.get("className", ""),
            "year": data.get("year", ""),
            "college": data.get("college", ""),
            "department": data.get("department", ""),
            "section": data.get("section", ""),
            "academicYear": data.get("academicYear", ""),
            "description": data.get("description", ""),
        }
        return self.create(payload)


class StudentRepository(BaseRepository):
    def __init__(self):
        super().__init__("students")

    def create_student(self, data):
        student_id = data.get("studentId") or str(uuid.uuid4())
        payload = {
            "studentId": student_id,
            "classId": data.get("classId", ""),
            "studentName": data.get("studentName", ""),
            "registerNo": data.get("registerNo", ""),
            "platformIds": data.get("platformIds", {}),
            "profileUrls": data.get("profileUrls", {}),
            "verified": bool(data.get("verified", False)),
            "country": data.get("country", ""),
        }
        return self.create(payload)


class JobRepository(BaseRepository):
    def __init__(self):
        super().__init__("jobs")

    def create_job(self, data):
        job_id = data.get("jobId") or str(uuid.uuid4())
        payload = {
            "jobId": job_id,
            "classId": data.get("classId", ""),
            "status": data.get("status", "queued"),
            "total": data.get("total", 0),
            "processed": 0,
            "success": 0,
            "failed": 0,
            "remaining": data.get("total", 0),
            "retries": 0,
            "cancelled": False,
            "currentStudent": "",
            "currentPlatformId": "",
            "startedAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        }
        return self.create(payload)


class StatRepository(BaseRepository):
    def __init__(self):
        super().__init__("platform_stats")

    def append_snapshot(self, payload):
        payload.setdefault("fetchDate", datetime.utcnow())
        payload.setdefault("status", "success")
        payload.setdefault("rawResponse", None)
        payload.setdefault("source", "scraper")
        return self.create(payload)


class RankingRepository(BaseRepository):
    def __init__(self):
        super().__init__("rankings")

    def upsert_snapshot(self, payload):
        return self.update_one(
            {
                "metric": payload["metric"],
                "period": payload["period"],
                "snapshotKey": payload["snapshotKey"],
            },
            payload,
            upsert=True,
        )


class HistoryRepository(BaseRepository):
    def __init__(self):
        super().__init__("fetch_history")
