import requests
from datetime import datetime
import re


# --------------------------------
# helpers
# --------------------------------

def to_date(ts):
    if not ts:
        return "AB"
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y")


def extract_no(title):
    if not title:
        return "AB"
    m = re.search(r"(\d+)", title)
    return m.group(1) if m else "AB"


def split_by_contest_total(n):
    """
    Your required mapping logic
    """

    if n == 1:
        return 1, 0, 0
    if n == 2:
        return 1, 1, 0
    if n == 3:
        return 1, 2, 0
    if n >= 4:
        return 1, 2, 1   # max contest structure
    return "AB", "AB", "AB"


# --------------------------------
# main
# --------------------------------

def get_lc_summary(sn, name, regno, dept, user):

    query = {
        "query": """
        query($u:String!){
          matchedUser(username:$u){
            profile{ranking}
            submitStats{
              acSubmissionNum{
                difficulty
                count
              }
            }
          }
          userContestRanking(username:$u){
            rating
            topPercentage
          }
          userContestRankingHistory(username:$u){
            contest{title startTime}
            problemsSolved
          }
        }
        """,
        "variables": {"u": user}
    }

    try:
        resp = requests.post(
            "https://leetcode.com/graphql",
            json=query,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        ).json()

        if "data" not in resp:
            return None

        data = resp["data"]

        mu = data.get("matchedUser")
        if not mu:
            return None

        cs = data.get("userContestRanking")
        hist = data.get("userContestRankingHistory") or []

        # -------------------------
        # profile totals
        # -------------------------

        stats = mu["submitStats"]["acSubmissionNum"]
        easy = stats[1]["count"]
        med = stats[2]["count"]
        hard = stats[3]["count"]
        profile_total = easy + med + hard

        # -------------------------
        # last contest
        # -------------------------

        last = next(
            (h for h in reversed(hist) if h and h.get("problemsSolved") is not None),
            None
        )

        if last:
            total = last["problemsSolved"]
            date = to_date(last["contest"]["startTime"])
            contest_no = extract_no(last["contest"]["title"])

            if total and isinstance(total, int):
                lc_easy, lc_med, lc_hard = split_by_contest_total(total)
            else:
                lc_easy = lc_med = lc_hard = "AB"

        else:
            # fallback to profile stats
            total = profile_total
            date = "AB"
            contest_no = "AB"
            lc_easy, lc_med, lc_hard = easy, med, hard

        # -------------------------
        # contest rating + top
        # -------------------------

        rating = round(cs["rating"]) if cs and cs.get("rating") else "AB"
        top = cs.get("topPercentage") if cs else "AB"

        profile = mu.get("profile") or {}
        global_rank = profile.get("ranking", "AB")

        # -------------------------
        # final row
        # -------------------------

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No": regno,
            "Date": date,
            "Leet Code Easy": lc_easy,
            "Leet Code Medium": lc_med,
            "Leet code Hard": lc_hard,
            "Total(No.of Problem Solved)": total,
            "Contest count": contest_no,
            "Contest Rating": rating,
            "Global Rank": global_rank,
            "Top": top
        }

    except Exception as e:
        print("LC error:", e)
        return None
