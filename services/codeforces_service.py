import requests
from utils.date_utils import today_ddmmyyyy


def get_cf_summary(sn, name, regno, dept, handle):

    try:
        info_resp = requests.get(
            f"https://codeforces.com/api/user.info?handles={handle}",
            timeout=10
        ).json()

        if info_resp.get("status") != "OK":
            return None

        info = info_resp["result"][0]

        subs_resp = requests.get(
            f"https://codeforces.com/api/user.status?handle={handle}",
            timeout=10
        ).json()

        if subs_resp.get("status") != "OK":
            return None

        subs = subs_resp["result"]

        solved = len({
            (s["problem"]["contestId"], s["problem"]["index"])
            for s in subs
            if s.get("verdict") == "OK"
            and s.get("author", {}).get("participantType") == "CONTESTANT"
        })

        if solved == 0:
            solved = "AB"

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No.": regno,
            "Dept": dept,
            "Date": today_ddmmyyyy(),
            "Problem Solved (6)": solved,
            "Current Rank": info.get("rank") or "AB",
            "Current Rating": info.get("rating") or "AB",
            "Max. Rating": info.get("maxRating") or "AB",
            "Max. Ranking": info.get("maxRank") or "AB"
        }

    except Exception as e:
        print("CF error:", e)
        print("Oops! Looks like you have entered something wrong or the server is down")
        return None
