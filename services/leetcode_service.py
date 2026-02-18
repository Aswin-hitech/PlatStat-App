import requests
from datetime import datetime
import re


# ==============================
# GLOBAL VARIABLES
# ==============================
LATEST_CONTEST_TITLE = None
LATEST_CONTEST_START = None
LATEST_CONTEST_TYPE = None   # Weekly / Biweekly


# ==============================
# DEFAULT ABSENT ROW
# ==============================
def ab_row(sn, name, regno, dept):
    return {
        "S. No": sn,
        "Name of the Student": name,
        "Register No": regno,
        "Dept": dept,
        "Contest Type": LATEST_CONTEST_TYPE if LATEST_CONTEST_TYPE else "AB",
        "Contest Name": LATEST_CONTEST_TITLE if LATEST_CONTEST_TITLE else "AB",
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


# ==============================
# HELPER FUNCTIONS
# ==============================
def to_date(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y") if ts else "AB"


def extract_no(title):
    m = re.search(r"(\d+)", title or "")
    return m.group(1) if m else "AB"


def split_by_contest_total(n):
    if n == 1: return 1, 0, 0
    if n == 2: return 1, 1, 0
    if n == 3: return 1, 2, 0
    if n >= 4: return 1, 2, 1
    return "AB", "AB", "AB"


def detect_contest_type(title):
    if "Weekly" in title:
        return "Weekly"
    if "Biweekly" in title:
        return "Biweekly"
    return "Other"


# ==============================
# GET LATEST WEEKLY / BIWEEKLY
# ==============================
def get_latest_contest():
    global LATEST_CONTEST_TITLE, LATEST_CONTEST_START, LATEST_CONTEST_TYPE

    query = {
        "query": """
        query {
          userContestRankingHistory(username:"leetcode"){
            contest{title startTime}
          }
        }
        """
    }

    try:
        data = requests.post(
            "https://leetcode.com/graphql",
            json=query,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        ).json()["data"]

        history = data.get("userContestRankingHistory", [])

        # Traverse from latest to oldest
        for h in reversed(history):
            title = h["contest"]["title"]

            # Only Weekly or Biweekly
            if "Weekly" in title or "Biweekly" in title:
                LATEST_CONTEST_TITLE = title
                LATEST_CONTEST_START = h["contest"]["startTime"]
                LATEST_CONTEST_TYPE = detect_contest_type(title)
                break

    except Exception as e:
        print("Error fetching latest contest:", e)


# ==============================
# MAIN FUNCTION
# ==============================
def get_lc_summary(sn, name, regno, dept, user):

    query = {
        "query": """
        query($u:String!){
          matchedUser(username:$u){
            profile{ranking}
            submitStats{acSubmissionNum{difficulty count}}
          }
          userContestRanking(username:$u){
            rating topPercentage
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
        response = requests.post(
            "https://leetcode.com/graphql",
            json=query,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )

        data = response.json()["data"]
        mu = data["matchedUser"]

        if not mu:
            return ab_row(sn, name, regno, dept)

        # Profile totals
        stats = mu["submitStats"]["acSubmissionNum"]
        easy = stats[1]["count"]
        med = stats[2]["count"]
        hard = stats[3]["count"]
        profile_total = easy + med + hard

        # Contest rating
        cs = data.get("userContestRanking") or {}
        rating = round(cs["rating"]) if cs.get("rating") else "AB"
        top = cs.get("topPercentage", "AB")

        # Contest history
        hist = data.get("userContestRankingHistory") or []

        # Find participation in latest contest
        target = next(
            (h for h in hist if h["contest"]["title"] == LATEST_CONTEST_TITLE),
            None
        )

        # If not attended → ABSENT
        if not target:
            return ab_row(sn, name, regno, dept)

        total = target["problemsSolved"]
        date = to_date(LATEST_CONTEST_START)
        contest_no = extract_no(LATEST_CONTEST_TITLE)
        lc_easy, lc_med, lc_hard = split_by_contest_total(total)

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No": regno,
            "Dept": dept,
            "Contest Type": LATEST_CONTEST_TYPE,
            "Contest Name": LATEST_CONTEST_TITLE,
            "Date": date,
            "Leet Code Easy": lc_easy,
            "Leet Code Medium": lc_med,
            "Leet Code Hard": lc_hard,
            "Total(No.of Problem Solved)": total,
            "Contest count": contest_no,
            "Contest Rating": rating,
            "Global Rank": mu["profile"].get("ranking", "AB"),
            "Top": top
        }

    except Exception as e:
        print("LC error:", e)
        return ab_row(sn, name, regno, dept)
