import requests
from bs4 import BeautifulSoup
import re
from utils.date_utils import today_ddmmyyyy


# ---------------------------------
# helpers
# ---------------------------------

def count_problems_from_commas(text):
    if not text:
        return None
    return text.count(",") + 1


def extract_star_count(star_text):
    """
    Convert star text like '★★★' or '3★' → 3
    """
    if not star_text:
        return None

    # case: 3★
    m = re.search(r"(\d+)", star_text)
    if m:
        return m.group(1)

    # case: ★★★
    return str(star_text.count("★")) if "★" in star_text else None


# ---------------------------------
# main
# ---------------------------------

def get_cc_summary(sn, name, regno, dept, user):

    try:
        r = requests.get(
            f"https://www.codechef.com/users/{user}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )

        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        rating_header = soup.select_one(".rating-header")

        current_rating = None
        highest_rating = None
        star_rating = None
        division = None

        if rating_header:

            x = rating_header.select_one(".rating-number")
            if x:
                current_rating = x.text.strip()

            x = rating_header.select_one(".rating-star")
            if x:
                star_rating = extract_star_count(x.text.strip())

            small = rating_header.find("small")
            if small:
                m = re.search(r"Highest Rating\s+(\d+)", small.text)
                if m:
                    highest_rating = m.group(1)

            divs = rating_header.find_all("div")
            if len(divs) >= 2:
                m = re.search(r"Div\s*\d+", divs[1].text)
                if m:
                    division = m.group(0)

        # ---------- ranks ----------

        global_rank = None
        country_rank = None

        ranks = soup.select_one(".rating-ranks")
        if ranks:
            for li in ranks.select("li"):
                a = li.find("a")
                if not a:
                    continue

                href = a.get("href", "")
                num = re.search(r"(\d+)", li.get_text())

                if not num:
                    continue

                if "filterBy=Country" in href:
                    country_rank = num.group(1)
                elif "/ratings/all" in href:
                    global_rank = num.group(1)

        # ---------- contest count ----------

        contest_count = None
        for h3 in soup.find_all("h3"):
            if "Contests" in h3.text:
                m = re.search(r"\((\d+)\)", h3.text)
                if m:
                    contest_count = m.group(1)

        # ---------- starters solved ----------

        starters_problem_count = None

        sections = soup.select("section.problems-solved .content")
        for sec in sections[::-1]:
            h5 = sec.find("h5")
            if h5 and "Starters" in h5.text:
                p = sec.find("p")
                if p:
                    starters_problem_count = count_problems_from_commas(
                        p.text.strip()
                    )
                break

        # ---------- final ----------

        return {
            "S. No": sn,
            "Name of the Student": name,
            "Register No.": regno,
            "Dept": dept,
            "Date": today_ddmmyyyy(),

            "Current Rating": current_rating or "AB",
            "Highest Rating": highest_rating or "AB",
            "Division": division or "AB",

            # ✅ NEW COLUMN
            "Star Rating": star_rating or "AB",

            "Global ranking": global_rank or "AB",
            "Country Ranking": country_rank or "AB",
            "Contest participated": contest_count or "AB",
            "Problems Solved": starters_problem_count or "AB"
        }

    except Exception as e:
        print("CC error:", e)
        print("Oops! Looks like you have entered something wrong or the server is down")
        return None
