import re
import os
import json
import time
from datetime import datetime
from io import BytesIO
from bson import ObjectId

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory

from concurrent.futures import ThreadPoolExecutor, as_completed

from parsers.csv_parser import parse_csv
from parsers.excel_parser import parse_excel
from repositories import ClassRepository
from services.class_service import ClassService
from services.codechef_service import get_cc_summary, get_latest_cc_contests, fetch_codechef_profile
from services.codeforces_service import get_cf_summary, get_latest_cf_contests
from services.contest_scheduler import contest_scheduler
from services.contest_service import contest_service
from services.leetcode_service import find_latest_lc_contest, get_lc_summary, get_latest_lc_contests
from services.notification_service import notification_manager
from services.student_service import StudentService
from services.topper_service import compute_topper
from utils.date_utils import get_export_filename, today_ddmmyyyy
from utils.excel_utils import create_excel_file

if not (os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")):
    try:
        contest_scheduler.start()
    except Exception as _e:
        pass


app = Flask(__name__)
class_service = ClassService()
student_service = StudentService()
class_repo = ClassRepository()


def _serialize_mongo(obj):
    if isinstance(obj, list):
        return [_serialize_mongo(i) for i in obj]
    if isinstance(obj, dict):
        res = {}
        for k, v in obj.items():
            if k == "_id" or isinstance(v, ObjectId):
                res[k] = str(v)
            elif isinstance(v, datetime):
                res[k] = v.isoformat()
            elif isinstance(v, (dict, list)):
                res[k] = _serialize_mongo(v)
            else:
                res[k] = v
        return res
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj



import tempfile
from db import store

cache_tables = {
    "codeforces": [],
    "codechef": [],
    "leetcode": [],
}

CACHE_FILE = os.path.join(app.root_path, "cache_tables.json")
TEMP_CACHE_FILE = os.path.join(tempfile.gettempdir(), "platstat_cache_tables.json")


def _save_cache_tables(tables):
    global cache_tables
    cache_tables = tables
    # 1. Local workspace root
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(tables, f, default=str)
    except Exception:
        pass
    # 2. System temp directory (writable in AWS Lambda/Vercel /tmp)
    try:
        with open(TEMP_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(tables, f, default=str)
    except Exception:
        pass
    # 3. MongoDB collection for persistent cross-instance / cross-process sharing
    try:
        store.collection("eval_cache").update_one(
            {"_id": "latest_evaluation"},
            {"$set": {"tables": tables, "updated_at": datetime.utcnow().isoformat()}},
            upsert=True,
        )
    except Exception:
        pass


def _load_cache_tables():
    global cache_tables
    has_data = any(
        any(b.get("rows") for b in cache_tables.get(key, []))
        for key in ("codeforces", "codechef", "leetcode")
    )
    if has_data:
        return cache_tables

    # 1. Try local root cache file
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and any(loaded.get(k) for k in ("codeforces", "codechef", "leetcode")):
                    cache_tables = loaded
                    return cache_tables
        except Exception:
            pass

    # 2. Try temp cache file
    if os.path.exists(TEMP_CACHE_FILE):
        try:
            with open(TEMP_CACHE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and any(loaded.get(k) for k in ("codeforces", "codechef", "leetcode")):
                    cache_tables = loaded
                    return cache_tables
        except Exception:
            pass

    # 3. Try database eval_cache
    try:
        doc = store.collection("eval_cache").find_one({"_id": "latest_evaluation"})
        if doc and isinstance(doc.get("tables"), dict):
            loaded = doc["tables"]
            if any(loaded.get(k) for k in ("codeforces", "codechef", "leetcode")):
                cache_tables = loaded
                return cache_tables
    except Exception:
        pass

    return cache_tables


def _clean_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    val_str = str(value).strip()
    if val_str.lower() in ("nan", "none", "null"):
        return ""
    return val_str


def _selected_platforms(form):
    selected = []
    for platform in ("codeforces", "codechef", "leetcode"):
        if form.get(f"platform_{platform}"):
            selected.append(platform)
    return selected


def _row_value(row, *keys):
    if not isinstance(row, dict):
        return ""
    # 1. Exact key match
    for key in keys:
        if key in row:
            value = _clean_text(row.get(key))
            if value:
                return value
    # 2. Normalized key match (case-insensitive & stripped of special characters)
    normalized_row = {
        re.sub(r'[^a-z0-9]', '', str(k).lower()): v
        for k, v in row.items()
        if k is not None
    }
    for key in keys:
        norm_key = re.sub(r'[^a-z0-9]', '', str(key).lower())
        if norm_key in normalized_row:
            value = _clean_text(normalized_row[norm_key])
            if value:
                return value
    return ""


def _normalize_rows(rows):
    normalized = []
    for row in rows:
        name = _row_value(row, "name", "studentName", "student_name", "student name", "student")
        reg_no = _row_value(row, "register_no", "registerNo", "register_no", "reg_no", "regno", "register no", "reg no", "registration_no")
        dept = _row_value(row, "department", "dept", "department_name")
        cf = _row_value(row, "codeforces", "codeforces_id", "codeforcesId", "codeforces id", "codeforces handle", "cf", "cf_id", "cf_handle")
        cc = _row_value(row, "codechef", "codechef_id", "codechefId", "codechef id", "codechef handle", "cc", "cc_id", "cc_handle")
        lc = _row_value(row, "leetcode", "leetcode_id", "leetcodeId", "leetcode id", "leetcode handle", "lc", "lc_id", "lc_handle")

        normalized.append(
            {
                "name": name,
                "studentName": name,
                "register_no": reg_no,
                "registerNo": reg_no,
                "department": dept,
                "codeforces": cf,
                "codechef": cc,
                "leetcode": lc,
            }
        )
    return normalized


def _rows_from_form(form):
    row = {
        "name": _clean_text(form.get("name")),
        "studentName": _clean_text(form.get("name")),
        "register_no": _clean_text(form.get("register_no")),
        "registerNo": _clean_text(form.get("register_no")),
        "department": _clean_text(form.get("department")),
        "codeforces": _clean_text(form.get("codeforces")),
        "codechef": _clean_text(form.get("codechef")),
        "leetcode": _clean_text(form.get("leetcode")),
    }
    if not row["name"] and not row["register_no"]:
        return []
    return [row]


def _load_rows(uploaded_file):
    filename = (uploaded_file.filename or "").lower()
    if filename.endswith(".csv"):
        return parse_csv(uploaded_file)
    if filename.endswith((".xlsx", ".xls")):
        return parse_excel(uploaded_file)
    return None


def _analyze_rows(rows, selected_platforms, lc_targets=None, cc_targets=None, cf_targets=None):
    """
    Returns dict mapping platform names to a list of contest table blocks:
    {
        "leetcode": [
            {"contest": "Weekly Contest 400", "date": "2026-07-26", "rows": [...]},
            ...
        ],
        ...
    }
    """
    tables = {"codeforces": [], "codechef": [], "leetcode": []}

    if "leetcode" in selected_platforms and not lc_targets:
        latest_title, latest_time = find_latest_lc_contest(rows)
        if latest_title:
            lc_targets = [{"title": latest_title, "startTime": latest_time}]
        else:
            lc_targets = [{"title": None, "startTime": None}]

    if "codechef" in selected_platforms and not cc_targets:
        cc_targets = [{"title": None, "date": None}]

    if "codeforces" in selected_platforms and not cf_targets:
        cf_targets = [{"title": None, "id": None, "date": None}]

    max_workers = 10

    if "codeforces" in selected_platforms:
        for cf_t in (cf_targets or [{"title": None, "id": None, "date": None}]):
            c_title = cf_t.get("title") or (str(cf_t.get("id")) if cf_t.get("id") else "General Summary")
            eligible = []
            for row in rows:
                name = _clean_text(row.get("name") or row.get("studentName"))
                regno = _clean_text(row.get("register_no") or row.get("registerNo"))
                dept = _clean_text(row.get("department"))
                handle = _clean_text(row.get("codeforces"))
                if name and handle:
                    eligible.append((name, regno, dept, handle))

            c_rows = [None] * len(eligible)

            def _fetch_cf(idx, item):
                n, r, d, h = item
                try:
                    return idx, get_cf_summary(
                        idx + 1, n, r, d, h,
                        target_contest_id=cf_t.get("id"),
                        target_contest_date=cf_t.get("date"),
                        target_contest_title=cf_t.get("title")
                    )
                except Exception:
                    from services.codeforces_service import ab_row, format_contest_date
                    out_d = format_contest_date(cf_t.get("date")) if cf_t.get("date") else today_ddmmyyyy()
                    return idx, ab_row(idx + 1, n, r, d, out_d, cf_t.get("title"))

            if eligible:
                workers = min(max_workers, len(eligible))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_fetch_cf, i, item) for i, item in enumerate(eligible)]
                    for fut in as_completed(futures):
                        try:
                            idx, row_res = fut.result()
                            c_rows[idx] = row_res
                        except Exception:
                            pass
            c_rows = [r for r in c_rows if r is not None]
            tables["codeforces"].append({"contest": c_title, "date": cf_t.get("date"), "rows": c_rows})

    if "codechef" in selected_platforms:
        # Pre-fetch CodeChef user profiles with safe anti-block rate limiting:
        # Visit 5 accounts, fetch data, leave 20 seconds gap, and again 5 accounts.
        unique_handles = list(dict.fromkeys(
            _clean_text(r.get("codechef"))
            for r in rows
            if _clean_text(r.get("codechef")) and _clean_text(r.get("name") or r.get("studentName"))
        ))

        CC_BATCH_SIZE = 5
        CC_GAP_SECONDS = 20
        total_handles = len(unique_handles)

        if total_handles > 0:
            print(f"[codechef] Starting safe batch fetch for {total_handles} student account(s) (5 accounts per batch, 20s gap)...")

        for b_start in range(0, total_handles, CC_BATCH_SIZE):
            b_handles = unique_handles[b_start:b_start + CC_BATCH_SIZE]
            b_num = (b_start // CC_BATCH_SIZE) + 1
            total_b = (total_handles + CC_BATCH_SIZE - 1) // CC_BATCH_SIZE
            print(f"[codechef] Batch {b_num}/{total_b}: Fetching accounts {b_start+1}-{b_start+len(b_handles)} of {total_handles} ({', '.join(b_handles)})...")

            for h_idx, h in enumerate(b_handles):
                try:
                    fetch_codechef_profile(h)
                except Exception as err:
                    print(f"[codechef] Pre-fetch error for '{h}': {err}")
                if h_idx < len(b_handles) - 1:
                    time.sleep(0.8)  # human-like pause between individual accounts

            # Leave 20 seconds gap between batches if more accounts remain
            if b_start + CC_BATCH_SIZE < total_handles:
                print(f"[codechef] Completed batch {b_num}. Leaving {CC_GAP_SECONDS}s gap before next batch to protect IDs...")
                time.sleep(CC_GAP_SECONDS)

        for cc_t in (cc_targets or [{"title": None, "date": None}]):
            c_title = cc_t.get("title") or "General Summary"
            eligible = []
            for row in rows:
                name = _clean_text(row.get("name") or row.get("studentName"))
                regno = _clean_text(row.get("register_no") or row.get("registerNo"))
                dept = _clean_text(row.get("department"))
                handle = _clean_text(row.get("codechef"))
                if name and handle:
                    eligible.append((name, regno, dept, handle))

            c_rows = []
            for idx, (n, r, d, h) in enumerate(eligible):
                try:
                    row_res = get_cc_summary(
                        idx + 1, n, r, d, h,
                        target_contest_title=cc_t.get("title"),
                        target_contest_date=cc_t.get("date")
                    )
                    c_rows.append(row_res)
                except Exception as exc:
                    print(f"[codechef] Error compiling summary for {h}: {exc}")
                    from utils.date_utils import today_ddmmyyyy
                    from services.codechef_service import format_contest_date
                    out_d = format_contest_date(cc_t.get("date")) if cc_t.get("date") else today_ddmmyyyy()
                    c_rows.append({
                        "S. No": idx + 1,
                        "Name of the Student": n,
                        "Register No": r,
                        "Dept": d,
                        "Target Contest": cc_t.get("title") or "N/A",
                        "Date": out_d,
                        "Current Rating": "AB",
                        "Highest Rating": "AB",
                        "Division": "AB",
                        "Star Rating": "AB",
                        "Global Rank": "AB",
                        "Country Ranking": "AB",
                        "Contest participated": "AB",
                        "Problems Solved": "AB",
                        "Target Contest Solved": "AB",
                    })

            tables["codechef"].append({"contest": c_title, "date": cc_t.get("date"), "rows": c_rows})

    if "leetcode" in selected_platforms:
        for lc_t in (lc_targets or [{"title": None, "startTime": None}]):
            c_title = lc_t.get("title") or "General Summary"
            eligible = []
            for row in rows:
                name = _clean_text(row.get("name") or row.get("studentName"))
                regno = _clean_text(row.get("register_no") or row.get("registerNo"))
                dept = _clean_text(row.get("department"))
                handle = _clean_text(row.get("leetcode"))
                if name and handle:
                    eligible.append((name, regno, dept, handle))

            c_rows = [None] * len(eligible)

            def _fetch_lc(idx, item):
                n, r, d, h = item
                try:
                    return idx, get_lc_summary(
                        idx + 1, n, r, d, h,
                        lc_t.get("title"),
                        lc_t.get("startTime")
                    )
                except Exception:
                    from services.leetcode_service import ab_row
                    return idx, ab_row(idx + 1, n, r, d, lc_t.get("title"))

            if eligible:
                workers = min(max_workers, len(eligible))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_fetch_lc, i, item) for i, item in enumerate(eligible)]
                    for fut in as_completed(futures):
                        try:
                            idx, row_res = fut.result()
                            c_rows[idx] = row_res
                        except Exception:
                            pass
            c_rows = [r for r in c_rows if r is not None]
            tables["leetcode"].append({"contest": c_title, "rows": c_rows})

    return tables


META_EXPORT_KEYS = {"s. no", "s.no", "student name", "name", "register no", "reg no", "reg_no", "register_no", "department", "dept", "section", "email", "platform"}


def _sanitize_sheet_title(title):
    """Sanitize worksheet titles by removing forbidden characters for openpyxl: \\ / ? * : [ ]"""
    if not title:
        return "Sheet"
    cleaned = re.sub(r'[\\*?:/\[\]]', '_', str(title)).strip()[:28].strip()
    return cleaned or "Sheet"


def _clean_row_dict(row):
    """Clean row dictionary to replace None/NaN with 'AB' or empty string for metadata and ensure numeric values don't turn into floats."""
    cleaned = {}
    for k, v in row.items():
        k_lower = str(k).strip().lower()
        try:
            _is_na = v is None or pd.isna(v)
        except (ValueError, TypeError):
            _is_na = False
        if _is_na or (isinstance(v, str) and v.strip().lower() in ("nan", "none", "null")):
            cleaned[k] = "" if k_lower in META_EXPORT_KEYS else "AB"
        elif v == "":
            cleaned[k] = "" if k_lower in META_EXPORT_KEYS else "AB"
        elif isinstance(v, float) and v.is_integer():
            cleaned[k] = int(v)
        else:
            cleaned[k] = v
    return cleaned


def _combined_export_frame(tables, requested_platform=None):
    """Build a combined pandas DataFrame for CSV export."""
    frames = []

    target_keys = [requested_platform] if (requested_platform and requested_platform in tables) else ["codeforces", "codechef", "leetcode"]

    for platform in target_keys:
        contest_blocks = tables.get(platform, [])
        for block in contest_blocks:
            rows = block.get("rows", [])
            if not rows:
                continue
            cleaned_rows = [_clean_row_dict(r) for r in rows]
            frame = pd.DataFrame(cleaned_rows)
            if len(target_keys) > 1:
                frame.insert(0, "Platform", platform.capitalize())
            frames.append(frame)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.fillna("AB")
    return combined


def _auto_fit_columns(worksheet):
    """Auto-adjust worksheet column widths and apply header styling."""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=11, color="0F172A")
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0")
    )

    for row in worksheet.iter_rows():
        for cell in row:
            if cell.row == 1:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            else:
                cell.font = data_font
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="left", vertical="center")

    for col in worksheet.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        worksheet.column_dimensions[col_letter].width = max(max_len + 4, 12)


def _tables_to_excel_stream(tables, requested_platform=None):
    """Build an Excel file stream with dedicated contest & platform worksheets and styling."""
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        workbook = writer.book
        used_sheet_names = set()

        def _unique_sheet_name(candidate):
            """Return a unique sheet name within 31 chars (Excel limit)."""
            candidate = candidate[:31]
            if candidate not in used_sheet_names:
                used_sheet_names.add(candidate)
                return candidate
            for i in range(2, 1000):
                suffix = f" ({i})"
                trimmed = candidate[:31 - len(suffix)] + suffix
                if trimmed not in used_sheet_names:
                    used_sheet_names.add(trimmed)
                    return trimmed
            return candidate  # fallback (should never reach)

        target_keys = [requested_platform] if (requested_platform and requested_platform in tables) else ["codeforces", "codechef", "leetcode"]

        # 1. Combined sheet first
        combined_frame = _combined_export_frame(tables, requested_platform=requested_platform)
        if not combined_frame.empty:
            sheet_name = _unique_sheet_name("Combined Results")
            combined_frame.to_excel(writer, sheet_name=sheet_name, index=False)
            try:
                _auto_fit_columns(writer.sheets[sheet_name])
            except Exception:
                pass

        # 2. Dedicated platform sheets (Codeforces, CodeChef, LeetCode)
        for platform in target_keys:
            p_frame = _combined_export_frame(tables, requested_platform=platform)
            if not p_frame.empty:
                if "Platform" in p_frame.columns:
                    p_frame = p_frame.drop(columns=["Platform"])
                sheet_name = _unique_sheet_name(platform.capitalize())
                p_frame.to_excel(writer, sheet_name=sheet_name, index=False)
                try:
                    _auto_fit_columns(writer.sheets[sheet_name])
                except Exception:
                    pass

        # 3. Dedicated sheet per contest table
        for platform in target_keys:
            contest_blocks = tables.get(platform, [])
            for block in contest_blocks:
                contest_title = block.get("contest") or platform.capitalize()
                rows = block.get("rows", [])
                if not rows:
                    continue

                safe_title = _sanitize_sheet_title(contest_title)
                candidate = f"{platform[:2].upper()} - {safe_title}"
                sheet_name = _unique_sheet_name(candidate)

                cleaned_rows = [_clean_row_dict(r) for r in rows]
                df = pd.DataFrame(cleaned_rows)
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                try:
                    _auto_fit_columns(writer.sheets[sheet_name])
                except Exception:
                    pass

        # Ensure there is at least one sheet so openpyxl doesn't write a corrupt file
        if not workbook.sheetnames:
            workbook.create_sheet("Results")

        # Remove the default empty 'Sheet' if more sheets exist
        if "Sheet" in workbook.sheetnames and len(workbook.sheetnames) > 1:
            del workbook["Sheet"]

    output.seek(0)
    return output



@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")


@app.route("/api/leetcode/contests", methods=["GET"])
def api_leetcode_contests():
    try:
        contests = get_latest_lc_contests(6)
        return jsonify({"contests": contests})
    except Exception as e:
        return jsonify({"error": f"Failed to fetch LeetCode contests from API: {str(e)}", "contests": []}), 500


@app.route("/api/codechef/contests", methods=["GET"])
def api_codechef_contests():
    try:
        contests = get_latest_cc_contests(6)
        return jsonify({"contests": contests})
    except Exception as e:
        return jsonify({"error": f"Failed to fetch CodeChef contests from API: {str(e)}", "contests": []}), 500


@app.route("/api/codeforces/contests", methods=["GET"])
def api_codeforces_contests():
    try:
        contests = get_latest_cf_contests(6)
        return jsonify({"contests": contests})
    except Exception as e:
        return jsonify({"error": f"Failed to fetch Codeforces contests from API: {str(e)}", "contests": []}), 500


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template("index.html")

    selected_platforms = _selected_platforms(request.form)
    if not selected_platforms:
        return render_template("index.html", error="Select at least one platform to track."), 400

    lc_targets = []
    if "leetcode" in selected_platforms:
        lc_vals = [c.strip() for c in request.form.getlist("leetcode_contest") if c and c.strip()]
        if not lc_vals and request.form.get("leetcode_contest"):
            lc_vals = [request.form.get("leetcode_contest").strip()]

        if not lc_vals:
            return render_template("index.html", error="Please select at least one LeetCode contest before fetching rankings."), 400

        try:
            contests = get_latest_lc_contests(15)
            for val in lc_vals:
                matched = next((c for c in contests if c["title"] == val or c["titleSlug"] == val), None)
                if matched:
                    lc_targets.append({"title": matched["title"], "startTime": matched["startTime"]})
                else:
                    lc_targets.append({"title": val, "startTime": 0})
        except Exception as e:
            return render_template("index.html", error=f"Failed to fetch LeetCode contests from API: {str(e)}"), 500

    cc_targets = []
    if "codechef" in selected_platforms:
        cc_vals = [c.strip() for c in request.form.getlist("codechef_contest") if c and c.strip()]
        if not cc_vals and request.form.get("codechef_contest"):
            cc_vals = [request.form.get("codechef_contest").strip()]

        if cc_vals:
            try:
                cc_contests = get_latest_cc_contests(15)
                for val in cc_vals:
                    matched_cc = next((c for c in cc_contests if c["title"] == val or c["code"] == val), None)
                    if matched_cc:
                        cc_targets.append({"title": matched_cc["title"], "date": matched_cc["date"]})
                    else:
                        cc_targets.append({"title": val, "date": None})
            except Exception:
                for val in cc_vals:
                    cc_targets.append({"title": val, "date": None})

    cf_targets = []
    if "codeforces" in selected_platforms:
        cf_vals = [c.strip() for c in request.form.getlist("codeforces_contest") if c and c.strip()]
        if not cf_vals and request.form.get("codeforces_contest"):
            cf_vals = [request.form.get("codeforces_contest").strip()]

        if cf_vals:
            try:
                cf_contests = get_latest_cf_contests(15)
                for val in cf_vals:
                    matched_cf = next((c for c in cf_contests if c["title"] == val or str(c.get("id")) == val), None)
                    if matched_cf:
                        cf_targets.append({"title": matched_cf["title"], "id": matched_cf.get("id"), "date": matched_cf.get("date")})
                    else:
                        cf_targets.append({"title": val, "id": val, "date": None})
            except Exception:
                for val in cf_vals:
                    cf_targets.append({"title": val, "id": val, "date": None})

    uploaded_file = request.files.get("csvfile")
    rows = []

    if uploaded_file and uploaded_file.filename:
        loaded_rows = _load_rows(uploaded_file)
        if loaded_rows is None:
            return render_template("index.html", error="Upload a CSV or Excel file."), 400
        rows = loaded_rows
    else:
        rows = _rows_from_form(request.form)

    if not rows:
        return render_template("index.html", error="Add a student or upload a file with rows to analyze."), 400

    rows = _normalize_rows(rows)

    if not any(_clean_text(row.get(platform)) for row in rows for platform in selected_platforms):
        return render_template(
            "index.html",
            error="Provide at least one platform ID for the selected platforms.",
        ), 400

    start_eval_time = time.time()
    tables = _analyze_rows(rows, selected_platforms, lc_targets, cc_targets, cf_targets)
    evaluation_time = round(time.time() - start_eval_time, 1)

    _save_cache_tables(tables)

    student_count = len(rows)
    platforms_str = ", ".join([p.capitalize() for p in selected_platforms])
    if uploaded_file and uploaded_file.filename:
        toast_title = "File Upload & Evaluation Completed 🚀"
        toast_msg = f"Successfully uploaded '{uploaded_file.filename}' and evaluated stats for {student_count} student records in {evaluation_time}s across {platforms_str}."
    else:
        toast_title = "Student Stats Evaluation Completed 🎯"
        toast_msg = f"Successfully evaluated stats for {student_count} student records in {evaluation_time}s across {platforms_str}."

    notification_manager.send_notification(
        user_id="default_user",
        title=toast_title,
        message=toast_msg,
        n_type="fetch_complete"
    )

    return render_template(
        "results.html",
        codeforces=tables["codeforces"],
        codechef=tables["codechef"],
        leetcode=tables["leetcode"],
        selected_platforms=selected_platforms,
        evaluation_time=evaluation_time,
        student_count=student_count,
        completion_toast={"title": toast_title, "message": toast_msg, "icon": "🚀" if uploaded_file else "🎯"}
    )


@app.route("/download")
def download():
    export_format = request.args.get("format", "xlsx").lower()
    requested_platform = request.args.get("platform", "").lower().strip()
    requested_contest = request.args.get("contest", "").strip()
    table_idx_str = request.args.get("table_idx", "").strip()

    tables = _load_cache_tables()

    has_data = any(
        any(b.get("rows") for b in tables.get(key, []))
        for key in ("codeforces", "codechef", "leetcode")
    )
    if not has_data:
        return "No data to download.", 404

    # -------------------------------------------------------------------------
    # 1. Unique Table Export (Targeting a specific table from output)
    # -------------------------------------------------------------------------
    if requested_platform and (table_idx_str != "" or requested_contest):
        blocks = tables.get(requested_platform, [])
        target_block = None

        if table_idx_str.isdigit():
            idx = int(table_idx_str)
            if 0 <= idx < len(blocks):
                target_block = blocks[idx]

        if not target_block and requested_contest:
            req_c_norm = requested_contest.strip().lower()
            for b in blocks:
                c_title = str(b.get("contest") or "").strip().lower()
                if c_title == req_c_norm or req_c_norm in c_title:
                    target_block = b
                    break

        if not target_block and blocks:
            target_block = blocks[0]

        if not target_block or not target_block.get("rows"):
            return "No data found for the requested table.", 404

        contest_title = target_block.get("contest") or requested_platform.capitalize()
        contest_date = target_block.get("date") or ""
        rows = target_block.get("rows", [])
        cleaned_rows = [_clean_row_dict(r) for r in rows]
        df = pd.DataFrame(cleaned_rows)

        # Build clean, unique filename for this specific table
        safe_p = requested_platform.capitalize()
        safe_c = re.sub(r'[^a-zA-Z0-9_-]', '_', str(contest_title)).strip('_')
        today_str = datetime.now().strftime("%d-%m-%Y")
        if contest_date:
            safe_d = re.sub(r'[^a-zA-Z0-9_-]', '_', str(contest_date)).strip('_')
            filename = f"{safe_p}_{safe_c}_{safe_d}_{today_str}.{export_format}"
        else:
            filename = f"{safe_p}_{safe_c}_{today_str}.{export_format}"

        if export_format == "csv":
            csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
            output = BytesIO(csv_bytes)
            output.seek(0)
            response = send_file(
                output,
                as_attachment=True,
                download_name=filename,
                mimetype="text/csv",
            )
            response.headers["Content-Type"] = "text/csv; charset=utf-8"
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response

        # Unique Excel export with dedicated styled worksheet
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            sheet_title = _sanitize_sheet_title(contest_title)[:31]
            df.to_excel(writer, sheet_name=sheet_title, index=False)
            try:
                _auto_fit_columns(writer.sheets[sheet_title])
            except Exception:
                pass
        output.seek(0)

        response = send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    # -------------------------------------------------------------------------
    # 2. Combined / Platform Multi-Table Export (Global Download)
    # -------------------------------------------------------------------------
    active_platforms = [k for k, v in tables.items() if v and any(b.get("rows") for b in v)]

    if requested_platform and tables.get(requested_platform):
        platform_name = requested_platform
        export_tables = {requested_platform: tables[requested_platform]}
    else:
        if len(active_platforms) == 1:
            platform_name = active_platforms[0]
        else:
            platform_name = requested_platform if requested_platform else "platstat"
        export_tables = tables

    filename = get_export_filename(platform_name=platform_name, extension=export_format)

    if export_format == "csv":
        frame = _combined_export_frame(export_tables, requested_platform=requested_platform if requested_platform in tables else None)
        csv_bytes = frame.to_csv(index=False).encode("utf-8-sig")
        output = BytesIO(csv_bytes)
        output.seek(0)
        response = send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv",
        )
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    excel_file = _tables_to_excel_stream(export_tables, requested_platform=requested_platform if requested_platform in tables else None)
    response = send_file(
        excel_file,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/dashboard", methods=["GET"])
def dashboard():
    classes = class_service.list_classes()
    return render_template("dashboard.html", classes=_serialize_mongo(classes))


@app.route("/class/<class_id>", methods=["GET"])
def class_detail(class_id):
    cls = class_service.get_class(class_id)
    if not cls:
        return render_template("index.html", error="Class not found."), 404
    students, total = student_service.find_by_class(class_id, page_size=0)
    return render_template("class_detail.html", class_data=_serialize_mongo(cls), students=_serialize_mongo(students))


@app.route("/api/classes", methods=["GET"])
def api_list_classes():
    search = request.args.get("search", "")
    archived = request.args.get("archived") == "true"
    classes = class_service.list_classes(archived=archived, search=search)
    return jsonify({"classes": _serialize_mongo(classes)})


@app.route("/api/classes", methods=["POST"])
def api_create_class():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    if not data.get("className") or not data.get("department"):
        return jsonify({"error": "className and department are required."}), 400
    created = class_service.create_class(data)
    return jsonify(_serialize_mongo(created)), 201


@app.route("/api/classes/<class_id>", methods=["GET"])
def api_get_class(class_id):
    cls = class_service.get_class(class_id)
    if not cls:
        return jsonify({"error": "Class not found"}), 404
    return jsonify(_serialize_mongo(cls))


@app.route("/api/classes/<class_id>", methods=["PUT"])
def api_update_class(class_id):
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    class_service.update_class(class_id, data)
    updated_cls = class_service.get_class(class_id)
    return jsonify({"status": "updated", "class": _serialize_mongo(updated_cls)})


@app.route("/api/classes/<class_id>", methods=["DELETE"])
def api_delete_class(class_id):
    class_service.delete_class(class_id)
    return jsonify({"status": "deleted", "classId": class_id})


@app.route("/api/classes/<class_id>/students", methods=["GET"])
def api_get_class_students(class_id):
    search = request.args.get("search", "")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 0))
    students, total = student_service.find_by_class(class_id, search=search, page=page, page_size=page_size)
    return jsonify({"students": _serialize_mongo(students), "total": total})


@app.route("/api/students", methods=["POST"])
def api_add_student():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    class_id = data.get("classId")
    if not class_id:
        return jsonify({"error": "classId is required"}), 400
    if not data.get("studentName") and not data.get("name"):
        return jsonify({"error": "studentName is required"}), 400
    if not data.get("registerNo") and not data.get("register_no"):
        return jsonify({"error": "registerNo is required"}), 400
    res = student_service.add_single_student(class_id, data)
    return jsonify(_serialize_mongo(res))


@app.route("/api/students/<student_id>", methods=["PUT"])
def api_edit_student(student_id):
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    student_service.edit_student(student_id, data)
    return jsonify({"status": "updated"})



@app.route("/api/students/<student_id>", methods=["DELETE"])
def api_delete_student(student_id):
    res = student_service.delete_student(student_id)
    return jsonify(res)


@app.route("/api/classes/<class_id>/import", methods=["POST"])
def api_import_students(class_id):
    file = request.files.get("file") or request.files.get("sheet")
    if not file or not file.filename:
        return jsonify({"error": "Please upload a CSV or Excel file"}), 400
    filename = file.filename.lower()
    file_type = "csv" if filename.endswith(".csv") else ("excel" if filename.endswith((".xlsx", ".xls")) else "")
    if not file_type:
        return jsonify({"error": "Unsupported file format. Please upload CSV or XLSX/XLS"}), 400
    update_existing = (request.form.get("update_existing") == "true" or request.form.get("updateExisting") == "true" or request.args.get("update_existing") == "true")
    try:
        res = student_service.import_students_from_file(class_id, file, file_type, update_existing=update_existing)
        toast_title = "Roster Imported Successfully 📋"
        toast_msg = f"Imported: {res['inserted']} added, {res['updated']} updated, {res['skipped']} skipped."
        notification_manager.send_notification(
            user_id="default_user",
            title=toast_title,
            message=toast_msg,
            n_type="import_complete"
        )
        return jsonify({"status": "success", "result": res, "toast": {"title": toast_title, "message": toast_msg}})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/classes/<class_id>/fetch", methods=["POST"])
def api_class_fetch(class_id):
    cls = class_service.get_class(class_id)
    if not cls:
        return jsonify({"error": "Class not found"}), 404
    students, _ = student_service.find_by_class(class_id, page_size=0)
    if not students:
        return jsonify({"error": "No students found in class to fetch."}), 400
    
    data = request.get_json(silent=True) or {}
    selected_platforms = data.get("platforms") or ["codeforces", "codechef", "leetcode"]
    
    rows = []
    for st in students:
        p_ids = st.get("platformIds") or {}
        rows.append({
            "name": st.get("studentName", ""),
            "studentName": st.get("studentName", ""),
            "register_no": st.get("registerNo", ""),
            "registerNo": st.get("registerNo", ""),
            "department": st.get("department", ""),
            "codeforces": p_ids.get("codeforces") or st.get("codeforces", ""),
            "codechef": p_ids.get("codechef") or st.get("codechef", ""),
            "leetcode": p_ids.get("leetcode") or st.get("leetcode", ""),
        })
    
    tables = _analyze_rows(rows, selected_platforms)
    
    _save_cache_tables(tables)
    
    class_repo.touch_fetch_stats(class_id)
    
    toast_title = f"Fetch Completed for {cls.get('className', 'Class')} 🚀"
    toast_msg = f"Evaluated stats for {len(rows)} student records across {', '.join([p.capitalize() for p in selected_platforms])}."
    notification_manager.send_notification(
        user_id="default_user",
        title=toast_title,
        message=toast_msg,
        n_type="fetch_complete"
    )
    return jsonify({"status": "success", "tables": tables, "toast": {"title": toast_title, "message": toast_msg}})


@app.route("/api/classes/<class_id>/students/export", methods=["GET"])
def export_class_students(class_id):
    export_format = request.args.get("format", "xlsx").lower()
    requested_platform = request.args.get("platform", "").lower().strip()

    cls = class_service.get_class(class_id)
    if not cls:
        return "Class not found.", 404

    students, _ = student_service.find_by_class(class_id, page_size=0)
    if not students:
        return "No student records found.", 404

    rows = []
    for st in students:
        p_ids = st.get("platformIds") or {}
        rows.append({
            "name": st.get("studentName", ""),
            "studentName": st.get("studentName", ""),
            "register_no": st.get("registerNo", ""),
            "registerNo": st.get("registerNo", ""),
            "department": st.get("department", ""),
            "codeforces": p_ids.get("codeforces") or st.get("codeforces", ""),
            "codechef": p_ids.get("codechef") or st.get("codechef", ""),
            "leetcode": p_ids.get("leetcode") or st.get("leetcode", ""),
        })

    selected_platforms = [requested_platform] if (requested_platform in ("codeforces", "codechef", "leetcode")) else ["codeforces", "codechef", "leetcode"]
    tables = _analyze_rows(rows, selected_platforms)
    _save_cache_tables(tables)

    export_name = requested_platform if requested_platform else (cls.get("className") or "class_roster")
    filename = get_export_filename(platform_name=export_name, extension=export_format)

    if export_format == "csv":
        frame = _combined_export_frame(tables, requested_platform=requested_platform if requested_platform in tables else None)
        csv_bytes = frame.to_csv(index=False).encode("utf-8-sig")
        output = BytesIO(csv_bytes)
        output.seek(0)
        response = send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv",
        )
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    excel_file = _tables_to_excel_stream(tables, requested_platform=requested_platform if requested_platform in tables else None)
    response = send_file(
        excel_file,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response



@app.route("/topper", methods=["GET", "POST"])
def topper():
    if request.method == "GET":
        return render_template("topper.html", result=None, error=None, view_mode="both")

    error = None
    result = None
    view_mode = (request.form.get("view_mode") or "both").lower()

    try:
        file = request.files.get("sheet")
        platform = _clean_text(request.form.get("platform"))
        month_raw = _clean_text(request.form.get("month"))

        if not file or not file.filename:
            error = "Upload a CSV or Excel file."
            return render_template("topper.html", result=None, error=error, view_mode=view_mode)

        if not platform:
            error = "Select a platform."
            return render_template("topper.html", result=None, error=error, view_mode=view_mode)

        if not month_raw:
            error = "Select a month."
            return render_template("topper.html", result=None, error=error, view_mode=view_mode)

        month = int(month_raw)
        filename = file.filename.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        ranked = compute_topper(df, platform, month)
        if ranked is None or ranked.empty:
            error = "No records found for the selected month."
        else:
            result = {}
            if view_mode in ("5", "top5", "both"):
                result["top5"] = ranked.head(5).to_dict("records")
            if view_mode in ("10", "top10", "both"):
                result["top10"] = ranked.head(10).to_dict("records")

            month_names = {1: 'January', 2: 'February', 3: 'March', 4: 'April', 5: 'May', 6: 'June', 7: 'July', 8: 'August', 9: 'September', 10: 'October', 11: 'November', 12: 'December'}
            month_label = month_names.get(month, f"Month {month}")
            toast_title = "Topper Calculation Completed 🏆"
            toast_msg = f"Calculated top performers for {platform.capitalize()} ({month_label})."
            notification_manager.send_notification(
                user_id="default_user",
                title=toast_title,
                message=toast_msg,
                n_type="topper_complete"
            )
            return render_template(
                "topper.html",
                result=result,
                error=error,
                view_mode=view_mode,
                completion_toast={"title": toast_title, "message": toast_msg, "icon": "🏆"}
            )

    except Exception as exc:
        error = str(exc)

    return render_template("topper.html", result=result, error=error, view_mode=view_mode)


# ----------------------------------------------------
# Contest Center & Reminder Module Endpoints
# ----------------------------------------------------
@app.route("/contests")
def contest_center():
    return render_template("contests.html")


@app.route("/notifications")
def notification_center():
    return render_template("notifications.html")


@app.route("/api/contests", methods=["GET"])
def get_contests():
    platform = request.args.get("platform")
    search = request.args.get("search")
    favorites_only = request.args.get("favorites") == "true"
    sort_by = request.args.get("sort", "nearest")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 50))
    user_id = request.args.get("user_id", "default_user")

    items, total = contest_service.get_upcoming_contests(
        platform=platform,
        search=search,
        favorites_only=favorites_only,
        sort_by=sort_by,
        user_id=user_id,
        page=page,
        page_size=page_size
    )
    return jsonify({"contests": items, "total": total, "page": page, "pageSize": page_size})


@app.route("/api/contests/sync", methods=["GET", "POST"])
@app.route("/api/cron_sync", methods=["GET", "POST"])   # Vercel cron entry point
def sync_contests():
    res = contest_service.sync_contests()
    synced_cnt = res.get("synced", res.get("syncedCount", 0)) if isinstance(res, dict) else 0
    toast_title = "Contest Sync Completed 🔄"
    toast_msg = f"Synced latest competitive programming contests ({synced_cnt} active/upcoming)."
    notification_manager.send_notification(
        user_id="default_user",
        title=toast_title,
        message=toast_msg,
        n_type="sync_complete"
    )
    if isinstance(res, dict):
        res["toast"] = {"title": toast_title, "message": toast_msg, "icon": "🔄"}
    return jsonify(res)


@app.route("/api/contests/<contest_id>/favorite", methods=["POST"])
def toggle_contest_favorite(contest_id):
    data = request.get_json(silent=True) or {}
    platform = data.get("platform", "")
    favorite = data.get("favorite", True)
    user_id = data.get("user_id", "default_user")
    contest_service.toggle_favorite(user_id, contest_id, platform, favorite=favorite)
    return jsonify({"status": "success", "contestId": contest_id, "favorite": favorite})


@app.route("/api/contests/<contest_id>/subscribe", methods=["POST"])
def subscribe_contest_reminder(contest_id):
    data = request.get_json(silent=True) or {}
    platform = data.get("platform", "")
    intervals = data.get("intervals", ["1h"])
    user_id = data.get("user_id", "default_user")
    contest_service.subscribe_reminder(user_id, contest_id, platform, intervals=intervals)
    return jsonify({"status": "success", "contestId": contest_id, "intervals": intervals})


@app.route("/api/contests/<contest_id>/unsubscribe", methods=["POST"])
def unsubscribe_contest_reminder(contest_id):
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id", "default_user")
    contest_service.unsubscribe_reminder(user_id, contest_id)
    return jsonify({"status": "success", "contestId": contest_id})


@app.route("/api/user/reminders", methods=["GET"])
def get_user_reminders():
    user_id = request.args.get("user_id", "default_user")
    reminders = contest_service.reminder_repo.get_user_reminders(user_id)
    return jsonify({"reminders": reminders})


@app.route("/api/notifications", methods=["GET"])
def get_notifications():
    user_id = request.args.get("user_id", "default_user")
    items, unread = notification_manager.get_user_notifications(user_id)
    return jsonify({"notifications": items, "unreadCount": unread})


@app.route("/api/notifications/<notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    user_id = request.args.get("user_id", "default_user")
    notification_manager.mark_read(user_id, notification_id)
    return jsonify({"status": "success"})


@app.route("/api/notifications/clear", methods=["POST"])
def clear_notifications():
    user_id = request.args.get("user_id", "default_user")
    notification_manager.clear_all(user_id)
    return jsonify({"status": "success"})


@app.route("/api/dashboard/contest-widget", methods=["GET"])
def get_dashboard_contest_widget():
    user_id = request.args.get("user_id", "default_user")
    summary = contest_service.get_dashboard_contest_summary(user_id)
    return jsonify(summary)


@app.errorhandler(500)
def internal_error(_):
    return render_template("index.html", error="A critical error occurred. Please check your input or try again later."), 500


@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    traceback.print_exc()
    if hasattr(e, "code") and e.code < 500:
        return e
    return render_template("index.html", error=f"Unexpected error: {str(e)}"), 500


if __name__ == "__main__":
    app.run(debug=True)
