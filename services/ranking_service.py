from datetime import datetime

from repositories import RankingRepository, StatRepository
from db import store
from utils.ranking_utils import month_key, safe_number, week_key, year_key


ranking_repo = RankingRepository()
stat_repo = StatRepository()


def _metric_value(doc, metric):
    return safe_number(doc.get(metric))


def _store_period_rankings(docs, metric, period, snapshot_key, top_n=(5, 10)):
    ordered = sorted(docs, key=lambda d: _metric_value(d, metric), reverse=True)
    payload = {
        "metric": metric,
        "period": period,
        "snapshotKey": snapshot_key,
        "generatedAt": datetime.utcnow(),
        "top5": ordered[: top_n[0]],
        "top10": ordered[: top_n[1]],
    }
    ranking_repo.upsert_snapshot(payload)
    period_payload = {
        "metric": metric,
        "period": period,
        "snapshotKey": snapshot_key,
        "generatedAt": datetime.utcnow(),
        "top5": ordered[: top_n[0]],
        "top10": ordered[: top_n[1]],
    }
    if period == "weekly":
        store.weekly_stats.update_one({"weekKey": snapshot_key}, {"$set": {"weekKey": snapshot_key, "metric": metric, **period_payload}}, upsert=True)
    elif period == "monthly":
        store.monthly_stats.update_one({"monthKey": snapshot_key}, {"$set": {"monthKey": snapshot_key, "metric": metric, **period_payload}}, upsert=True)
    elif period == "yearly":
        store.yearly_stats.update_one({"yearKey": snapshot_key}, {"$set": {"yearKey": snapshot_key, "metric": metric, **period_payload}}, upsert=True)
    return payload


def compute_rankings(reference_date=None):
    docs = stat_repo.find()
    reference_date = reference_date or datetime.utcnow()
    metric_names = ["followers", "likes", "views", "engagement", "growth"]
    snapshots = {}
    for metric in metric_names:
        snapshots[metric] = {
            "overall": _store_period_rankings(docs, metric, "overall", "overall"),
            "weekly": _store_period_rankings(
                [d for d in docs if week_key(d.get("fetchDate")) == week_key(reference_date)],
                metric,
                "weekly",
                week_key(reference_date),
            ),
            "monthly": _store_period_rankings(
                [d for d in docs if month_key(d.get("fetchDate")) == month_key(reference_date)],
                metric,
                "monthly",
                month_key(reference_date),
            ),
            "yearly": _store_period_rankings(
                [d for d in docs if year_key(d.get("fetchDate")) == year_key(reference_date)],
                metric,
                "yearly",
                year_key(reference_date),
            ),
        }
    return snapshots
