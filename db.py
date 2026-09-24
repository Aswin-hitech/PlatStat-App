import logging
from datetime import datetime
from uuid import uuid4

from config import settings

try:
    from pymongo import ASCENDING, DESCENDING, MongoClient
except Exception:  # pragma: no cover - optional dependency fallback
    ASCENDING = 1
    DESCENDING = -1
    MongoClient = None


logger = logging.getLogger("platstat.mongo")


def _matches(doc, query):
    for key, expected in query.items():
        actual = doc.get(key)
        if isinstance(expected, dict) and any(k.startswith("$") for k in expected):
            for op, op_value in expected.items():
                if op == "$exists":
                    if (key in doc) != bool(op_value):
                        return False
                elif op == "$ne":
                    if actual == op_value:
                        return False
                elif op == "$in":
                    if actual not in op_value:
                        return False
                elif op == "$gt":
                    if not (actual is not None and actual > op_value):
                        return False
                elif op == "$gte":
                    if not (actual is not None and actual >= op_value):
                        return False
                elif op == "$lt":
                    if not (actual is not None and actual < op_value):
                        return False
                elif op == "$lte":
                    if not (actual is not None and actual <= op_value):
                        return False
                # unknown operators are ignored rather than silently failing the match
        elif actual != expected:
            return False
    return True


class MemoryCursor(list):
    def sort(self, sort_spec):
        if sort_spec:
            key, direction = sort_spec[0]
            super().sort(key=lambda d: d.get(key), reverse=direction == DESCENDING)
        return self

    def skip(self, n):
        return MemoryCursor(self[n:])

    def limit(self, n):
        return MemoryCursor(self[:n])

    def count_documents(self, query=None):
        query = query or {}
        return sum(1 for doc in self if _matches(doc, query))


class InsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class MemoryCollection:
    def __init__(self, name="memory"):
        self.name = name
        self._docs = []

    def insert_one(self, doc):
        payload = doc.copy()
        if "_id" not in payload:
            try:
                from bson import ObjectId
                payload["_id"] = ObjectId()
            except Exception:
                payload["_id"] = str(uuid4())
        self._docs.append(payload)
        return InsertOneResult(payload["_id"])

    def insert_many(self, docs):
        for doc in docs:
            self.insert_one(doc)

    def find(self, query=None, projection=None, sort=None, skip=0, limit=0):
        query = query or {}
        results = [doc.copy() for doc in self._docs if _matches(doc, query)]
        if sort:
            key, direction = sort[0]
            results.sort(key=lambda d: d.get(key), reverse=direction == DESCENDING)
        if skip:
            results = results[skip:]
        if limit:
            results = results[:limit]
        return MemoryCursor(results)

    def find_one(self, query=None, projection=None, sort=None):
        found = self.find(query=query, projection=projection, sort=sort, limit=1)
        return found[0] if found else None

    def count_documents(self, query=None):
        return len(self.find(query=query))

    def delete_many(self, query=None):
        query = query or {}
        kept = []
        removed = 0
        for doc in self._docs:
            if _matches(doc, query):
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


try:
    from pymongo.errors import PyMongoError
except Exception:
    PyMongoError = Exception


class MongoCollectionAdapter:
    def __init__(self, collection):
        self.collection = collection
        self.memory = MemoryCollection(collection.name)

    def insert_one(self, doc):
        try:
            res = self.collection.insert_one(doc)
            try:
                self.memory.insert_one(doc)
            except Exception:
                pass
            return res
        except PyMongoError as err:
            logger.warning("MongoDB error in insert_one (%s), falling back to memory.", err)
            return self.memory.insert_one(doc)

    def insert_many(self, docs):
        try:
            res = self.collection.insert_many(docs)
            try:
                self.memory.insert_many(docs)
            except Exception:
                pass
            return res
        except PyMongoError as err:
            logger.warning("MongoDB error in insert_many (%s), falling back to memory.", err)
            return self.memory.insert_many(docs)

    def find(self, query=None, projection=None, sort=None, skip=0, limit=0):
        try:
            cursor = self.collection.find(query or {}, projection)
            if sort:
                cursor = cursor.sort(sort)
            if skip:
                cursor = cursor.skip(skip)
            if limit:
                cursor = cursor.limit(limit)
            return cursor
        except PyMongoError as err:
            logger.warning("MongoDB error in find (%s), falling back to memory.", err)
            return self.memory.find(query=query, projection=projection, sort=sort, skip=skip, limit=limit)

    def find_one(self, query=None, projection=None, sort=None):
        try:
            cursor = self.find(query=query, projection=projection, sort=sort, limit=1)
            return next(iter(cursor), None)
        except PyMongoError as err:
            logger.warning("MongoDB error in find_one (%s), falling back to memory.", err)
            return self.memory.find_one(query=query, projection=projection, sort=sort)

    def count_documents(self, query=None):
        try:
            return self.collection.count_documents(query or {})
        except PyMongoError as err:
            logger.warning("MongoDB error in count_documents (%s), falling back to memory.", err)
            return self.memory.count_documents(query or {})

    def delete_many(self, query=None):
        try:
            self.memory.delete_many(query or {})
            return self.collection.delete_many(query or {})
        except PyMongoError as err:
            logger.warning("MongoDB error in delete_many (%s), falling back to memory.", err)
            return self.memory.delete_many(query or {})

    def update_one(self, query, update, upsert=False):
        try:
            self.memory.update_one(query, update, upsert=upsert)
            return self.collection.update_one(query, update, upsert=upsert)
        except PyMongoError as err:
            logger.warning("MongoDB error in update_one (%s), falling back to memory.", err)
            return self.memory.update_one(query, update, upsert=upsert)

    def aggregate(self, pipeline):
        try:
            return self.collection.aggregate(pipeline)
        except PyMongoError as err:
            logger.warning("MongoDB error in aggregate (%s), falling back to memory.", err)
            return self.memory.aggregate(pipeline)

    def create_index(self, *args, **kwargs):
        try:
            return self.collection.create_index(*args, **kwargs)
        except Exception:
            return None


class MongoStore:
    COLLECTION_NAMES = {
        "users",
        "classes",
        "students",
        "platform_stats",
        "rankings",
        "monthly_stats",
        "weekly_stats",
        "yearly_stats",
        "contest_stats",
        "fetch_history",
        "jobs",
        "fetch_logs",
        "import_logs",
        "contests",
        "reminders",
        "notifications",
        "contest_sync_state",
    }


    def __init__(self):
        self.enabled = False
        self.client = None
        self.db = None
        self._collections = {}
        self._connect_attempted = False

    def _validate_uri(self, uri):
        if not uri or not (uri.startswith("mongodb://") or uri.startswith("mongodb+srv://")):
            raise ValueError("Invalid MONGODB_URI. Expected mongodb:// or mongodb+srv://")
        return uri

    def _connect(self):
        if self.enabled:
            return
        if self._connect_attempted:
            return
        self._connect_attempted = True

        if not settings.MONGO_URI or not settings.MONGO_URI.strip():
            logger.info("No MONGODB_URI configured; using high-performance in-memory store.")
            return

        if not MongoClient:
            logger.warning("pymongo not installed; using in-memory fallback")
            return

        try:
            uri = self._validate_uri(settings.MONGO_URI.strip())
            logger.info("Connecting to MongoDB...")
            client = MongoClient(
                uri,
                serverSelectionTimeoutMS=2500,
                connectTimeoutMS=2500,
                socketTimeoutMS=2500,
            )
            client.admin.command("ping")
            self.client = client
            self.db = client[settings.MONGO_DB]
            self.enabled = True
            logger.info("MongoDB connection established successfully.")
        except Exception as exc:
            logger.warning("MongoDB unavailable (%s); falling back to in-memory store.", exc)
            self.enabled = False

    def _collection(self, name):
        if name in self._collections:
            return self._collections[name]
        try:
            self._connect()
        except Exception as exc:
            logger.warning("MongoDB connect error for %s: %s", name, exc)
            collection = MemoryCollection(name)
            self._collections[name] = collection
            return collection
        collection = MongoCollectionAdapter(self.db[name]) if self.enabled else MemoryCollection(name)
        self._collections[name] = collection
        return collection

    def collection(self, name):
        return self._collection(name)

    def __getattr__(self, item):
        if item in self.COLLECTION_NAMES:
            return self._collection(item)
        raise AttributeError(item)

    def ensure_indexes(self):
        if not self.enabled:
            return
        try:
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
            self.contests.create_index([("startTime", ASCENDING)])
            self.contests.create_index([("platform", ASCENDING)])
            self.contests.create_index([("externalId", ASCENDING)])
            self.contests.create_index([("platform", ASCENDING), ("externalId", ASCENDING)], unique=True)
            self.reminders.create_index([("userId", ASCENDING)])
            self.reminders.create_index([("contestId", ASCENDING)])
            self.reminders.create_index([("userId", ASCENDING), ("contestId", ASCENDING)], unique=True)
            self.notifications.create_index([("userId", ASCENDING)])
            self.notifications.create_index([("read", ASCENDING)])
            self.notifications.create_index([("createdAt", DESCENDING)])
        except Exception as idx_err:
            logger.warning("Index creation issue: %s", idx_err)


class StoreProxy:
    def __init__(self):
        self._store = MongoStore()
        self._initialized = False

    def _ensure(self):
        if not self._initialized:
            self._initialized = True
            try:
                self._store._connect()
                if self._store.enabled:
                    self._store.ensure_indexes()
            except Exception as exc:
                logger.warning("Store initialization error: %s", exc)

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        self._ensure()
        return getattr(self._store, item)

    def collection(self, name):
        self._ensure()
        return self._store.collection(name)


store = StoreProxy()

