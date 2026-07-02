from datetime import datetime
import uuid
from bson import ObjectId
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

    def find(self, query=None, sort=None, skip=0, limit=0):
        return list(self.collection.find(query=query or {}, sort=sort, skip=skip, limit=limit))

    def find_one(self, query=None, sort=None):
        return self.collection.find_one(query=query or {}, sort=sort)

    def count(self, query=None):
        return self.collection.count_documents(query or {})

    def delete(self, query):
        return self.collection.delete_many(query)


class ClassRepository(BaseRepository):
    def __init__(self):
        super().__init__("classes")

    def create_class(self, data):
        # Use MongoDB ObjectId as the primary identifier
        payload = {
            "className": (data.get("className") or "").strip(),
            "academicYear": (data.get("academicYear") or data.get("year") or "").strip(),
            "year": (data.get("academicYear") or data.get("year") or "").strip(),
            "department": (data.get("department") or "").strip(),
            "college": (data.get("college") or "").strip(),
            "section": (data.get("section") or "").strip(),
            "description": (data.get("description") or "").strip(),
            "createdBy": (data.get("createdBy") or "").strip(),
            "academicBatch": (data.get("academicBatch") or "").strip(),
            "archived": False,
            "studentCount": 0,
            "totalFetches": 0,
            "lastFetchDate": None,
            "lastUpdated": datetime.utcnow(),
        }
        # Insert and return the document which now contains the generated ObjectId as `_id`
        return self.create(payload)

    def list_classes(self, archived=False, search=""):
        query = {"archived": bool(archived)}
        items = self.find(query=query, sort=[("createdAt", -1)])
        if search:
            s = search.lower()
            items = [
                c for c in items
                if s in (c.get("className", "") or "").lower()
                or s in (c.get("department", "") or "").lower()
                or s in (c.get("college", "") or "").lower()
                or s in (c.get("academicYear", "") or "").lower()
            ]
        return items

    def archive_class(self, class_id):
        return self.update_one({"_id": ObjectId(class_id)}, {"archived": True})

    def restore_class(self, class_id):
        return self.update_one({"_id": ObjectId(class_id)}, {"archived": False})

    def touch_fetch_stats(self, class_id):
        cls = self.find_one({"_id": ObjectId(class_id)})
        total = (cls or {}).get("totalFetches", 0) + 1
        return self.update_one(
            {"_id": ObjectId(class_id)},
            {
                "totalFetches": total,
                "lastFetchDate": datetime.utcnow(),
                "lastUpdated": datetime.utcnow(),
            },
        )

    def refresh_student_count(self, class_id):
        count = store.students.count_documents({"classId": ObjectId(class_id)})
        return self.update_one(
            {"_id": ObjectId(class_id)},
            {"studentCount": count, "lastUpdated": datetime.utcnow()},
        )

    def delete_class_cascade(self, class_id):
        oid = ObjectId(class_id)
        store.students.delete_many({"classId": oid})
        store.platform_stats.delete_many({"classId": oid})
        store.rankings.delete_many({"classId": oid})
        store.fetch_history.delete_many({"classId": oid})
        store.jobs.delete_many({"classId": oid})
        store.import_logs.delete_many({"classId": oid})
        store.classes.delete_many({"_id": oid})


class StudentRepository(BaseRepository):
    def __init__(self):
        super().__init__("students")

    def create_student(self, data):
        student_id = data.get("studentId") or str(uuid.uuid4())
        platform_ids = data.get("platformIds") or {
            "codeforces": data.get("codeforces", ""),
            "codechef": data.get("codechef", ""),
            "leetcode": data.get("leetcode", ""),
        }
        payload = {
            "studentId": student_id,
            "classId": data.get("classId", ""),
            "studentName": data.get("studentName") or data.get("name", ""),
            "registerNo": data.get("registerNo") or data.get("register_no", ""),
            "department": data.get("department", ""),
            "section": data.get("section", ""),
            "email": data.get("email", ""),
            # flat fields kept for compatibility with existing fetch engine
            "codeforces": platform_ids.get("codeforces", ""),
            "codechef": platform_ids.get("codechef", ""),
            "leetcode": platform_ids.get("leetcode", ""),
            "platformIds": platform_ids,
            "profileUrls": data.get("profileUrls", {}),
            "verified": bool(data.get("verified", False)),
            "country": data.get("country", ""),
        }
        return self.create(payload)

    def find_by_class(self, class_id, search="", page=1, page_size=0, sort=None):
        # Ensure class_id is an ObjectId for proper querying
        oid = ObjectId(class_id)
        query = {"classId": oid}
        items = self.find(query=query, sort=sort or [("createdAt", -1)])
        if search:
            s = search.lower()
            items = [
                st for st in items
                if s in (st.get("studentName", "") or "").lower()
                or s in (st.get("registerNo", "") or "").lower()
                or s in (st.get("codeforces", "") or "").lower()
                or s in (st.get("codechef", "") or "").lower()
                or s in (st.get("leetcode", "") or "").lower()
            ]
        total = len(items)
        if page_size:
            start = (max(page, 1) - 1) * page_size
            items = items[start:start + page_size]
        return items, total

    def find_duplicate(self, class_id, register_no="", name=""):
        # Use ObjectId for class lookup
        oid = ObjectId(class_id)
        if register_no:
            found = self.find_one({"classId": oid, "registerNo": register_no})
            if found:
                return found
        if name:
            return self.find_one({"classId": oid, "studentName": name})
        return None


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
                "classId": payload.get("classId", "global"),
                "platform": payload["platform"],
                "period": payload["period"],
                "snapshotKey": payload["snapshotKey"],
            },
            payload,
            upsert=True,
        )


class HistoryRepository(BaseRepository):
    def __init__(self):
        super().__init__("fetch_history")


class ImportLogRepository(BaseRepository):
    def __init__(self):
        super().__init__("import_logs")
