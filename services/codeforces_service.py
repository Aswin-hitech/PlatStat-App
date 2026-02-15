import requests
from utils.date_utils import today_ddmmyyyy


def ab_row(sn,name,regno,dept):
    return {
        "S. No": sn,
        "Name of the Student": name,
        "Register No": regno,
        "Dept": dept,
        "Date": today_ddmmyyyy(),
        "Problem Solved": "AB",
        "Current Rank": "AB",
        "Current Rating": "AB",
        "Max. Rating": "AB",
        "Max. Ranking": "AB"
    }


def get_cf_summary(sn,name,regno,dept,handle):

    try:
        info=requests.get(
            f"https://codeforces.com/api/user.info?handles={handle}",
            timeout=15).json()

        if info.get("status")!="OK":
            return ab_row(sn,name,regno,dept)

        user=info["result"][0]

        subs=requests.get(
            f"https://codeforces.com/api/user.status?handle={handle}",
            timeout=15).json()

        if subs.get("status")!="OK":
            return ab_row(sn,name,regno,dept)

        solved=set()

        for s in subs["result"]:
            if s.get("verdict")=="OK" and \
               s.get("author",{}).get("participantType")=="CONTESTANT":
                p=s.get("problem",{})
                if p.get("contestId") and p.get("index"):
                    solved.add((p["contestId"],p["index"]))

        solved=len(solved) if solved else "AB"

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No": regno,
            "Dept": dept,
            "Date": today_ddmmyyyy(),
            "Problem Solved": solved,
            "Current Rank": user.get("rank","AB"),
            "Current Rating": user.get("rating","AB"),
            "Max. Rating": user.get("maxRating","AB"),
            "Max. Ranking": user.get("maxRank","AB")
        }

    except Exception as e:
        print("CF error:",e)
        return ab_row(sn,name,regno,dept)
