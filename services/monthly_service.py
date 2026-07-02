from datetime import datetime

from db import store


def generate_monthly_report():
    docs = store.platform_stats.find()
    if not docs:
        return None

    ranked = sorted(docs, key=lambda d: (d.get("growth") or 0, d.get("engagement") or 0), reverse=True)
    winner = ranked[0]
    report = {
        "winner": winner.get("platformName") or winner.get("platformId") or "Unknown",
        "growth": winner.get("growth", 0),
        "stats": winner,
        "date": datetime.utcnow(),
        "ranking": 1,
    }
    store.monthly_stats.insert_one(report)
    return report
