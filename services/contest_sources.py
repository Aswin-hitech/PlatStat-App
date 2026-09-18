import requests
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import re

logger = logging.getLogger("platstat.contest_sources")


class BaseContestSource:
    """Base class for modular contest sources."""
    def fetch_contests(self):
        raise NotImplementedError


class CodeforcesSource(BaseContestSource):
    def fetch_contests(self):
        url = "https://codeforces.com/api/contest.list?gym=false"
        contests = []
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK":
                    for c in data.get("result", []):
                        phase = c.get("phase")
                        if phase in ("BEFORE", "CODING"):
                            st_ts = c.get("startTimeSeconds")
                            if not st_ts:
                                continue
                            st_dt = datetime.fromtimestamp(st_ts, tz=timezone.utc).replace(tzinfo=None)
                            dur = c.get("durationSeconds", 7200)
                            cid = str(c["id"])
                            contests.append({
                                "platform": "codeforces",
                                "externalId": cid,
                                "contestId": f"codeforces_{cid}",
                                "title": c.get("name", f"Codeforces Round {cid}"),
                                "startTime": st_dt,
                                "duration": dur,
                                "url": f"https://codeforces.com/contest/{cid}",
                                "source": "codeforces_api",
                                "status": "UPCOMING" if phase == "BEFORE" else "CODING"
                            })
        except Exception as e:
            logger.warning("CodeforcesSource fetch error: %s", e)
        return contests


class LeetCodeSource(BaseContestSource):
    def fetch_contests(self):
        url = "https://leetcode.com/graphql"
        query = {
            "query": """
            query {
              allContests {
                title
                titleSlug
                startTime
                duration
              }
            }
            """
        }
        contests = []
        now_ts = int(time.time())
        try:
            resp = requests.post(url, json=query, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code == 200:
                all_c = resp.json().get("data", {}).get("allContests", [])
                for c in all_c:
                    st_ts = c.get("startTime", 0)
                    dur = c.get("duration", 5400)
                    if st_ts + dur >= now_ts - 3600:
                        st_dt = datetime.fromtimestamp(st_ts, tz=timezone.utc).replace(tzinfo=None)
                        slug = c.get("titleSlug") or c.get("title", "").lower().replace(" ", "-")
                        contests.append({
                            "platform": "leetcode",
                            "externalId": slug,
                            "contestId": f"leetcode_{slug}",
                            "title": c.get("title", slug),
                            "startTime": st_dt,
                            "duration": dur,
                            "url": f"https://leetcode.com/contest/{slug}",
                            "source": "leetcode_graphql",
                            "status": "UPCOMING" if st_ts > now_ts else "CODING"
                        })
        except Exception as e:
            logger.warning("LeetCodeSource fetch error: %s", e)
        return contests


class AtCoderSource(BaseContestSource):
    def fetch_contests(self):
        url = "https://kenkoooo.com/atcoder/resources/contests.json"
        contests = []
        now_ts = int(time.time())
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for c in data:
                    st_ts = c.get("start_epoch_second", 0)
                    dur = c.get("duration_second", 6000)
                    # Filter out practice guides starting in 1970 or with multi-year duration
                    if st_ts > 1577836800 and dur <= 864000 and st_ts + dur >= now_ts - 3600:
                        st_dt = datetime.fromtimestamp(st_ts, tz=timezone.utc).replace(tzinfo=None)
                        cid = c.get("id")
                        contests.append({
                            "platform": "atcoder",
                            "externalId": cid,
                            "contestId": f"atcoder_{cid}",
                            "title": c.get("title", cid),
                            "startTime": st_dt,
                            "duration": dur,
                            "url": f"https://atcoder.jp/contests/{cid}",
                            "source": "atcoder_api",
                            "status": "UPCOMING" if st_ts > now_ts else "CODING"
                        })
        except Exception as e:
            logger.warning("AtCoderSource fetch error: %s", e)
        return contests


class CodeChefSource(BaseContestSource):
    """Fetch upcoming CodeChef contests via the official CodeChef contest list API."""

    def fetch_contests(self):
        contests = []
        now_ts = int(time.time())
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        # Fetch upcoming + present contests
        for endpoint_type in ("future", "present"):
            url = (
                f"https://www.codechef.com/api/list/contests/all"
                f"?sort_by=START&sorting_order=asc&offset=0&limit=30"
                f"&category={endpoint_type}"
            )
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                contest_list = data.get(f"{endpoint_type}_contests") or []
                for c in contest_list:
                    name = (c.get("contest_name") or "").strip()
                    code = (c.get("contest_code") or "").strip()
                    if not name or not code:
                        continue

                    # Parse start time
                    start_iso = c.get("contest_start_date_iso") or c.get("contest_start_date") or ""
                    st_dt = None
                    if start_iso:
                        try:
                            st_dt = datetime.fromisoformat(
                                start_iso.replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                        except Exception:
                            pass

                    if not st_dt:
                        continue

                    # Parse duration
                    end_iso = c.get("contest_end_date_iso") or c.get("contest_end_date") or ""
                    dur = 10800  # default 3h
                    if end_iso:
                        try:
                            end_dt = datetime.fromisoformat(
                                end_iso.replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                            dur = max(0, int((end_dt - st_dt).total_seconds()))
                        except Exception:
                            pass

                    st_ts = int(st_dt.timestamp())
                    # Skip if ended more than 1 hour ago
                    if st_ts + dur < now_ts - 3600:
                        continue

                    ext_id = re.sub(r"[^a-zA-Z0-9_-]", "_", code.lower())
                    contests.append({
                        "platform": "codechef",
                        "externalId": ext_id,
                        "contestId": f"codechef_{ext_id}",
                        "title": name,
                        "startTime": st_dt,
                        "duration": dur,
                        "url": f"https://www.codechef.com/{code}",
                        "source": "codechef_api",
                        "status": "UPCOMING" if st_ts > now_ts else "CODING",
                    })
            except Exception as e:
                logger.warning("CodeChefSource fetch error (%s): %s", endpoint_type, e)

        return contests


class ContestSourceAggregator:
    def __init__(self):
        self.sources = [
            CodeforcesSource(),
            LeetCodeSource(),
            AtCoderSource(),
            CodeChefSource(),
        ]

    def fetch_all(self):
        """Fetch contests from all sources concurrently.

        Each source runs in its own thread so a slow or timing-out source
        cannot block the others.  Per-source timeout is capped at 15 s.
        """
        all_contests = []
        source_timeout = 15  # seconds – safety cap per source

        with ThreadPoolExecutor(max_workers=len(self.sources), thread_name_prefix="contest_src") as executor:
            future_to_source = {
                executor.submit(self._safe_fetch, src): src
                for src in self.sources
            }
            for future in as_completed(future_to_source, timeout=source_timeout + 2):
                src = future_to_source[future]
                try:
                    results = future.result(timeout=source_timeout)
                    all_contests.extend(results)
                except Exception as exc:
                    logger.warning(
                        "Contest source %s timed out or raised an error: %s",
                        src.__class__.__name__,
                        exc,
                    )

        return all_contests

    @staticmethod
    def _safe_fetch(source):
        """Wrapper that catches all exceptions from a source's fetch_contests."""
        try:
            return source.fetch_contests()
        except Exception as exc:
            logger.error(
                "Unhandled error in %s.fetch_contests: %s",
                source.__class__.__name__,
                exc,
            )
            return []
