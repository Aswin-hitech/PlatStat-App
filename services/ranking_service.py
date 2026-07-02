from collections import defaultdict
from datetime import datetime

from db import store
from utils.ranking_utils import month_key, safe_number, week_key, year_key


PLATFORM_CRITERIA = {
    "codeforces": [
        ("Current Rating", True),
        ("Problem Solved", True),
        ("Global Rank", False),
    ],
    "codechef": [
        ("Current Rating", True),
        ("Star Rating", True),
        ("Highest Rating", True),
        ("Global ranking", False),
    ],
    "leetcode": [
        ("Contest Rating", True),
        ("Total(No.of Problem Solved)", True),
        ("Global Rank", False),
        ("Top", False),
    ],
}


def _value(doc, field):
    value = doc.get(field)
    if value in [None, "", "AB", "-"]:
        return 0
    return safe_number(value)


def _sort_key(doc, criteria):
    key_parts = []
    for field, descending in criteria:
        value = _value(doc, field)
        key_parts.append(-value if descending else value)
    return tuple(key_parts)


def _snapshot_key(period, reference_date, platform):
    if period == "weekly":
        return f"{platform}:{week_key(reference_date)}"
    if period == "monthly":
        return f"{platform}:{month_key(reference_date)}"
    if period == "yearly":
        return f"{platform}:{year_key(reference_date)}"
    if period == "contest":
        contest = reference_date.strftime("%Y-%m-%d")
        return f"{platform}:{contest}"
    return f"{platform}:{reference_date.strftime('%Y-%m-%dT%H:%M:%S')}"


def _dedupe_latest(docs):
    latest = {}
    for doc in docs:
        key = (
            doc.get("classId", ""),
            doc.get("studentId", "") or doc.get("studentName", ""),
            doc.get("platform", ""),
            doc.get("platformId", ""),
        )
        current = latest.get(key)
        fetch_date = doc.get("fetchDate") or doc.get("createdAt") or datetime.utcnow()
        if not current:
            latest[key] = doc
            continue
        current_date = current.get("fetchDate") or current.get("createdAt") or datetime.utcnow()
        if fetch_date >= current_date:
            latest[key] = doc
    return list(latest.values())


def _period_docs(docs, period, reference_date):
    if period == "overall":
        return docs
    if period == "weekly":
        key = week_key(reference_date)
        return [d for d in docs if week_key(d.get("fetchDate") or d.get("createdAt")) == key]
    if period == "monthly":
        key = month_key(reference_date)
        return [d for d in docs if month_key(d.get("fetchDate") or d.get("createdAt")) == key]
    if period == "yearly":
        key = year_key(reference_date)
        return [d for d in docs if year_key(d.get("fetchDate") or d.get("createdAt")) == key]
    if period == "contest":
        contest = reference_date.strftime("%Y-%m-%d")
        return [d for d in docs if str(d.get("contest", "")).startswith(contest)]
    return docs


def _build_snapshot(platform, period, reference_date, docs):
    criteria = PLATFORM_CRITERIA.get(platform, [])
    ranked = sorted(docs, key=lambda d: _sort_key(d, criteria))
    snapshot = {
        "platform": platform,
        "period": period,
        "rankingType": f"{period.title()} Rankings",
        "criteria": [field for field, _ in criteria],
        "snapshotKey": _snapshot_key(period, reference_date, platform),
        "generatedAt": datetime.utcnow(),
        "top5": ranked[:5],
        "top10": ranked[:10],
        "count": len(ranked),
    }
    store.rankings.insert_one(snapshot)
    return snapshot


def _store_period_summary(period, reference_date, docs):
    snapshot = {
        "period": period,
        "snapshotKey": _snapshot_key(period, reference_date, "summary"),
        "generatedAt": datetime.utcnow(),
        "winner": docs[0] if docs else None,
        "top5": docs[:5],
        "top10": docs[:10],
        "count": len(docs),
    }
    collection = {
        "weekly": store.weekly_stats,
        "monthly": store.monthly_stats,
        "yearly": store.yearly_stats,
        "contest": store.contest_stats,
    }.get(period)
    if collection:
        collection.insert_one(snapshot)
    return snapshot


def compute_rankings(reference_date=None):
    reference_date = reference_date or datetime.utcnow()
    all_docs = list(store.platform_stats.find())
    grouped = defaultdict(list)
    for doc in _dedupe_latest(all_docs):
        grouped[doc.get("platform", "")].append(doc)

    snapshots = {}
    for platform, docs in grouped.items():
        snapshots[platform] = {}
        for period in ("overall", "weekly", "monthly", "yearly", "contest"):
            filtered = _period_docs(docs, period, reference_date)
            snapshots[platform][period] = _build_snapshot(platform, period, reference_date, filtered)

    # keep summary toppers per period for dashboard cards
    ranked_overall = sorted(
        _dedupe_latest(all_docs),
        key=lambda d: _sort_key(d, PLATFORM_CRITERIA.get(d.get("platform", ""), [])),
    )
    _store_period_summary("weekly", reference_date, ranked_overall)
    _store_period_summary("monthly", reference_date, ranked_overall)
    _store_period_summary("yearly", reference_date, ranked_overall)
    _store_period_summary("contest", reference_date, ranked_overall)
    return snapshots
