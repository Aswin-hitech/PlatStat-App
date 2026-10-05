import time
import requests
import re
from datetime import datetime
from utils.date_utils import today_ddmmyyyy


def format_contest_date(dt_str):
    """Format YYYY-MM-DD to DD.MM.YYYY"""
    if not dt_str:
        return today_ddmmyyyy()
    parts = str(dt_str).strip().split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return str(dt_str)


_CF_CONTESTS_CACHE = {"data": None, "timestamp": 0}
_CF_CACHE_TTL_SECONDS = 300
_CF_USER_CACHE = {}       # handle.lower() -> (timestamp, dict or None)
_CF_STATUS_CACHE = {}     # handle.lower() -> (timestamp, list of subs)
_CF_RATING_CACHE = {}     # handle.lower() -> (timestamp, list of rating events)
_CF_SESSION = requests.Session()
_CF_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
_LAST_REQUEST_TIME = 0.0


def _safe_cf_get(url, timeout=8, max_retries=3):
    """Safely make a GET request to Codeforces API with pacing and exponential backoff retry."""
    global _LAST_REQUEST_TIME
    for attempt in range(max_retries):
        elapsed = time.time() - _LAST_REQUEST_TIME
        if elapsed < 0.22:
            time.sleep(0.22 - elapsed)
        _LAST_REQUEST_TIME = time.time()
        try:
            r = _CF_SESSION.get(url, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "OK":
                    return data
                return None
            elif r.status_code == 429:
                time.sleep(1.5 + attempt * 1.0)
                continue
            elif r.status_code == 404:
                return None
        except Exception:
            if attempt == max_retries - 1:
                return None
            time.sleep(0.5)
    return None


def get_latest_cf_contests(limit=15):
    """Fetch the latest finished Codeforces contests with title, id, code, and date (5-min caching)."""
    now = int(time.time())
    if _CF_CONTESTS_CACHE["data"] and (now - _CF_CONTESTS_CACHE["timestamp"] < _CF_CACHE_TTL_SECONDS):
        return _CF_CONTESTS_CACHE["data"][:limit]

    url = "https://codeforces.com/api/contest.list?gym=false"
    data = _safe_cf_get(url, timeout=10)
    if not data:
        if _CF_CONTESTS_CACHE["data"]:
            return _CF_CONTESTS_CACHE["data"][:limit]
        return []

    finished = [c for c in data.get("result", []) if c.get("phase") == "FINISHED"]
    result = []
    for c in finished:
        st = c.get("startTimeSeconds")
        dt_str = datetime.fromtimestamp(st).strftime("%Y-%m-%d") if st else ""
        name = c.get("name") or ""
        cid = c.get("id")
        if name and cid:
            result.append({
                "title": name,
                "id": cid,
                "code": str(cid),
                "date": dt_str
            })
            if len(result) >= max(limit, 60):
                break

    _CF_CONTESTS_CACHE["data"] = result
    _CF_CONTESTS_CACHE["timestamp"] = now
    return result[:limit]


def resolve_cf_contest(identifier):
    """Resolve a contest title, round number, or contest ID to (contest_id, title, date)."""
    if not identifier:
        return None, None, None
    id_str = str(identifier).strip()
    contests = get_latest_cf_contests(60)

    # 1. Exact numeric contest ID match
    for c in contests:
        if str(c.get("id")) == id_str or str(c.get("code")) == id_str:
            return c["id"], c["title"], c.get("date")

    # 2. Exact title match (case-insensitive)
    for c in contests:
        if c.get("title", "").strip().lower() == id_str.lower():
            return c["id"], c["title"], c.get("date")

    # 3. Round number / division match (e.g., '1123', 'div 2 1123', 'Round 1123')
    round_match = re.search(r"round\s*(\d+)", id_str, re.I)
    if round_match:
        round_num = round_match.group(1)
    else:
        all_nums = re.findall(r"\b\d+\b", id_str)
        large_nums = [n for n in all_nums if int(n) >= 10]
        round_num = large_nums[0] if large_nums else (all_nums[0] if all_nums else None)

    if round_num:
        is_div2 = bool(re.search(r"div\.?\s*2", id_str, re.I))
        is_div3 = bool(re.search(r"div\.?\s*3", id_str, re.I))
        is_div1 = bool(re.search(r"div\.?\s*1", id_str, re.I))

        candidates = [
            c for c in contests
            if f"Round {round_num}" in c.get("title", "")
            or f"#{round_num}" in c.get("title", "")
            or f" {round_num} " in f" {c.get('title', '')} "
            or c.get("title", "").endswith(f" {round_num}")
        ]

        if candidates:
            if is_div2:
                for c in candidates:
                    if "div. 2" in c.get("title", "").lower() or "div 2" in c.get("title", "").lower():
                        return c["id"], c["title"], c.get("date")
            if is_div3:
                for c in candidates:
                    if "div. 3" in c.get("title", "").lower() or "div 3" in c.get("title", "").lower():
                        return c["id"], c["title"], c.get("date")
            if is_div1:
                for c in candidates:
                    if "div. 1" in c.get("title", "").lower() or "div 1" in c.get("title", "").lower():
                        return c["id"], c["title"], c.get("date")
            return candidates[0]["id"], candidates[0]["title"], candidates[0].get("date")

    if id_str.isdigit():
        return int(id_str), id_str, None

    return None, id_str, None


def prefetch_cf_users(handles):
    """Batch fetch multiple user profiles in 1 request to avoid overloading Codeforces."""
    clean_handles = list(dict.fromkeys([h.strip() for h in handles if h and h.strip()]))
    if not clean_handles:
        return

    now = time.time()
    needed = [
        h for h in clean_handles
        if h.lower() not in _CF_USER_CACHE
        or (now - _CF_USER_CACHE[h.lower()][0] >= _CF_CACHE_TTL_SECONDS)
    ]
    if not needed:
        return

    # Chunk into 50 handles per API request
    chunk_size = 50
    for i in range(0, len(needed), chunk_size):
        chunk = needed[i:i + chunk_size]
        url = f"https://codeforces.com/api/user.info?handles={';'.join(chunk)}"
        data = _safe_cf_get(url, timeout=10)
        if data and data.get("result"):
            for u in data["result"]:
                h_name = u.get("handle", "")
                if h_name:
                    _CF_USER_CACHE[h_name.lower()] = (now, u)
        else:
            # Fallback to individual requests if a malformed/missing handle failed the batch
            for h in chunk:
                single_url = f"https://codeforces.com/api/user.info?handles={h}"
                s_data = _safe_cf_get(single_url, timeout=6)
                if s_data and s_data.get("result"):
                    _CF_USER_CACHE[h.lower()] = (now, s_data["result"][0])
                else:
                    _CF_USER_CACHE[h.lower()] = (now, None)


def ab_row(sn, name, regno, dept, output_date=None, target_contest_title=None):
    return {
        "S. No": sn,
        "Name of the Student": name,
        "Register No": regno,
        "Dept": dept,
        "Target Contest": target_contest_title or "N/A",
        "Date": format_contest_date(output_date) if output_date else today_ddmmyyyy(),
        "Problem Solved": "AB",
        "Target Contest Solved": "AB",
        "Global Rank": "AB",
        "Current Rating": "AB",
        "Max. Rating": "AB",
        "Max. Ranking": "AB"
    }


def get_cf_summary(sn, name, regno, dept, handle, target_contest_id=None, target_contest_date=None, target_contest_title=None):
    clean_handle = (handle or "").strip()
    if not clean_handle:
        return ab_row(sn, name, regno, dept, target_contest_date, target_contest_title)

    resolved_id = target_contest_id
    resolved_title = target_contest_title
    resolved_date = target_contest_date

    # Automatically resolve contest if identifier / string given
    if target_contest_id or target_contest_title:
        identifier = target_contest_id or target_contest_title
        c_id, c_title, c_dt = resolve_cf_contest(identifier)
        if c_id:
            resolved_id = c_id
            resolved_title = resolved_title or c_title
            resolved_date = resolved_date or c_dt

    output_date = format_contest_date(resolved_date) if resolved_date else today_ddmmyyyy()
    c_title = resolved_title or (str(resolved_id) if resolved_id else "N/A")

    try:
        now = time.time()

        # 1. User Info (cached or batch-prefetched)
        h_key = clean_handle.lower()
        cached_user = _CF_USER_CACHE.get(h_key)
        if cached_user and (now - cached_user[0] < _CF_CACHE_TTL_SECONDS):
            user = cached_user[1]
        else:
            data = _safe_cf_get(f"https://codeforces.com/api/user.info?handles={clean_handle}", timeout=8)
            user = data["result"][0] if data and data.get("result") else None
            _CF_USER_CACHE[h_key] = (now, user)

        if not user:
            return ab_row(sn, name, regno, dept, output_date, c_title)

        # 2. Submissions
        cached_subs = _CF_STATUS_CACHE.get(h_key)
        if cached_subs and (now - cached_subs[0] < _CF_CACHE_TTL_SECONDS):
            subs_result = cached_subs[1]
        else:
            subs_data = _safe_cf_get(f"https://codeforces.com/api/user.status?handle={clean_handle}", timeout=10)
            subs_result = subs_data.get("result", []) if subs_data else []
            _CF_STATUS_CACHE[h_key] = (now, subs_result)

        solved = set()
        target_solved = set()
        participated_in_target = False

        for s in subs_result:
            if s.get("verdict") == "OK":
                p = s.get("problem", {})
                cid = p.get("contestId")
                index = p.get("index")
                if cid and index:
                    solved.add((cid, index))
                    if resolved_id and str(cid) == str(resolved_id):
                        target_solved.add(index)
                        participated_in_target = True

        solved_val = len(solved) if solved else "AB"
        current_rating = user.get("rating", "AB")
        global_rank = "AB" if resolved_id else user.get("rank", "AB")
        target_val = "AB"

        # 3. Rating History
        if resolved_id:
            cached_rat = _CF_RATING_CACHE.get(h_key)
            if cached_rat and (now - cached_rat[0] < _CF_CACHE_TTL_SECONDS):
                rat_result = cached_rat[1]
            else:
                rat_data = _safe_cf_get(f"https://codeforces.com/api/user.rating?handle={clean_handle}", timeout=8)
                rat_result = rat_data.get("result", []) if rat_data else []
                _CF_RATING_CACHE[h_key] = (now, rat_result)

            for item in rat_result:
                if str(item.get("contestId")) == str(resolved_id):
                    participated_in_target = True
                    if item.get("newRating") is not None:
                        current_rating = item["newRating"]
                    if item.get("rank") is not None:
                        global_rank = item["rank"]
                    break

            if participated_in_target:
                target_val = len(target_solved)
            else:
                target_val = "AB"
                global_rank = "AB"

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No": regno,
            "Dept": dept,
            "Target Contest": c_title,
            "Date": output_date,
            "Problem Solved": solved_val,
            "Target Contest Solved": target_val,
            "Global Rank": global_rank,
            "Current Rating": current_rating,
            "Max. Rating": user.get("maxRating", "AB"),
            "Max. Ranking": user.get("maxRank", "AB")
        }

    except Exception as e:
        print(f"[codeforces] extraction error for '{clean_handle}': {e}")
        return ab_row(sn, name, regno, dept, output_date, c_title)
