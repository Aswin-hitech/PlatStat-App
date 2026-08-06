import requests
from datetime import datetime
from utils.date_utils import today_ddmmyyyy


def format_contest_date(dt_str):
    """Format YYYY-MM-DD to DD.MM.YYYY"""
    if not dt_str:
        return today_ddmmyyyy()
    parts = dt_str.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return dt_str


def get_latest_cf_contests(limit=6):
    """Fetch the latest finished Codeforces contests with title, id, code, and date."""
    url = "https://codeforces.com/api/contest.list?gym=false"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("status") != "OK":
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
                if len(result) >= limit:
                    break
        return result
    except Exception as e:
        print("Error fetching Codeforces contests:", e)
        return []


def ab_row(sn, name, regno, dept, output_date=None):
    return {
        "S. No": sn,
        "Name of the Student": name,
        "Register No": regno,
        "Dept": dept,
        "Date": output_date or today_ddmmyyyy(),
        "Problem Solved": "AB",
        "Target Contest Solved": "AB",
        "Global Rank": "AB",
        "Current Rating": "AB",
        "Max. Rating": "AB",
        "Max. Ranking": "AB"
    }


def get_cf_summary(sn, name, regno, dept, handle, target_contest_id=None, target_contest_date=None):
    output_date = format_contest_date(target_contest_date) if target_contest_date else today_ddmmyyyy()

    try:
        info = requests.get(
            f"https://codeforces.com/api/user.info?handles={handle}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        ).json()

        if info.get("status") != "OK":
            return ab_row(sn, name, regno, dept, output_date)

        user = info["result"][0]

        subs = requests.get(
            f"https://codeforces.com/api/user.status?handle={handle}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        ).json()

        if subs.get("status") != "OK":
            return ab_row(sn, name, regno, dept, output_date)

        solved = set()
        target_solved = set()

        for s in subs["result"]:
            if s.get("verdict") == "OK" and s.get("author", {}).get("participantType") == "CONTESTANT":
                p = s.get("problem", {})
                cid = p.get("contestId")
                index = p.get("index")
                if cid and index:
                    solved.add((cid, index))
                    if target_contest_id and str(cid) == str(target_contest_id):
                        target_solved.add(index)

        solved_val = len(solved) if solved else "AB"
        target_val = len(target_solved) if target_contest_id else "AB"

        current_rating = user.get("rating", "AB")
        global_rank = user.get("rank", "AB")

        # Historical rating & contest rank extraction
        if target_contest_id:
            try:
                r_rat = requests.get(
                    f"https://codeforces.com/api/user.rating?handle={handle}",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10
                ).json()
                if r_rat.get("status") == "OK":
                    for item in r_rat.get("result", []):
                        if str(item.get("contestId")) == str(target_contest_id):
                            if item.get("newRating") is not None:
                                current_rating = item["newRating"]
                            if item.get("rank") is not None:
                                global_rank = item["rank"]
                            break
            except Exception as rat_err:
                print("CF rating history fetch error:", rat_err)

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No": regno,
            "Dept": dept,
            "Date": output_date,
            "Problem Solved": solved_val,
            "Target Contest Solved": target_val,
            "Global Rank": global_rank,
            "Current Rating": current_rating,
            "Max. Rating": user.get("maxRating", "AB"),
            "Max. Ranking": user.get("maxRank", "AB")
        }

    except Exception as e:
        print("CF error:", e)
        return ab_row(sn, name, regno, dept, output_date)
