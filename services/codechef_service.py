"""
CodeChef scraping service.

Architecture:
  - A single long-lived requests.Session is warmed up by visiting the CodeChef
    homepage first.  This sets the session cookies that CodeChef requires before
    it will serve profile pages at full speed.
  - Profile HTML is fetched with retry + exponential back-off.
  - All data is extracted from the HTML/embedded JS (no external API calls for
    per-user data, which are blocked / unreliable).
  - A short in-process cache for the contest list avoids hammering the API when
    many students are fetched in one batch.
"""

import json
import random
import re
import time

import requests
from bs4 import BeautifulSoup

from utils.date_utils import today_ddmmyyyy


# ---------------------------------------------------------------------------
# User-Agent pool
# ---------------------------------------------------------------------------
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ---------------------------------------------------------------------------
# Session (module-level singleton with warm-up state)
# ---------------------------------------------------------------------------
_session = requests.Session()
_session_warmed = False          # True once we've visited the homepage


def _ensure_session_warm():
    """
    Visit the CodeChef homepage once per process lifetime so we pick up the
    session cookies that CodeChef checks before serving profile pages.
    """
    global _session_warmed
    if _session_warmed:
        return
    try:
        _session.get(
            "https://www.codechef.com/",
            headers={
                "User-Agent": random.choice(_USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=12,
        )
        _session_warmed = True
        time.sleep(random.uniform(0.3, 0.7))   # brief human-like pause
    except Exception as e:
        print(f"[codechef] session warm-up failed (non-fatal): {e}")
        # Mark as warmed anyway so we don't hammer the homepage on every student
        _session_warmed = True


def _profile_headers():
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Referer": "https://www.codechef.com/",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_text(el):
    return el.get_text(strip=True) if el else None


def star_to_number(text: str | None) -> str | None:
    """Convert '★★★', '3★', '7★' → '3', '7', etc."""
    if not text:
        return None
    m = re.search(r"(\d+)\s*★", text)
    if m:
        return m.group(1)
    if "★" in text:
        return str(text.count("★"))
    return None


def format_contest_date(dt_str: str | None) -> str:
    """Reformat YYYY-MM-DD → DD.MM.YYYY; return today's date on bad input."""
    if not dt_str:
        return today_ddmmyyyy()
    parts = dt_str.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return dt_str


# ---------------------------------------------------------------------------
# Contest list (cached)
# ---------------------------------------------------------------------------
_CC_CONTESTS_CACHE: dict = {"data": None, "timestamp": 0}
_CC_CACHE_TTL = 300   # 5 minutes


def get_latest_cc_contests(limit: int = 6) -> list[dict]:
    """
    Return up to *limit* recent past CodeChef contests (Starters + Monday Munch
    / DSA contests only), with a 5-minute in-process cache.
    """
    now = int(time.time())
    cached = _CC_CONTESTS_CACHE["data"]
    if cached and (now - _CC_CONTESTS_CACHE["timestamp"] < _CC_CACHE_TTL):
        return cached[:limit]

    url = (
        "https://www.codechef.com/api/list/contests/all"
        "?sort_by=END&sorting_order=desc&offset=0&limit=60"
    )
    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
    }
    try:
        r = _session.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return cached[:limit] if cached else []

        past = r.json().get("past_contests") or []
        results: list[dict] = []
        for c in past:
            name: str = c.get("contest_name") or ""
            code: str = c.get("contest_code") or ""
            start_iso: str = c.get("contest_start_date_iso") or ""
            name_lower = name.lower()
            if not ("starters" in name_lower or "monday munch" in name_lower or "dsa" in name_lower):
                continue
            dt = start_iso[:10] if start_iso else (c.get("contest_start_date") or "")
            if name and code:
                results.append({"title": name, "code": code, "date": dt})
            if len(results) >= max(limit, 15):
                break

        _CC_CONTESTS_CACHE["data"] = results
        _CC_CONTESTS_CACHE["timestamp"] = now
        return results[:limit]

    except Exception as e:
        print(f"[codechef] contest list fetch error: {e}")
        return cached[:limit] if cached else []


# ---------------------------------------------------------------------------
# Profile fetch (with session warm-up + retry)
# ---------------------------------------------------------------------------
def fetch_codechef_profile(username: str, max_retries: int = 3) -> str | None:
    """
    Fetch a CodeChef user profile page as raw HTML.

    Strategy:
      1. Warm the session (homepage visit) once per process.
      2. Try up to *max_retries* times with exponential back-off.
      3. Return None if the user doesn't exist (404/403) or all retries fail.
    """
    _ensure_session_warm()
    url = f"https://www.codechef.com/users/{username}"

    for attempt in range(max_retries):
        try:
            resp = _session.get(url, headers=_profile_headers(), timeout=20)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (404, 403):
                # User not found or permanently blocked — no point retrying
                return None
            if resp.status_code == 429:
                # Rate-limited — back off a bit more
                wait = 2.0 + attempt * 1.5 + random.uniform(0.2, 0.8)
                time.sleep(wait)
                continue
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait = 1.5 * (attempt + 1) + random.uniform(0.1, 0.5)
                time.sleep(wait)
        except Exception as e:
            print(f"[codechef] fetch error for {username} (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1.0)

    return None


# ---------------------------------------------------------------------------
# HTML parsers
# ---------------------------------------------------------------------------
def _parse_rating(soup: BeautifulSoup, container, html: str) -> str:
    """Extract current rating (number only)."""
    el = container.select_one(".rating-number")
    if el:
        txt = el.get_text(strip=True)
        if txt and txt.isdigit():
            return txt

    # Fallback: scan container text for a 3-4 digit rating
    ctext = container.get_text(" ", strip=True)
    m = re.search(r"\b(\d{3,4})\b", ctext)
    return m.group(1) if m else "AB"


def _parse_stars(container) -> str:
    """Extract star rating."""
    el = container.select_one(".rating-star")
    val = star_to_number(safe_text(el))
    return val if val else "AB"


def _parse_highest_rating(container) -> str:
    """Extract highest-ever rating."""
    ctext = container.get_text(" ", strip=True)
    m = re.search(r"Highest\s+Rating\s*\(?\s*(\d+)\s*\)?", ctext, re.I)
    return m.group(1) if m else "AB"


def _parse_division(container) -> str:
    """Extract division (e.g. 'Div 1')."""
    ctext = container.get_text(" ", strip=True)
    m = re.search(r"Div\s*\d+", ctext, re.I)
    return m.group(0).strip() if m else "AB"


def _parse_ranks(container) -> tuple[str, str]:
    """Return (global_rank, country_rank) from the rating-ranks list."""
    global_rank = "AB"
    country_rank = "AB"
    for li in container.select(".rating-ranks li"):
        txt = li.get_text(" ", strip=True)
        a = li.find("a")
        href = a.get("href", "") if a else ""
        num_m = re.search(r"(\d[\d,]*)", txt)
        val = num_m.group(1).replace(",", "") if num_m else ("Inactive" if "Inactive" in txt else None)
        if not val:
            continue
        if "Country" in txt or "filterBy=Country" in href:
            country_rank = val
        elif "Global" in txt or "/ratings/all" in href or "dsa-monday" in href:
            global_rank = val
    return global_rank, country_rank


def _parse_contests_participated(html: str, soup: BeautifulSoup) -> str:
    """Extract total contests participated count."""
    m = re.search(r"Contests\s*\(\s*(\d+)\s*\)", html, re.I)
    if m:
        return m.group(1)
    # Fallback: find heading containing 'Contests'
    for tag in soup.find_all(["h3", "h4", "h5"]):
        txt = tag.get_text()
        if "Contests" in txt:
            nm = re.search(r"\(?(\d+)\)?", txt)
            if nm:
                return nm.group(1)
    return "AB"


def _parse_problems_solved(html: str, soup: BeautifulSoup) -> str:
    """Extract total problems solved count."""
    # Pattern 1: explicit label in HTML
    m = re.search(r"Total Problems Solved:\s*(\d+)", html, re.I)
    if m:
        return m.group(1)

    # Pattern 2: problems-solved section heading
    el = soup.select_one(".problems-solved h3")
    if el:
        nm = re.search(r"(\d+)", el.get_text())
        if nm:
            return nm.group(1)

    # Pattern 3: count comma-separated problem lists across all content sections
    total = 0
    for sec in soup.select("section.problems-solved .content"):
        p = sec.find("p")
        if p:
            items = p.get_text(strip=True)
            if items:
                total += items.count(",") + 1
    if total:
        return str(total)

    return "AB"


def _parse_target_contest_solved(soup: BeautifulSoup, key_search: str, target_norm: str) -> int | str:
    """Count problems solved in the target contest section."""
    for sec in soup.select("section.problems-solved .content"):
        h5 = sec.find("h5")
        if not h5:
            continue
        sec_title = h5.get_text(strip=True).lower()
        if key_search in sec_title or target_norm in sec_title:
            p = sec.find("p")
            if p and p.get_text(strip=True):
                return p.get_text(strip=True).count(",") + 1
            return 0
    return "AB"


def _lookup_historical_rating(html: str, key_search: str, target_norm: str) -> tuple[str | None, str | None]:
    """
    Parse the embedded ``all_rating = [...];`` JS array and return
    (rating, rank) for the contest matching *key_search* / *target_norm*.
    """
    ar_m = re.search(r"all_rating\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if not ar_m:
        return None, None
    try:
        ar_data = json.loads(ar_m.group(1))
    except Exception as e:
        print(f"[codechef] all_rating parse error: {e}")
        return None, None

    for item in ar_data:
        c_name = (item.get("name") or "").lower()
        c_code = (item.get("code") or "").lower()
        if key_search in c_name or key_search in c_code or target_norm in c_name:
            rating = str(item["rating"]) if item.get("rating") else None
            rank = str(item["rank"]) if item.get("rank") else None
            return rating, rank
    return None, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_cc_summary(
    sn: int,
    name: str,
    regno: str,
    dept: str,
    user: str,
    target_contest_title: str | None = None,
    target_contest_date: str | None = None,
) -> dict:
    """
    Fetch and parse a CodeChef user's profile, returning a flat summary dict
    suitable for spreadsheet export.

    All fields default to "AB" (Absent/Blank) so the row is always complete
    even if scraping partially fails.
    """
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

        # ------------------------------------------------------------------
        # Choose the right rating container
        # DSA / Monday Munch contests have their own rating block.
        # ------------------------------------------------------------------
        is_dsa = bool(
            target_contest_title
            and re.search(r"dsa|monday", target_contest_title, re.I)
        )
        container = None
        if is_dsa:
            container = (
                soup.select_one("#rating-block-dsa-monday")
                or soup.select_one('[id*="dsa"]')
            )
        if not container:
            container = soup.select_one("#rating-block-all") or soup

        # ------------------------------------------------------------------
        # Core stats
        # ------------------------------------------------------------------
        row["Current Rating"] = _parse_rating(soup, container, html)
        row["Star Rating"]    = _parse_stars(container)
        row["Highest Rating"] = _parse_highest_rating(container)
        row["Division"]       = _parse_division(container)

        g_rank, c_rank = _parse_ranks(container)
        row["Global Rank"]      = g_rank
        row["Country Ranking"]  = c_rank

        row["Contest participated"] = _parse_contests_participated(html, soup)
        row["Problems Solved"]      = _parse_problems_solved(html, soup)

        # ------------------------------------------------------------------
        # Target-contest-specific data
        # ------------------------------------------------------------------
        if target_contest_title:
            target_norm = target_contest_title.lower().strip()
            # Build a robust search key (e.g. "starters 123" or "monday munch")
            km = re.search(r"(starters\s*\d+|monday munch[^(]*)", target_norm, re.I)
            key_search = km.group(1).strip() if km else target_norm

            row["Target Contest Solved"] = _parse_target_contest_solved(soup, key_search, target_norm)

            # Historical rating / rank from embedded JS array
            hist_rating, hist_rank = _lookup_historical_rating(html, key_search, target_norm)
            if hist_rating:
                row["Current Rating"] = hist_rating
            if hist_rank:
                row["Global Rank"] = hist_rank

    except Exception as e:
        print(f"[codechef] scrape error for '{user}': {e}")

    return row
