import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    MONGO_URI = os.getenv("MONGODB_URI", os.getenv("MONGO_URI", ""))
    MONGO_DB = os.getenv("MONGO_DB", "platstat")
    MAX_CONCURRENT_FETCHES = int(os.getenv("MAX_CONCURRENT_FETCHES", "15"))
    FETCH_RETRIES = int(os.getenv("FETCH_RETRIES", "3"))
    FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "20"))
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", "15"))


settings = Settings()
