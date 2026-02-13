import requests
from datetime import datetime


def epoch_to_ddmmyyyy(ts):
    if not ts:
        return "AB"
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y")


def get_lc_summary(sn, name, regno, dept, user):

    url = "https://leetcode.com/graphql"

    query = {
        "query": """
        query getUser($username: String!) {

          matchedUser(username: $username) {
            profile {
              ranking
            }
          }

          userContestRanking(username: $username) {
            rating
            attendedContestsCount
            topPercentage
          }

          userContestRankingHistory(username: $username) {
            contest {
              title
              startTime
            }
            problemsSolved
            ranking
          }
        }
        """,
        "variables": {"username": user}
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://leetcode.com/{user}/"
    }

    try:
        resp = requests.post(url, json=query, headers=headers, timeout=15)
        data = resp.json()

        if "data" not in data or not data["data"]:
            print("LC error:", data)
            return ab_row(sn, name, regno, dept)

        mu = data["data"].get("matchedUser")
        if not mu:
            print("LC user not found:", user)
            return ab_row(sn, name, regno, dept)

        contest_summary = data["data"].get("userContestRanking") or {}
        history = data["data"].get("userContestRankingHistory") or []

        # ---------- Contest Summary ----------
        contest_rating = contest_summary.get("rating")
        top_pct = contest_summary.get("topPercentage")

        if contest_rating is not None:
            contest_rating = round(contest_rating, 2)
        else:
            contest_rating = "AB"

        if top_pct is None:
            top_pct = "AB"

        # ---------- Latest Contest ----------
        contest_name = "AB"
        contest_date = "AB"
        contest_solved = "AB"

        for entry in reversed(history):
            if not entry:
                continue
            if entry.get("problemsSolved") is None:
                continue

            contest_name = entry["contest"]["title"]
            contest_date = epoch_to_ddmmyyyy(entry["contest"]["startTime"])
            contest_solved = entry["problemsSolved"]
            break

        if contest_solved == 0:
            contest_solved = "AB"

        # ---------- Global Rank ----------
        global_rank = mu["profile"].get("ranking", "AB")

        # ---------- Return Row (NEW FORMAT) ----------
        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No.": regno,
            "Dept": dept,
            "Date": contest_date,

            # contest-only difficulty split not available → AB
            "Leet Code Easy": "AB",
            "Leet Code Medium": "AB",
            "Leet Code Hard": "AB",

            "Total(No.of Problem Solved)": contest_solved,
            "Contest count": contest_name,   # ← REQUIRED CHANGE
            "Contest Rating": contest_rating,
            "Global Rank": global_rank,
            "Top": top_pct
        }

    except Exception as e:
        print("LC exception:", e)
        return ab_row(sn, name, regno, dept)


# ---------- AB SAFE FALLBACK ----------
def ab_row(sn, name, regno, dept):
    return {
        "S. No": sn,
        "Name of the Student": name,
        "Register No.": regno,
        "Dept": dept,
        "Date": "AB",
        "Leet Code Easy": "AB",
        "Leet Code Medium": "AB",
        "Leet Code Hard": "AB",
        "Total(No.of Problem Solved)": "AB",
        "Contest count": "AB",
        "Contest Rating": "AB",
        "Global Rank": "AB",
        "Top": "AB"
    }
