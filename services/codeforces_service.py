import requests


def get_cf_summary(sn, name, regno, dept, handle):

    row = {
        "S. No": sn,
        "Name of the Student": name,
        "Problem Solved": "AB",
        "Current Rank": "AB",
        "Current Rating": "AB",
        "Max. Rating": "AB",
        "Max. Ranking": "AB"
    }

    try:
        r = requests.get(
            f"https://codeforces.com/api/user.info?handles={handle}",
            timeout=15
        )

        data = r.json()
        if data.get("status") != "OK":
            print("CF info failed:", handle)
            return row

        info = data["result"][0]

        row["Current Rank"] = info.get("rank", "AB")
        row["Current Rating"] = info.get("rating", "AB")
        row["Max. Rating"] = info.get("maxRating", "AB")
        row["Max. Ranking"] = info.get("maxRank", "AB")

        # ---------- submissions ----------
        r = requests.get(
            f"https://codeforces.com/api/user.status?handle={handle}",
            timeout=15
        )

        data = r.json()
        if data.get("status") != "OK":
            return row

        subs = data["result"]

        solved = len({
            (s["problem"]["contestId"], s["problem"]["index"])
            for s in subs
            if s.get("verdict") == "OK"
            and s.get("author", {}).get("participantType") == "CONTESTANT"
        })

        row["Problem Solved"] = solved or "AB"

        return row

    except Exception as e:
        print("CF error:", e)
        return row
