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
            submitStats {
              acSubmissionNum {
                difficulty
                count
              }
            }
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
            return None

        mu = data["data"].get("matchedUser")
        if not mu:
            print("LC user not found:", user)
            return None

        stats = mu["submitStats"]["acSubmissionNum"]

        easy = stats[1]["count"]
        med = stats[2]["count"]
        hard = stats[3]["count"]

        contest_summary = data["data"].get("userContestRanking") or {}

        contest_rating = contest_summary.get("rating")
        contest_count = contest_summary.get("attendedContestsCount")
        top_pct = contest_summary.get("topPercentage")

        if contest_rating is not None:
            contest_rating = round(contest_rating, 2)

        if contest_count in (None, 0):
            contest_rating = "AB"
            contest_count = "AB"
            top_pct = "AB"

        history = data["data"].get("userContestRankingHistory") or []

        last_contest_name = "AB"
        last_contest_date = "AB"
        last_contest_solved = "AB"
        last_contest_rank = "AB"

        for entry in reversed(history):

            if not entry:
                continue

            if entry.get("problemsSolved") is None:
                continue

            last_contest_name = entry["contest"]["title"]
            last_contest_date = epoch_to_ddmmyyyy(
                entry["contest"]["startTime"]
            )
            last_contest_solved = entry["problemsSolved"]
            last_contest_rank = entry.get("ranking", "AB")

            break

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No.": regno,
            "Dept": dept,
            "Date": last_contest_date,
            "Leet Code Easy": easy,
            "Leet Code Medium": med,
            "Leet Code Hard": hard,
            "Total(No.of Problem Solved)": easy + med + hard,
            "Contest count": contest_count,
            "Contest Rating": contest_rating,
            "Global Rank": mu["profile"].get("ranking"),
            "Top": top_pct
        }

    except Exception as e:
        print("LC exception:", e)
        print("Oops! Looks like you have entered something wrong or the server is down")
        return None
