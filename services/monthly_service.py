from datetime import datetime

from db import store
from utils.ranking_utils import month_key


def generate_monthly_report():
    current_month = month_key(datetime.utcnow())
    docs = list(store.platform_stats.find({"monthKey": current_month}))
    if not docs:
        return None

    ranked = sorted(docs, key=lambda d: (d.get("growth") or 0, d.get("engagement") or 0), reverse=True)
    winner = ranked[0]
    report = {
        "winner": winner.get("platformName") or winner.get("platformId") or "Unknown",
        "growth": winner.get("growth", 0),
        "stats": winner,
        "generatedAt": datetime.utcnow(),
        "ranking": 1,
    }
    store.monthly_stats.insert_one(report)
    return report
