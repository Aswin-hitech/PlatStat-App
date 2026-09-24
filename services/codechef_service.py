"""
CodeChef scraping service.

Architecture:
  - A single long-lived requests.Session is warmed up by visiting the CodeChef
    homepage first.  This sets the session cookies CodeChef requires before it
    serves profile pages.
  - Profile HTML is fetched with retry + exponential back-off.
  - CodeChef always returns HTTP 200 even for non-existent users.  We detect
    invalid profiles by checking for the ``all_rating`` JS variable: present
    on real profiles, absent on "user not found" pages.
  - Data is extracted in two layers:
      1. PRIMARY  – the embedded ``all_rating = [...];`` JS array (most
                    reliable; gives per-contest rating + rank history).
      2. SECONDARY – HTML selectors / regex (current rating block, ranks,
                    problems solved, contests count).
  - The only working CodeChef public APIs are:
      • /api/list/contests/all  (contest list)           → used by get_latest_cc_contests()
      • /users/{username}       (profile HTML page)      → used by fetch_codechef_profile()
    All other /api/* endpoints return 403 or 404; we don't call them.
  - A 5-minute in-process cache for the contest list avoids hammering the API
    when many students are fetched in one batch.
"""

import json
import random
import re
import time

import requests
from bs4 import BeautifulSoup

from utils.date_utils import today_ddmmyyyy


# ---------------------------------------------------------------------------
# User-Agent pool  (rotate to look less like a bot)
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
# Session  (module-level singleton with warm-up state)
# ---------------------------------------------------------------------------
_session = requests.Session()
_session_warmed = False   # True once homepage has been visited


def _ensure_session_warm():
    """
    Visit the CodeChef homepage once per process lifetime so the session gets
    the SESS*** cookie CodeChef checks before serving profile pages at speed.
    Without this cookie the server stalls the connection until timeout.
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
        time.sleep(random.uniform(0.3, 0.7))   # human-like pause
    except Exception as e:
        print(f"[codechef] session warm-up failed (non-fatal): {e}")
    finally:
        _session_warmed = True   # don't retry regardless of outcome


def _profile_headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Referer": "https://www.codechef.com/",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_text(el) -> str | None:
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


def _is_valid_profile(html: str) -> bool:
    """
    CodeChef returns HTTP 200 for *both* valid and invalid usernames.
    A real profile always embeds the ``all_rating`` JS variable and the
    ``.rating-number`` CSS class.  An invalid-user page (~85 KB) has neither.
    """
    return "all_rating" in html and ".rating-number" not in html or "rating-number" in html


# ---------------------------------------------------------------------------
# Contest list  (cached)
# ---------------------------------------------------------------------------
_CC_CONTESTS_CACHE: dict = {"data": None, "timestamp": 0}
_CC_CACHE_TTL = 300   # 5 minutes


def get_latest_cc_contests(limit: int = 6) -> list[dict]:
    """
    Return up to *limit* recent past CodeChef contests (Starters + Monday
    Munch / DSA only), with a 5-minute in-process cache.

    Uses the only working public CodeChef API:
        GET /api/list/contests/all?sort_by=END&sorting_order=desc&...
    """
    now = int(time.time())
    cached = _CC_CONTESTS_CACHE["data"]
    if cached and (now - _CC_CONTESTS_CACHE["timestamp"] < _CC_CACHE_TTL):
        return cached[:limit]

    url = (
        "https://www.codechef.com/api/list/contests/all"
        "?sort_by=END&sorting_order=desc&offset=0&limit=60"
    )
    try:
        r = _session.get(
            url,
            headers={
                "User-Agent": random.choice(_USER_AGENTS),
                "Accept": "application/json, text/plain, */*",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return cached[:limit] if cached else []

        past = r.json().get("past_contests") or []
        results: list[dict] = []
        for c in past:
            name: str = c.get("contest_name") or ""
            code: str = c.get("contest_code") or ""
            start_iso: str = c.get("contest_start_date_iso") or ""
            name_lower = name.lower()
            if not (
                "starters" in name_lower
                or "monday munch" in name_lower
                or "dsa" in name_lower
            ):
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
# Profile fetch  (session warm-up + retry)
# ---------------------------------------------------------------------------
def fetch_codechef_profile(username: str, max_retries: int = 3) -> str | None:
    """
    Fetch a CodeChef user profile page as raw HTML.

    Important notes:
    - CodeChef ALWAYS returns HTTP 200, even for non-existent users.
      Use _is_valid_profile() to check whether the page actually has data.
    - Without the SESS cookie (set by _ensure_session_warm) the server
      stalls and times out.  The warm-up runs once per process.

    Returns None only when the page could not be fetched at all (network
    error / all retries exhausted).
    """
    _ensure_session_warm()
    url = f"https://www.codechef.com/users/{username}"

    for attempt in range(max_retries):
        try:
            resp = _session.get(url, headers=_profile_headers(), timeout=20)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (404, 403):
                return None
            if resp.status_code == 429:
                wait = 2.0 + attempt * 1.5 + random.uniform(0.2, 0.8)
                print(f"[codechef] rate-limited for {username}, waiting {wait:.1f}s")
                time.sleep(wait)
                continue
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait = 1.5 * (attempt + 1) + random.uniform(0.1, 0.5)
                print(f"[codechef] timeout for {username} (attempt {attempt+1}), retry in {wait:.1f}s")
                time.sleep(wait)
        except Exception as e:
            print(f"[codechef] fetch error for '{username}' (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1.0)

    return None


# ---------------------------------------------------------------------------
# PRIMARY data source: embedded all_rating JS array
# ---------------------------------------------------------------------------
def _parse_all_rating(html: str) -> list[dict]:
    """
    Extract and JSON-parse the ``all_rating = [...];`` variable embedded in
    every CodeChef profile page.  Each entry looks like:
        {"code": "START257", "name": "Starters 257", "rating": 1850,
         "rank": 42, "country_rank": 5, "end_date": "2026-09-23"}
    Returns an empty list if the variable is missing or unparseable.
    """
    m = re.search(r"all_rating\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except Exception as e:
        print(f"[codechef] all_rating parse error: {e}")
        return []


def _latest_from_all_rating(ar_data: list[dict]) -> dict:
    """
    Pull the most recent entry from all_rating to get current rating/rank.
    The array is chronological (earliest first), so we use the last entry.
    """
    if not ar_data:
        return {}
    latest = ar_data[-1]
    result = {}
    if latest.get("rating"):
        result["rating"] = str(latest["rating"])
    if latest.get("rank"):
        result["global_rank"] = str(latest["rank"])
    if latest.get("country_rank"):
        result["country_rank"] = str(latest["country_rank"])
    return result


def _match_contest_in_all_rating(
    ar_data: list[dict],
    key_search: str,
    target_norm: str,
) -> dict:
    """
    Find a specific contest entry in all_rating and return its rating + rank.
    Searches by contest name and contest code.
    """
    for item in ar_data:
        c_name = (item.get("name") or "").lower()
        c_code = (item.get("code") or "").lower()
        if key_search in c_name or key_search in c_code or target_norm in c_name:
            return {
                "rating": str(item["rating"]) if item.get("rating") else None,
                "global_rank": str(item["rank"]) if item.get("rank") else None,
                "country_rank": str(item.get("country_rank", "")) or None,
            }
    return {}


# ---------------------------------------------------------------------------
# SECONDARY data source: HTML selectors / regex
# ---------------------------------------------------------------------------
def _parse_rating_html(container, html: str) -> str:
    """Extract current rating from the rating block."""
    el = container.select_one(".rating-number")
    if el:
        txt = el.get_text(strip=True)
        if txt and txt.isdigit():
            return txt
    ctext = container.get_text(" ", strip=True)
    m = re.search(r"\b(\d{3,4})\b", ctext)
    return m.group(1) if m else "AB"


def _parse_stars(container) -> str:
    el = container.select_one(".rating-star")
    val = star_to_number(safe_text(el))
    return val if val else "AB"


def _parse_highest_rating(container) -> str:
    ctext = container.get_text(" ", strip=True)
    m = re.search(r"Highest\s+Rating\s*\(?\s*(\d+)\s*\)?", ctext, re.I)
    return m.group(1) if m else "AB"


def _parse_division(container) -> str:
    ctext = container.get_text(" ", strip=True)
    m = re.search(r"Div\s*\d+", ctext, re.I)
    return m.group(0).strip() if m else "AB"


def _parse_ranks_html(container) -> tuple[str, str]:
    """Return (global_rank, country_rank) from .rating-ranks li elements."""
    global_rank = "AB"
    country_rank = "AB"
    for li in container.select(".rating-ranks li"):
        txt = li.get_text(" ", strip=True)
        a = li.find("a")
        href = a.get("href", "") if a else ""
        num_m = re.search(r"(\d[\d,]*)", txt)
        val = (
            num_m.group(1).replace(",", "") if num_m
            else ("Inactive" if "Inactive" in txt else None)
        )
        if not val:
            continue
        if "Country" in txt or "filterBy=Country" in href:
            country_rank = val
        elif "Global" in txt or "/ratings/all" in href or "dsa-monday" in href:
            global_rank = val
    return global_rank, country_rank


def _parse_contests_count(html: str, soup: BeautifulSoup) -> str:
    m = re.search(r"Contests\s*\(\s*(\d+)\s*\)", html, re.I)
    if m:
        return m.group(1)
    for tag in soup.find_all(["h3", "h4", "h5"]):
        txt = tag.get_text()
        if "Contests" in txt:
            nm = re.search(r"\(?(\d+)\)?", txt)
            if nm:
                return nm.group(1)
    return "AB"


def _parse_problems_solved(html: str, soup: BeautifulSoup) -> str:
    # Pattern 1: explicit inline label
    m = re.search(r"Total Problems Solved:\s*(\d+)", html, re.I)
    if m:
        return m.group(1)
    # Pattern 2: section heading
    el = soup.select_one(".problems-solved h3")
    if el:
        nm = re.search(r"(\d+)", el.get_text())
        if nm:
            return nm.group(1)
    # Pattern 3: count comma-separated names in each solved section
    total = 0
    for sec in soup.select("section.problems-solved .content"):
        p = sec.find("p")
        if p:
            items = p.get_text(strip=True)
            if items:
                total += items.count(",") + 1
    return str(total) if total else "AB"


def _parse_target_contest_solved(
    soup: BeautifulSoup, key_search: str, target_norm: str
) -> int | str:
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
    Fetch and parse a CodeChef user profile, returning a flat summary dict
    ready for spreadsheet export.

    Data sourcing strategy:
      1. Fetch profile HTML (session-warmed, with retry).
      2. Detect invalid users via _is_valid_profile(); return AB row if bad.
      3. Parse all_rating JS array (PRIMARY) for rating, rank, contest history.
      4. Parse HTML selectors / regex (SECONDARY) for stars, division,
         problems solved, contests count.
      5. If a target contest is given, look it up in all_rating first;
         fall back to the problems-solved HTML sections.

    All output fields default to "AB" (Absent/Blank) so the row is always
    structurally complete even when data is partially unavailable.
    """
    output_date = (
        format_contest_date(target_contest_date) if target_contest_date
        else today_ddmmyyyy()
    )

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

    # ------------------------------------------------------------------
    # Step 1 – fetch HTML
    # ------------------------------------------------------------------
    html = fetch_codechef_profile(user.strip())
    if not html:
        print(f"[codechef] could not fetch profile for '{user}' (network failure)")
        return row

    # ------------------------------------------------------------------
    # Step 2 – validate: CodeChef returns 200 for nonexistent users too.
    # A real profile always has all_rating embedded.
    # ------------------------------------------------------------------
    ar_data = _parse_all_rating(html)
    if not ar_data and "rating-number" not in html:
        # HTML page with ~85 KB and no user data → user doesn't exist
        print(f"[codechef] user '{user}' not found (profile page has no data)")
        return row

    try:
        soup = BeautifulSoup(html, "html.parser")

        # ------------------------------------------------------------------
        # Step 3 – choose rating container
        # DSA / Monday Munch contests live in a separate rating block.
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
        # Step 4 – PRIMARY: use all_rating for rating + rank
        # ------------------------------------------------------------------
        latest = _latest_from_all_rating(ar_data)
        if latest.get("rating"):
            row["Current Rating"] = latest["rating"]
        if latest.get("global_rank"):
            row["Global Rank"] = latest["global_rank"]
        if latest.get("country_rank"):
            row["Country Ranking"] = latest["country_rank"]

        # ------------------------------------------------------------------
        # Step 5 – SECONDARY: HTML selectors for everything else
        # ------------------------------------------------------------------
        # Rating from HTML (overrides all_rating if both present, as HTML
        # shows the real-time current rating whereas all_rating is historical)
        html_rating = _parse_rating_html(container, html)
        if html_rating != "AB":
            row["Current Rating"] = html_rating

        row["Star Rating"]    = _parse_stars(container)
        row["Highest Rating"] = _parse_highest_rating(container)
        row["Division"]       = _parse_division(container)

        # HTML ranks (fill gaps left by all_rating)
        g_rank, c_rank = _parse_ranks_html(container)
        if row["Global Rank"] == "AB":
            row["Global Rank"] = g_rank
        if row["Country Ranking"] == "AB":
            row["Country Ranking"] = c_rank

        row["Contest participated"] = _parse_contests_count(html, soup)
        row["Problems Solved"]      = _parse_problems_solved(html, soup)

        # ------------------------------------------------------------------
        # Step 6 – target-contest-specific data
        # ------------------------------------------------------------------
        if target_contest_title:
            target_norm = target_contest_title.lower().strip()
            km = re.search(r"(starters\s*\d+|monday munch[^(]*)", target_norm, re.I)
            key_search = km.group(1).strip() if km else target_norm

            # Historical rating + rank from all_rating (most accurate)
            hist = _match_contest_in_all_rating(ar_data, key_search, target_norm)
            if hist.get("rating"):
                row["Current Rating"] = hist["rating"]
            if hist.get("global_rank"):
                row["Global Rank"] = hist["global_rank"]
            if hist.get("country_rank"):
                row["Country Ranking"] = hist["country_rank"]

            # Problems solved in that specific contest
            row["Target Contest Solved"] = _parse_target_contest_solved(
                soup, key_search, target_norm
            )

    except Exception as e:
        print(f"[codechef] scrape error for '{user}': {e}")

    return row
