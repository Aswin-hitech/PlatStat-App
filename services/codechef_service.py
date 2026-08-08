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


def format_contest_date(dt_str):
    """Format YYYY-MM-DD to DD.MM.YYYY"""
    if not dt_str:
        return today_ddmmyyyy()
    parts = dt_str.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return dt_str


def get_latest_cc_contests(limit=6):
    """Fetch the latest past CodeChef contests (Starters and Monday Munch only) with title, code, and dates."""
    url = "https://www.codechef.com/api/list/contests/all?sort_by=END&sorting_order=desc&offset=0&limit=60"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
    }

    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        past = data.get("past_contests") or []

        result = []
        for c in past:
            name = c.get("contest_name") or ""
            code = c.get("contest_code") or ""
            start_iso = c.get("contest_start_date_iso") or ""

            # Filter ONLY Starters and Monday Munch (DSA Munch)
            name_lower = name.lower()
            if not ("starters" in name_lower or "monday munch" in name_lower or "dsa" in name_lower):
                continue

            dt_str = start_iso[:10] if start_iso else (c.get("contest_start_date") or "")

            if name and code:
                result.append({
                    "title": name,
                    "code": code,
                    "date": dt_str
                })
                if len(result) >= limit:
                    break

        return result
    except Exception as e:
        print("Error fetching CodeChef contests:", e)
        return []


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
                wait = (attempt + 1) * 2 + random.uniform(0.5, 1.5)
                time.sleep(wait)
            elif r.status_code in (404, 403):
                return None
        except Exception as err:
            time.sleep(attempt + 1)

    return None


def get_cc_summary(sn, name, regno, dept, user, target_contest_title=None, target_contest_date=None):
    output_date = format_contest_date(target_contest_date) if target_contest_date else today_ddmmyyyy()

    row = {
        "S. No": sn,
        "Name of the Student": name,
        "Register No": regno,
        "Dept": dept,
        "Target Contest": target_contest_title or "N/A",
        "Date": output_date,
        "Current Rating": "AB",
        "Highest Rating": "AB",
        "Division": "AB",
        "Star Rating": "AB",
        "Global Rank": "AB",
        "Country Ranking": "AB",
        "Contest participated": "AB",
        "Problems Solved": "AB",
        "Target Contest Solved": "AB",
    }

    if not user or not user.strip():
        return row

    html = fetch_codechef_profile(user.strip())
    if not html:
        return row

    try:
        soup = BeautifulSoup(html, "html.parser")

        # Determine target rating container:
        # If target contest is a DSA / Monday Munch contest, pick #rating-block-dsa-monday
        is_dsa_contest = False
        if target_contest_title:
            t_low = target_contest_title.lower()
            if "dsa" in t_low or "monday" in t_low:
                is_dsa_contest = True

        target_container = None
        if is_dsa_contest:
            target_container = soup.select_one("#rating-block-dsa-monday") or soup.select_one('[id*="dsa"]')

        if not target_container:
            target_container = soup.select_one("#rating-block-all") or soup

        container_text = target_container.get_text(" ", strip=True)

        # ====================================
        # RATING & STARS
        # ====================================
        rating_el = target_container.select_one(".rating-number")
        if rating_el:
            r_txt = rating_el.text.strip()
            row["Current Rating"] = r_txt if r_txt else "AB"
        else:
            m_rat = re.search(r"(\d{3,4})\s*\(\s*Rating\s*\)", container_text, re.I)
            if m_rat:
                row["Current Rating"] = m_rat.group(1)

        star_el = target_container.select_one(".rating-star")
        star_val = star_to_number(safe_text(star_el))
        if star_val:
            row["Star Rating"] = star_val

        # ====================================
        # HIGHEST RATING & DIVISION
        # ====================================
        highest_m = re.search(r"Highest Rating\s*\(?(\d+)\)?", container_text, re.I)
        if highest_m:
            row["Highest Rating"] = highest_m.group(1)

        div_m = re.search(r"Div\s*\d+", container_text, re.I)
        if div_m:
            row["Division"] = div_m.group(0).capitalize()

        # ====================================
        # GLOBAL + COUNTRY RANK
        # ====================================
        rank_items = target_container.select(".rating-ranks li")
        for li in rank_items:
            txt = li.get_text(" ", strip=True)
            a = li.find("a")
            href = a.get("href", "") if a else ""

            num_m = re.search(r"(\d+)", txt)
            val = num_m.group(1) if num_m else ("Inactive" if "Inactive" in txt else None)

            if not val:
                continue

            if "Country" in txt or "filterBy=Country" in href:
                row["Country Ranking"] = val
            elif "Global" in txt or "/ratings/all" in href or "dsa-monday" in href:
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
        prob_m = re.search(r"Total Problems Solved:\s*(\d+)", html, re.I)
        if prob_m:
            row["Problems Solved"] = prob_m.group(1)
        else:
            p_el = soup.select_one(".problems-solved h3")
            if p_el:
                p_m = re.search(r"(\d+)", p_el.get_text())
                if p_m:
                    row["Problems Solved"] = p_m.group(1)

            if row["Problems Solved"] == "AB":
                total_solved_count = 0
                for sec in soup.select("section.problems-solved .content"):
                    p = sec.find("p")
                    if p and p.get_text(strip=True):
                        total_solved_count += p.get_text(strip=True).count(",") + 1
                if total_solved_count > 0:
                    row["Problems Solved"] = str(total_solved_count)

        # Target Contest Matching & Historical Rating Lookup
        if target_contest_title:
            target_norm = target_contest_title.lower().strip()
            target_num_m = re.search(r"(starters\s*\d+|monday munch[^\(]*)", target_norm, re.I)
            key_search = target_num_m.group(1).strip() if target_num_m else target_norm

            sections = soup.select("section.problems-solved .content")
            for sec in sections:
                title_el = sec.find("h5")
                if not title_el:
                    continue
                sec_title = title_el.get_text(strip=True).lower()
                if key_search in sec_title or target_norm in sec_title:
                    p = sec.find("p")
                    if p and p.get_text(strip=True):
                        cnt = p.get_text(strip=True).count(",") + 1
                        row["Target Contest Solved"] = cnt
                    else:
                        row["Target Contest Solved"] = 0
                    break

            # Parse historical rating and rank from all_rating script array
            import json
            ar_m = re.search(r"all_rating\s*=\s*(\[.*?\]);", html, re.DOTALL)
            if ar_m:
                try:
                    ar_data = json.loads(ar_m.group(1))
                    for item in ar_data:
                        c_name = (item.get("name") or "").lower()
                        c_code = (item.get("code") or "").lower()
                        if key_search in c_name or key_search in c_code or target_norm in c_name:
                            if item.get("rating"):
                                row["Current Rating"] = str(item["rating"])
                            if item.get("rank"):
                                row["Global Rank"] = str(item["rank"])
                            break
                except Exception as ar_err:
                    print("CodeChef rating history parse error:", ar_err)

        return row

    except Exception as e:
        print("CodeChef scrape error:", e)
        return row
