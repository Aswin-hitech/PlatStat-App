import requests
import logging
from datetime import datetime, timezone
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


class CompeteAPISource(BaseContestSource):
    """Aggregator source fetching contests for CodeChef, LeetCode, Codeforces, AtCoder."""
    def fetch_contests(self):
        url = "https://kontests.net/api/v1/all"
        contests = []
        now_ts = int(time.time())
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            if resp.status_code == 200:
                for c in resp.json():
                    site = (c.get("site") or "").lower()
                    platform = None
                    if "codeforces" in site:
                        platform = "codeforces"
                    elif "codechef" in site:
                        platform = "codechef"
                    elif "leetcode" in site:
                        platform = "leetcode"
                    elif "atcoder" in site:
                        platform = "atcoder"

                    if not platform:
                        continue

                    title = c.get("name", "").strip()
                    url_str = c.get("url", "")
                    dur = int(float(c.get("duration") or 7200))
                    
                    st_str = c.get("start_time")
                    st_dt = None
                    if st_str:
                        try:
                            st_dt = datetime.fromisoformat(st_str.replace("Z", "+00:00")).replace(tzinfo=None)
                        except Exception:
                            pass

                    if not st_dt:
                        continue

                    st_ts = int(st_dt.timestamp())
                    if st_ts + dur < now_ts:
                        continue

                    ext_id = re.sub(r'[^a-zA-Z0-9_-]', '_', title.lower())
                    contests.append({
                        "platform": platform,
                        "externalId": ext_id,
                        "contestId": f"{platform}_{ext_id}",
                        "title": title,
                        "startTime": st_dt,
                        "duration": dur,
                        "url": url_str,
                        "source": "compete_api",
                        "status": "UPCOMING" if st_ts > now_ts else "CODING"
                    })
        except Exception as e:
            logger.warning("CompeteAPISource fetch error: %s", e)
        return contests


class ContestSourceAggregator:
    def __init__(self):
        self.sources = [
            CodeforcesSource(),
            LeetCodeSource(),
            AtCoderSource(),
            CompeteAPISource()
        ]

    def fetch_all(self):
        all_contests = []
        for source in self.sources:
            try:
                res = source.fetch_contests()
                all_contests.extend(res)
            except Exception as exc:
                logger.error("Error in contest source %s: %s", source.__class__.__name__, exc)
        return all_contests
