import requests
from bs4 import BeautifulSoup
import re
import time
import random
from utils.date_utils import today_ddmmyyyy

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Referer": "https://www.codechef.com/",
    }


def safe_text(el):
    return el.text.strip() if el else None


def star_to_number(text):
    """Convert ★★★ or 3★ or 7★ → 3 or 7"""
    if not text:
        return None

    # 3★ or 7★ case
    m = re.search(r"(\d+)\s*★?", text)
    if m:
        return m.group(1)

    # ★★★ case
    if "★" in text:
        return str(text.count("★"))

    return None


def fetch_codechef_profile(user, max_retries=3):
    """Fetch CodeChef profile HTML with session retries and exponential backoff for HTTP 429."""
    url = f"https://www.codechef.com/users/{user}"
    session = requests.Session()

    for attempt in range(max_retries):
        try:
            r = session.get(url, headers=get_headers(), timeout=15)
            if r.status_code == 200:
                return r.text
            elif r.status_code == 429:
                # Throttled by CodeChef, back off before retry
                wait = (attempt + 1) * 2 + random.uniform(0.5, 1.5)
                time.sleep(wait)
            elif r.status_code in (404, 403):
                return None
        except Exception as err:
            time.sleep(attempt + 1)

    return None


def get_cc_summary(sn, name, regno, dept, user):
    row = {
        "S. No": sn,
        "Name of the Student": name,
        "Register No": regno,
        "Dept": dept,
        "Date": today_ddmmyyyy(),
        "Current Rating": "AB",
        "Highest Rating": "AB",
        "Division": "AB",
        "Star Rating": "AB",
        "Global Rank": "AB",
        "Country Ranking": "AB",
        "Contest participated": "AB",
        "Problems Solved": "AB",
    }

    if not user or not user.strip():
        return row

    html = fetch_codechef_profile(user.strip())
    if not html:
        return row

    try:
        soup = BeautifulSoup(html, "html.parser")
        header = soup.select_one(".rating-header")
        page_text = soup.get_text(" ", strip=True)

        # ====================================
        # RATING & STARS
        # ====================================
        rating_el = soup.select_one(".rating-number")
        if rating_el:
            row["Current Rating"] = rating_el.text.strip()
        else:
            m_rat = re.search(r"(\d{3,4})\s*\(\s*Rating\s*\)", html, re.I)
            if m_rat:
                row["Current Rating"] = m_rat.group(1)

        star_el = soup.select_one(".rating-star")
        star_val = star_to_number(safe_text(star_el))
        if star_val:
            row["Star Rating"] = star_val

        # ====================================
        # HIGHEST RATING & DIVISION
        # ====================================
        highest_m = re.search(r"Highest Rating\s*\(?(\d+)\)?", html, re.I)
        if highest_m:
            row["Highest Rating"] = highest_m.group(1)

        div_m = re.search(r"Div\s*\d+", html, re.I)
        if div_m:
            row["Division"] = div_m.group(0).capitalize()

        # ====================================
        # GLOBAL + COUNTRY RANK
        # ====================================
        rank_items = soup.select(".rating-ranks li")
        for li in rank_items:
            txt = li.get_text(" ", strip=True)
            a = li.find("a")
            href = a.get("href", "") if a else ""

            # Extract numeric value if present
            num_m = re.search(r"(\d+)", txt)
            val = num_m.group(1) if num_m else ("Inactive" if "Inactive" in txt else None)

            if not val:
                continue

            if "Country" in txt or "filterBy=Country" in href:
                row["Country Ranking"] = val
            elif "Global" in txt or "/ratings/all" in href:
                row["Global Rank"] = val

        # ====================================
        # CONTESTS PARTICIPATED
        # ====================================
        cont_m = re.search(r"Contests\s*\(\s*(\d+)\s*\)", html, re.I)
        if cont_m:
            row["Contest participated"] = cont_m.group(1)
        else:
            for h3 in soup.find_all(["h3", "h4", "h5"]):
                if "Contests" in h3.get_text():
                    m = re.search(r"\(?(\d+)\)?", h3.get_text())
                    if m:
                        row["Contest participated"] = m.group(1)
                        break

        # ====================================
        # TOTAL PROBLEMS SOLVED
        # ====================================
        # Primary: Exact Total Problems Solved header/text
        prob_m = re.search(r"Total Problems Solved:\s*(\d+)", html, re.I)
        if prob_m:
            row["Problems Solved"] = prob_m.group(1)
        else:
            # Fallback 1: Check section.problems-solved header
            p_el = soup.select_one(".problems-solved h3")
            if p_el:
                p_m = re.search(r"(\d+)", p_el.get_text())
                if p_m:
                    row["Problems Solved"] = p_m.group(1)

            # Fallback 2: Count commas across problem blocks if header missing
            if row["Problems Solved"] == "AB":
                total_solved_count = 0
                for sec in soup.select("section.problems-solved .content"):
                    p = sec.find("p")
                    if p and p.get_text(strip=True):
                        total_solved_count += p.get_text(strip=True).count(",") + 1
                if total_solved_count > 0:
                    row["Problems Solved"] = str(total_solved_count)

        return row

    except Exception as e:
        print("CodeChef scrape error:", e)
        return row
