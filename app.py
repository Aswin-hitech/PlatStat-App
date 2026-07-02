from flask import Flask, jsonify, render_template, request, send_file
import pandas as pd
from datetime import datetime
from parsers.csv_parser import parse_csv
from services.codeforces_service import get_cf_summary
from services.codechef_service import get_cc_summary
from services.leetcode_service import get_lc_summary
from services.topper_service import compute_topper
from utils.excel_writer import build_excel
from db import store
from services.fetch_engine import fetch_engine
from services.ranking_service import compute_rankings
from services.monthly_service import generate_monthly_report
from repositories import ClassRepository, StudentRepository, HistoryRepository
from utils.ranking_utils import month_key, week_key, year_key

app = Flask(__name__)
class_repo = ClassRepository()
student_repo = StudentRepository()
history_repo = HistoryRepository()

# store last analysis for download
cache_tables = {
    "codeforces": [],
    "codechef": [],
    "leetcode": []
}

def find_latest_lc_contest(rows):

    import requests

    latest_title = None
    latest_time = 0

    for row in rows:

        username = (row.get("leetcode") or "").strip()
        if not username:
            continue

        query = {
            "query": """
            query($u:String!){
              userContestRankingHistory(username:$u){
                contest{title startTime}
                problemsSolved
              }
            }
            """,
            "variables": {"u": username}
        }

        try:
            data = requests.post(
                "https://leetcode.com/graphql",
                json=query,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            ).json()["data"]

            hist = data.get("userContestRankingHistory") or []

            for h in hist:
                if h["contest"]["startTime"] and h["contest"]["startTime"] > latest_time:
                    latest_time = h["contest"]["startTime"]
                    latest_title = h["contest"]["title"]

        except:
            continue

    return latest_title, latest_time

# =====================================================
# MAIN PAGE
# =====================================================

@app.route("/", methods=["GET", "POST"])
def index():

    if request.method == "GET":
        return render_template("index.html")

    # ---------- PLATFORM SELECTION ----------
    use_cf = bool(request.form.get("platform_codeforces"))
    use_cc = bool(request.form.get("platform_codechef"))
    use_lc = bool(request.form.get("platform_leetcode"))

    # if user selects nothing
    if not (use_cf or use_cc or use_lc):
        return render_template("index.html", error="Select at least one platform")

    # ---------- INPUT SOURCE ----------
    csv_file = request.files.get("csvfile")

    if csv_file and csv_file.filename:
        try:
            rows = parse_csv(csv_file)
        except:
            return render_template("index.html", error="Invalid CSV format")
    else:
        rows = [{
            "name": (request.form.get("name") or "").strip(),
            "register_no": (request.form.get("register_no") or "").strip(),
            "department": (request.form.get("department") or "").strip(),
            "codeforces": (request.form.get("codeforces") or "").strip(),
            "codechef": (request.form.get("codechef") or "").strip(),
            "leetcode": (request.form.get("leetcode") or "").strip(),
        }]

    # ---------- TABLES ----------
    codeforces_table = []
    codechef_table = []
    leetcode_table = []

    # ---------- PROCESS STUDENTS ----------
    for i, row in enumerate(rows, start=1):

        if not row:
            continue

        name = (row.get("name") or "").strip()
        if not name:
            continue

        regno = (row.get("register_no") or "").strip()
        dept = (row.get("department") or "").strip()

        # ---------------- Codeforces ----------------
        if use_cf and row.get("codeforces"):
            try:
                r = get_cf_summary(i, name, regno, dept, row.get("codeforces").strip())
                if r:
                    codeforces_table.append(r)
            except Exception as e:
                print("CF failed:", e)

        # ---------------- CodeChef ----------------
        if use_cc and row.get("codechef"):
            try:
                r = get_cc_summary(i, name, regno, dept, row.get("codechef").strip())
                if r:
                    codechef_table.append(r)
            except Exception as e:
                print("CC failed:", e)

        # ---------------- LeetCode ----------------
        # ----------- Find GLOBAL latest LC contest -----------
        latest_lc_title = None
        latest_lc_time = None

        if use_lc:
            latest_lc_title, latest_lc_time = find_latest_lc_contest(rows)

        # ---------------- LeetCode ----------------
        if use_lc and row.get("leetcode"):
            try:
                r = get_lc_summary(
                    i,
                    name,
                    regno,
                    dept,
                    row.get("leetcode").strip(),
                    latest_lc_title,
                    latest_lc_time
                )
                if r:
                    leetcode_table.append(r)
            except Exception as e:
                print("LC failed:", e)


    # ---------- CACHE ----------
    global cache_tables
    cache_tables = {
        "codeforces": codeforces_table or [],
        "codechef": codechef_table or [],
        "leetcode": leetcode_table or []
    }

    return render_template(
        "results.html",
        codeforces=codeforces_table,
        codechef=codechef_table,
        leetcode=leetcode_table
    )


@app.route("/dashboard")
def dashboard():
    platform_count = store.students.count_documents({})
    class_count = store.classes.count_documents({})
    fetch_count = store.fetch_history.count_documents({})
    running_jobs = store.jobs.count_documents({"status": "running"})
    last_fetch = store.fetch_history.find_one(sort=[("createdAt", -1)]) or {}
    recent_activity = list(store.fetch_logs.find(sort=[("createdAt", -1)], limit=10))
    ranking_snapshot = store.rankings.find_one(sort=[("generatedAt", -1)]) or {}
    monthly_winner = store.monthly_stats.find_one(sort=[("generatedAt", -1)]) or {}
    return render_template(
        "dashboard.html",
        totals={
            "total_ids": platform_count,
            "total_classes": class_count,
            "total_fetches": fetch_count,
            "running_jobs": running_jobs,
            "last_fetch": last_fetch,
            "monthly_winner": monthly_winner,
            "top_performer": ranking_snapshot,
            "recent_activity": recent_activity,
        }
    )


# =====================================================
# DOWNLOAD EXCEL
# =====================================================

@app.route("/download")
def download():

    if not any(cache_tables.values()):
        return "No data to download."

    file_stream = build_excel(
        cache_tables["codeforces"],
        cache_tables["codechef"],
        cache_tables["leetcode"]
    )

    filename = f"{datetime.now().strftime('%d%m%Y')}_Tracked.xlsx"

    return send_file(
        file_stream,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    payload = request.get_json(silent=True) or {}
    class_id = payload.get("classId") or ""
    rows = payload.get("rows") or []
    if class_id and not rows:
        rows = student_repo.find({"classId": class_id})
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "rows must be a non-empty list"}), 400
    job = fetch_engine.create_job(rows, class_id=class_id)
    return jsonify({"jobId": job["jobId"], "status": job["status"]}), 202


@app.route("/api/batch-fetch", methods=["POST"])
def api_batch_fetch():
    payload = request.get_json(silent=True) or {}
    class_id = payload.get("classId") or ""
    rows = payload.get("rows") or []
    if class_id and not rows:
        rows = student_repo.find({"classId": class_id})
    job = fetch_engine.create_job(rows, class_id=class_id)
    return jsonify({
        "jobId": job["jobId"],
        "status": job["status"],
        "processed": job.get("processed", 0),
        "success": job.get("success", 0),
        "failed": job.get("failed", 0),
        "skipped": job.get("skipped", 0),
    })


@app.route("/api/jobs/<job_id>/process", methods=["POST"])
def api_process_job(job_id):
    job = fetch_engine.process_job_step(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify({
        "jobId": job["jobId"],
        "status": job["status"],
        "processed": job.get("processed", 0),
        "success": job.get("success", 0),
        "failed": job.get("failed", 0),
        "skipped": job.get("skipped", 0),
        "remaining": job.get("remaining", 0),
        "currentStudent": job.get("currentStudent", ""),
        "currentPlatform": job.get("currentPlatform", ""),
        "elapsedSeconds": job.get("elapsedSeconds", 0),
        "etaSeconds": job.get("etaSeconds", 0),
        "rpm": job.get("rpm", 0),
    })


@app.route("/api/fetch/<job_id>")
def api_fetch_status(job_id):
    job = fetch_engine.get_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify({
        "jobId": job.get("jobId"),
        "status": job.get("status"),
        "processed": job.get("processed", 0),
        "success": job.get("success", 0),
        "failed": job.get("failed", 0),
        "skipped": job.get("skipped", 0),
        "currentStudent": job.get("currentStudent", ""),
        "currentPlatformId": job.get("currentPlatformId", ""),
        "remaining": job.get("remaining", 0),
        "cancelled": job.get("cancelled", False),
    })


@app.route("/api/fetch/<job_id>/cancel", methods=["POST"])
def api_cancel_fetch(job_id):
    job = fetch_engine.cancel_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"jobId": job["jobId"], "status": job["status"]})


@app.route("/api/fetch/<job_id>/resume", methods=["POST"])
def api_resume_fetch(job_id):
    job = fetch_engine.resume_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify({
        "jobId": job["jobId"],
        "status": job["status"],
        "processed": job["processed"],
        "success": job["success"],
        "failed": job["failed"],
        "skipped": job["skipped"],
    })


@app.route("/api/rankings")
def api_rankings():
    period = request.args.get("period")
    platform = request.args.get("platform")
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("pageSize", 25)), 1), 100)
    skip = (page - 1) * page_size
    query = {}
    if period:
        query["period"] = period
    if platform:
        query["platform"] = platform
    total = store.rankings.count_documents(query)
    items = list(store.rankings.find(query=query, sort=[("generatedAt", -1)], skip=skip, limit=page_size))
    return jsonify({"items": items, "page": page, "pageSize": page_size, "total": total})


@app.route("/api/rankings/history")
def api_rankings_history():
    period = request.args.get("period", "")
    snapshot_key = request.args.get("snapshotKey", "")
    platform = request.args.get("platform", "")
    query = {}
    if period:
        query["period"] = period
    if snapshot_key:
        query["snapshotKey"] = snapshot_key
    if platform:
        query["platform"] = platform
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("pageSize", 25)), 1), 100)
    skip = (page - 1) * page_size
    total = store.rankings.count_documents(query)
    items = list(store.rankings.find(query=query, sort=[("generatedAt", -1)], skip=skip, limit=page_size))
    return jsonify({"items": items, "page": page, "pageSize": page_size, "total": total})


@app.route("/api/profile")
def api_profile():
    platform = request.args.get("platform", "")
    platform_id = request.args.get("platformId", "")
    if not platform or not platform_id:
        return jsonify({"error": "platform and platformId are required"}), 400
    doc = store.platform_stats.find_one({"platform": platform, "platformId": platform_id})
    if not doc:
        return jsonify({"error": "profile not found"}), 404
    return jsonify(doc)


@app.route("/api/monthly-winner")
def api_monthly_winner():
    doc = store.monthly_stats.find_one(sort=[("generatedAt", -1)])
    if not doc:
        return jsonify({"error": "no monthly stats available"}), 404
    return jsonify(doc)


@app.route("/api/weekly-winner")
def api_weekly_winner():
    doc = store.weekly_stats.find_one(sort=[("generatedAt", -1)])
    if not doc:
        return jsonify({"error": "no weekly stats available"}), 404
    return jsonify(doc)


@app.route("/api/yearly-winner")
def api_yearly_winner():
    doc = store.yearly_stats.find_one(sort=[("generatedAt", -1)])
    if not doc:
        return jsonify({"error": "no yearly stats available"}), 404
    return jsonify(doc)


@app.route("/api/monthly/run", methods=["POST"])
def api_run_monthly():
    report = generate_monthly_report()
    if not report:
        return jsonify({"error": "no data available"}), 404
    return jsonify(report)


@app.route("/api/fetch-history")
def api_fetch_history():
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("pageSize", 25)), 1), 100)
    skip = (page - 1) * page_size
    query = {}
    status = request.args.get("status")
    class_id = request.args.get("classId")
    if status:
        query["status"] = status
    if class_id:
        query["classId"] = class_id
    total = store.fetch_history.count_documents(query)
    items = list(store.fetch_history.find(query=query, sort=[("createdAt", -1)], skip=skip, limit=page_size))
    return jsonify({"items": items, "page": page, "pageSize": page_size, "total": total})


@app.route("/api/jobs")
def api_jobs():
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("pageSize", 25)), 1), 100)
    skip = (page - 1) * page_size
    query = {}
    status = request.args.get("status")
    if status:
        query["status"] = status
    total = store.jobs.count_documents(query)
    items = list(store.jobs.find(query=query, sort=[("updatedAt", -1)], skip=skip, limit=page_size))
    return jsonify({"items": items, "page": page, "pageSize": page_size, "total": total})


@app.route("/api/stats")
def api_stats():
    collection = request.args.get("collection", "platform")
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("pageSize", 25)), 1), 100)
    skip = (page - 1) * page_size
    query = {}
    class_id = request.args.get("classId")
    platform = request.args.get("platform")
    start_date = request.args.get("startDate")
    end_date = request.args.get("endDate")
    if class_id:
        query["classId"] = class_id
    if platform:
        query["platform"] = platform
    if collection == "students":
        total = store.students.count_documents(query)
        items = store.students.find(query=query, sort=[("createdAt", -1)], skip=skip, limit=page_size)
    else:
        total = store.platform_stats.count_documents(query)
        items = store.platform_stats.find(query=query, sort=[("fetchDate", -1)], skip=skip, limit=page_size)
    return jsonify({"items": list(items), "page": page, "pageSize": page_size, "total": total})


@app.route("/api/history", methods=["DELETE"])
def api_delete_history():
    store.fetch_history.delete_many({})
    store.fetch_logs.delete_many({})
    return jsonify({"status": "deleted"})


@app.route("/api/classes", methods=["GET", "POST"])
def api_classes():
    if request.method == "GET":
        return jsonify({"items": class_repo.find(sort=[("createdAt", -1)])})
    payload = request.get_json(silent=True) or {}
    if not payload.get("className"):
        return jsonify({"error": "className is required"}), 400
    return jsonify(class_repo.create_class(payload)), 201


@app.route("/api/classes/<class_id>", methods=["GET", "PUT", "DELETE"])
def api_class_detail(class_id):
    if request.method == "GET":
        doc = class_repo.find_one({"classId": class_id})
        return (jsonify(doc), 200) if doc else (jsonify({"error": "not found"}), 404)
    if request.method == "DELETE":
        store.students.delete_many({"classId": class_id})
        store.classes.delete_many({"classId": class_id})
        return jsonify({"status": "deleted"})
    payload = request.get_json(silent=True) or {}
    updated = class_repo.update_one({"classId": class_id}, payload, upsert=False)
    return jsonify(updated or {"error": "not found"})


@app.route("/api/classes/<class_id>/students", methods=["GET", "POST", "DELETE"])
def api_class_students(class_id):
    if request.method == "GET":
        return jsonify({"items": student_repo.find({"classId": class_id}, sort=[("createdAt", -1)])})
    if request.method == "DELETE":
        store.students.delete_many({"classId": class_id})
        return jsonify({"status": "deleted"})
    payload = request.get_json(silent=True) or {}
    payload["classId"] = class_id
    if not payload.get("studentName"):
        return jsonify({"error": "studentName is required"}), 400
    return jsonify(student_repo.create_student(payload)), 201


# =====================================================
# TOPPER CALCULATOR
# =====================================================

@app.route("/topper", methods=["GET", "POST"])
def topper():

    if request.method == "GET":
        return render_template("topper.html", result=None, error=None)

    result = None
    error = None

    try:
        file = request.files.get("sheet")
        platform = request.form.get("platform")
        month_raw = request.form.get("month")

        if not file or not file.filename:
            error = "Upload an Excel file"
            return render_template("topper.html", result=None, error=error)

        if not platform:
            error = "Select a platform"
            return render_template("topper.html", result=None, error=error)

        if not month_raw:
            error = "Select a month"
            return render_template("topper.html", result=None, error=error)

        month = int(month_raw)

        df = pd.read_excel(file)

        top = compute_topper(df, platform, month)

        if top is None or top.empty:
            error = "No records found for selected month"
        else:
            result = top.to_dict("records")

    except Exception as e:
        error = str(e)

    return render_template("topper.html", result=result, error=error)


# =====================================================
# GLOBAL ERROR HANDLING
# =====================================================

@app.errorhandler(500)
def internal_error(e):
    return render_template(
        "index.html", 
        error="A critical error occurred. Please check your input or try again later."
    ), 500

@app.errorhandler(Exception)
def handle_exception(e):
    # pass through HTTP errors
    if hasattr(e, 'code') and e.code < 500:
        return e
    
    # now you're handling non-HTTP exceptions only
    print("Unhandled Exception:", e)
    return render_template(
        "index.html", 
        error=f"Unsuspected error: {str(e)}"
    ), 500


# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    app.run(debug=True)
