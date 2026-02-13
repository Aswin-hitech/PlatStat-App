import requests
from bs4 import BeautifulSoup
import re
from utils.date_utils import today_ddmmyyyy


def count_from_commas(text):
    return text.count(",") + 1 if text else "AB"


def get_cc_summary(sn, name, regno, dept, user):

    row = {
        "S. No": sn,
        "Name of the Student": name,
        "Date": today_ddmmyyyy(),
        "Current Rating": "AB",
        "Highest Rating": "AB",
        "Division": "AB",
        "Star Rating": "AB",
        "Global ranking": "AB",
        "Country Ranking": "AB",
        "Contest participated": "AB",
        "Problems Solved": "AB"
    }

    try:
        r = requests.get(
            f"https://www.codechef.com/users/{user}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )

        soup = BeautifulSoup(r.text, "html.parser")

        header = soup.select_one(".rating-header")

        if not header:
            print("CC layout not found — user or blocked:", user)
            return row

        # ---------- rating ----------
        x = header.select_one(".rating-number")
        if x:
            row["Current Rating"] = x.text.strip()

        # ---------- stars ----------
        x = header.select_one(".rating-star")
        if x:
            star_text = x.text.strip()
            star = star_text.count("★") or re.findall(r"\d+", star_text)[0]
            row["Star Rating"] = star

        # ---------- highest ----------
        small = header.find("small")
        if small:
            m = re.search(r"Highest Rating\s+(\d+)", small.text)
            if m:
                row["Highest Rating"] = m.group(1)

        # ---------- division ----------
        divs = header.find_all("div")
        if len(divs) >= 2:
            m = re.search(r"Div\s*\d+", divs[1].text)
            if m:
                row["Division"] = m.group(0)

        # ---------- ranks ----------
        for li in soup.select(".rating-ranks li"):
            href = li.a["href"]
            num = re.search(r"\d+", li.text)
            if not num:
                continue
            if "Country" in href:
                row["Country Ranking"] = num.group(0)
            else:
                row["Global ranking"] = num.group(0)

        # ---------- contest count ----------
        h3 = soup.find("h3", string=re.compile("Contests"))
        if h3:
            m = re.search(r"\((\d+)\)", h3.text)
            if m:
                row["Contest participated"] = m.group(1)

        # ---------- starters solved ----------
        for sec in soup.select("section.problems-solved .content")[::-1]:
            h5 = sec.find("h5")
            if h5 and "Starters" in h5.text:
                row["Problems Solved"] = count_from_commas(
                    sec.find("p").text
                )
                break

        return row

    except Exception as e:
        print("CC error:", e)
        return row
