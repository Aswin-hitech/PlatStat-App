from datetime import datetime

from config import settings

try:
    from pymongo import MongoClient, ASCENDING, DESCENDING
except Exception:  # pragma: no cover - optional dependency fallback
    MongoClient = None
    ASCENDING = 1
    DESCENDING = -1


class MemoryCollection:
    def __init__(self):
        self._docs = []

    def insert_one(self, doc):
        self._docs.append(doc.copy())
        return doc

    def insert_many(self, docs):
        for doc in docs:
            self.insert_one(doc)

    def find(self, query=None, sort=None, limit=0):
        query = query or {}
        results = [doc for doc in self._docs if all(doc.get(k) == v for k, v in query.items())]
        if sort:
            key, direction = sort[0]
            results.sort(key=lambda d: d.get(key), reverse=direction == DESCENDING)
        if limit:
            results = results[:limit]
        return results

    def find_one(self, query=None, sort=None):
        found = self.find(query=query, sort=sort, limit=1)
        return found[0] if found else None

    def delete_many(self, query=None):
        query = query or {}
        kept = []
        removed = 0
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                removed += 1
            else:
                kept.append(doc)
        self._docs = kept
        return removed

    def update_one(self, query, update, upsert=False):
        doc = self.find_one(query)
        if doc:
            for k, v in update.get("$set", {}).items():
                doc[k] = v
            for k, v in update.get("$setOnInsert", {}).items():
                doc.setdefault(k, v)
            return doc
        if upsert:
            new_doc = dict(query)
            new_doc.update(update.get("$setOnInsert", {}))
            new_doc.update(update.get("$set", {}))
            self.insert_one(new_doc)
            return new_doc
        return None

    def aggregate(self, pipeline):
        return list(self._docs)

    def create_index(self, *args, **kwargs):
        return None


class MongoStore:
    def __init__(self):
        self.enabled = False
        self.client = None
        self.db = None
        if settings.MONGO_URI and MongoClient:
            self.client = MongoClient(settings.MONGO_URI)
            self.db = self.client[settings.MONGO_DB]
            self.enabled = True
        else:
            self.db = None

        self.users = self._collection("users")
        self.classes = self._collection("classes")
        self.students = self._collection("students")
        self.platform_stats = self._collection("platform_stats")
        self.contest_stats = self._collection("contest_stats")
        self.weekly_stats = self._collection("weekly_stats")
        self.yearly_stats = self._collection("yearly_stats")
        self.monthly_stats = self._collection("monthly_stats")
        self.fetch_history = self._collection("fetch_history")
        self.jobs = self._collection("jobs")
        self.fetch_logs = self._collection("fetch_logs")
        self.rankings = self._collection("rankings")

    def _collection(self, name):
        return self.db[name] if self.enabled else MemoryCollection()

    def ensure_indexes(self):
        if not self.enabled:
            return
        self.classes.create_index([("classId", ASCENDING)], unique=True)
        self.classes.create_index([("college", ASCENDING), ("department", ASCENDING)])
        self.students.create_index([("studentId", ASCENDING)], unique=True)
        self.students.create_index([("classId", ASCENDING), ("studentName", ASCENDING)])
        self.students.create_index([("classId", ASCENDING), ("platformId", ASCENDING)])

        self.platform_stats.create_index([("platformId", ASCENDING), ("platform", ASCENDING), ("fetchDate", DESCENDING)])
        self.platform_stats.create_index([("classId", ASCENDING), ("fetchDate", DESCENDING)])
        self.platform_stats.create_index([("platformName", ASCENDING), ("fetchDate", DESCENDING)])
        self.platform_stats.create_index([("rankingPeriod", ASCENDING), ("fetchDate", DESCENDING)])
        self.platform_stats.create_index([("contest", ASCENDING), ("fetchDate", DESCENDING)])

        self.contest_stats.create_index([("contest", ASCENDING), ("fetchDate", DESCENDING)])
        self.weekly_stats.create_index([("weekKey", ASCENDING)], unique=True)
        self.monthly_stats.create_index([("monthKey", ASCENDING)], unique=True)
        self.yearly_stats.create_index([("yearKey", ASCENDING)], unique=True)

        self.fetch_history.create_index([("requestId", ASCENDING)], unique=True)
        self.fetch_history.create_index([("classId", ASCENDING), ("createdAt", DESCENDING)])
        self.jobs.create_index([("jobId", ASCENDING)], unique=True)
        self.jobs.create_index([("status", ASCENDING), ("updatedAt", DESCENDING)])
        self.rankings.create_index([("metric", ASCENDING), ("period", ASCENDING), ("snapshotKey", ASCENDING)], unique=True)

    def now(self):
        return datetime.utcnow()


store = MongoStore()
store.ensure_indexes()
