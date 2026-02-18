import requests
from datetime import datetime
import re


def ab_row(sn, name, regno, dept):
    return {
        "S. No": sn,
        "Name of the Student": name,
        "Register No": regno,
        "Dept": dept,
        "Date": "AB",
        "Leet Code Easy": "AB",
        "Leet Code Medium": "AB",
        "Leet code Hard": "AB",
        "Total(No.of Problem Solved)": "AB",
        "Contest count": "AB",
        "Contest Rating": "AB",
        "Global Rank": "AB",
        "Top": "AB"
    }


def to_date(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y") if ts else "AB"


def extract_no(title):
    m = re.search(r"(\d+)", title or "")
    return m.group(1) if m else "AB"


def split_by_contest_total(n):
    if n == 1: return 1,0,0
    if n == 2: return 1,1,0
    if n == 3: return 1,2,0
    if n >= 4: return 1,2,1
    return "AB","AB","AB"


def get_lc_summary(sn, name, regno, dept, user, latest_contest_title=None, latest_contest_time=None):

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
        data = requests.post(
            "https://leetcode.com/graphql",
            json=query,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        ).json()["data"]

        mu = data["matchedUser"]
        if not mu:
            return ab_row(sn,name,regno,dept)

        # profile totals
        stats = mu["submitStats"]["acSubmissionNum"]
        easy,med,hard = stats[1]["count"],stats[2]["count"],stats[3]["count"]
        profile_total = easy+med+hard

        cs = data.get("userContestRanking") or {}
        rating = round(cs["rating"]) if cs.get("rating") else "AB"
        top = cs.get("topPercentage","AB")

        hist = data.get("userContestRankingHistory") or []

        # --------------------------
        # Find participation in GLOBAL latest contest
        # --------------------------
        participated = None
        for h in hist:
            if latest_contest_title and h["contest"]["title"] == latest_contest_title:
                participated = h
                break

        # If participated
        if participated:
            total = participated["problemsSolved"]
            date = to_date(latest_contest_time)
            contest_no = extract_no(latest_contest_title)
            lc_easy,lc_med,lc_hard = split_by_contest_total(total)

        else:
            total = "AB"
            date = to_date(latest_contest_time) if latest_contest_time else "AB"
            contest_no = extract_no(latest_contest_title) if latest_contest_title else "AB"
            lc_easy,lc_med,lc_hard = "AB","AB","AB"

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No": regno,
            "Dept": dept,
            "Date": date,
            "Leet Code Easy": lc_easy,
            "Leet Code Medium": lc_med,
            "Leet code Hard": lc_hard,
            "Total(No.of Problem Solved)": total,
            "Contest count": contest_no,
            "Contest Rating": rating,
            "Global Rank": mu["profile"].get("ranking","AB"),
            "Top": top
        }

    except Exception as e:
        print("LC error:",e)
        return ab_row(sn,name,regno,dept)
