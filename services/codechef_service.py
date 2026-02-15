import requests
from bs4 import BeautifulSoup
import re
from utils.date_utils import today_ddmmyyyy


# -----------------------------
# helpers
# -----------------------------

def safe_text(el):
    return el.text.strip() if el else None


def star_to_number(text):
    """
    Convert ★★★ or 3★ → 3
    """
    if not text:
        return None

    # 3★ case
    m = re.search(r"\d+", text)
    if m:
        return m.group(0)

    # ★★★ case
    return str(text.count("★")) if "★" in text else None


def count_from_commas(text):
    if not text:
        return None
    return text.count(",") + 1


# -----------------------------
# main
# -----------------------------

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
            timeout=20
        )

        if r.status_code != 200:
            print("CC blocked or user not found:", user)
            return row

        soup = BeautifulSoup(r.text, "html.parser")

        # ====================================
        # HEADER (rating, stars, division)
        # ====================================

        header = soup.select_one(".rating-header")
        if not header:
            print("CC layout missing:", user)
            return row

        # current rating
        rating = header.select_one(".rating-number")
        if rating:
            row["Current Rating"] = rating.text.strip()

        # star rating
        star = header.select_one(".rating-star")
        star_val = star_to_number(safe_text(star))
        if star_val:
            row["Star Rating"] = star_val

        # highest rating
        small = header.find("small")
        if small:
            m = re.search(r"Highest Rating\s+(\d+)", small.text)
            if m:
                row["Highest Rating"] = m.group(1)

        # division
        div_block = header.find_all("div")
        if len(div_block) >= 2:
            m = re.search(r"Div\s*\d+", div_block[1].text)
            if m:
                row["Division"] = m.group(0)

        # ====================================
        # GLOBAL + COUNTRY RANK (FIXED LOGIC)
        # ====================================

        rank_items = soup.select(".rating-ranks li")

        for li in rank_items:
            a = li.find("a")
            if not a:
                continue

            text = li.get_text(" ", strip=True)
            num = re.search(r"\d+", text)
            if not num:
                continue

            href = a.get("href", "")

            if "filterBy=Country" in href:
                row["Country Ranking"] = num.group(0)
            elif "/ratings/all" in href:
                row["Global ranking"] = num.group(0)

        # ====================================
        # CONTEST PARTICIPATED
        # ====================================

        for h3 in soup.find_all("h3"):
            if "Contests" in h3.get_text():
                m = re.search(r"\((\d+)\)", h3.get_text())
                if m:
                    row["Contest participated"] = m.group(1)
                break

        # ====================================
        # LAST STARTERS PROBLEMS SOLVED
        # ====================================

        sections = soup.select("section.problems-solved .content")

        for sec in reversed(sections):
            title = sec.find("h5")
            if not title:
                continue

            if "Starters" in title.text:
                p = sec.find("p")
                if p:
                    val = count_from_commas(p.get_text(strip=True))
                    if val:
                        row["Problems Solved"] = val
                break

        return row

    except Exception as e:
        print("CodeChef scrape error:", e)
        return row
