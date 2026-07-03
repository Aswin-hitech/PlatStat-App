from flask import Flask, jsonify, render_template, request, send_file
import pandas as pd
from datetime import datetime
from parsers.csv_parser import parse_csv
from parsers.excel_parser import parse_excel
from services.codeforces_service import get_cf_summary
from services.codechef_service import get_cc_summary
from services.leetcode_service import get_lc_summary
from services.topper_service import compute_topper
from utils.excel_writer import build_excel
from utils.excel_utils import create_excel_file
from db import store
from services.fetch_engine import fetch_engine
from services.ranking_service import compute_rankings
from services.monthly_service import generate_monthly_report
from repositories import HistoryRepository
from services.class_service import ClassService
from services.student_service import StudentService
from utils.ranking_utils import month_key, week_key, year_key

app = Flask(__name__)
class_service = ClassService()
student_service = StudentService()
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

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    classes = class_service.list_classes()
    return render_template("dashboard.html", classes=classes)


@app.route("/class/<class_id>")
def class_detail(class_id):
    cls = class_service.get_class(class_id)
    if not cls:
        return jsonify({"error": "Class not found"}), 404
    students, total_students = student_service.find_by_class(class_id)
    return render_template("class_detail.html", class_data=cls, students=students, total_students=total_students)


@app.route("/api/classes", methods=["GET", "POST"])
def api_classes():
    if request.method == "GET":
        search_query = request.args.get("search", "")
        archived = request.args.get("archived", "false").lower() == "true"
        classes = class_service.list_classes(archived=archived, search=search_query)
        return jsonify({"items": classes})
    payload = request.get_json(silent=True) or {}
    if not payload.get("className"):
        return jsonify({"error": "className is required"}), 400
    new_class = class_service.create_class(payload)
    return jsonify(new_class), 201


@app.route("/api/classes/<class_id>", methods=["GET", "PUT", "DELETE"])
def api_class_detail(class_id):
    if request.method == "GET":
        cls = class_service.get_class(class_id)
        return (jsonify(cls), 200) if cls else (jsonify({"error": "not found"}), 404)
    if request.method == "DELETE":
        class_service.delete_class(class_id)
        return jsonify({"status": "deleted"})
    payload = request.get_json(silent=True) or {}
    updated = class_service.update_class(class_id, payload)
    return jsonify(updated or {"error": "not found"})


@app.route("/api/classes/<class_id>/archive", methods=["POST"])
def api_archive_class(class_id):
    updated = class_service.archive_class(class_id)
    return jsonify(updated or {"error": "not found"})


@app.route("/api/classes/<class_id>/restore", methods=["POST"])
def api_restore_class(class_id):
    updated = class_service.restore_class(class_id)
    return jsonify(updated or {"error": "not found"})


@app.route("/api/classes/<class_id>/students", methods=["GET", "POST"])
def api_class_students(class_id):
    if request.method == "GET":
        search_query = request.args.get("search", "")
        page = max(int(request.args.get("page", 1)), 1)
        page_size = max(1, min(int(request.args.get("pageSize", 25)), 100))
        students, total = student_service.find_by_class(class_id, search_query, page, page_size)
        return jsonify({"items": students, "total": total, "page": page, "pageSize": page_size})
    payload = request.get_json(silent=True) or {}
    if not payload.get("studentName") or not payload.get("registerNo"):
        return jsonify({"error": "studentName and registerNo are required"}), 400
    result = student_service.add_single_student(class_id, payload)
    if result["status"] == "skipped":
        return jsonify({"error": "Duplicate student", "student": result["student"]}), 409
    return jsonify(result["student"]), 201


@app.route("/api/students/<student_id>", methods=["PUT", "DELETE"])
def api_student_detail(student_id):
    if request.method == "PUT":
        payload = request.get_json(silent=True) or {}
        updated = student_service.edit_student(student_id, payload)
        return jsonify(updated or {"error": "not found"}), 200 if updated else 404
    if request.method == "DELETE":
        result = student_service.delete_student(student_id)
        return jsonify(result), 200


@app.route("/api/classes/<class_id>/students/import", methods=["POST"])
def api_import_students(class_id):
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    file_extension = file.filename.split(".").pop().lower()
    if file_extension == "csv":
        file_type = "csv"
    elif file_extension in ["xlsx", "xls"]:
        file_type = "excel"
    else:
        return jsonify({"error": "Unsupported file type"}), 400

    update_existing = request.form.get("updateExisting", "false").lower() == "true"

    try:
        import_summary = student_service.import_students_from_file(class_id, file, file_type, update_existing)
        return jsonify(import_summary), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Import error: {e}")
        return jsonify({"error": "Failed to import students"}), 500


@app.route("/api/classes/<class_id>/students/export", methods=["GET"])
def api_export_students(class_id):
    excel_file = student_service.export_students_to_excel(class_id)
    if excel_file:
        filename = f"students_{class_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
        return send_file(
            excel_file,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    return jsonify({"error": "No students found for this class"}), 404


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    payload = request.get_json(silent=True) or {}
    class_id = payload.get("classId") or ""
    rows = payload.get("rows") or []
    if class_id and not rows:
        # Fetch all students for the given class_id if no rows are provided
        students, _ = student_service.find_by_class(class_id)
        # Convert student objects to the format expected by fetch_engine (list of dicts with platform IDs)
        rows = []
        for student in students:
            s_row = {
                "name": student.get("studentName"),
                "register_no": student.get("registerNo"),
                "department": student.get("department"),
                "codeforces": student.get("platformIds", {}).get("codeforces"),
                "codechef": student.get("platformIds", {}).get("codechef"),
                "leetcode": student.get("platformIds", {}).get("leetcode"),
            }
            rows.append(s_row)

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
        students, _ = student_service.find_by_class(class_id)
        rows = []
        for student in students:
            s_row = {
                "name": student.get("studentName"),
                "register_no": student.get("registerNo"),
                "department": student.get("department"),
                "codeforces": student.get("platformIds", {}).get("codeforces"),
                "codechef": student.get("platformIds", {}).get("codechef"),
                "leetcode": student.get("platformIds", {}).get("leetcode"),
            }
            rows.append(s_row)

    job = fetch_engine.create_job(rows, class_id=class_id)
    return jsonify({
        "jobId": job["jobId"],
        "status": job["status"],
        "processed": job.get("processed", 0),
        "success": job.get("success", 0),
        "failed": job.get("failed", 0),
        "skipped": job.get("skipped", 0),
    })


@app.route("/api/rankings")
def api_rankings():
    period = request.args.get("period")
    platform = request.args.get("platform")
    class_id = request.args.get("classId", "global")  # Default to global rankings
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("pageSize", 25)), 1), 100)
    skip = (page - 1) * page_size
    query = {"classId": class_id}
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
    class_id = request.args.get("classId", "global")
    query = {"classId": class_id}
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


@app.route("/api/stats")
def api_stats():
    collection_name = request.args.get("collection", "platform_stats")
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
    # TODO: Add date filtering

    collection = store.collection(collection_name)
    total = collection.count_documents(query)
    items = list(collection.find(query=query, sort=[("createdAt", -1)], skip=skip, limit=page_size))
    return jsonify({"items": items, "page": page, "pageSize": page_size, "total": total})


@app.route("/api/reports/<class_id>/<report_type>", methods=["GET"])
def api_reports(class_id, report_type):
    class_obj = class_service.get_class(class_id)
    if not class_obj:
        return jsonify({"error": "Class not found"}), 404

    dfs = []
    sheet_names = []

    if report_type == "latest_fetch" or report_type == "complete_class":
        platform_stats = store.platform_stats.find(
            {"classId": class_id, "fetchDate": {"$exists": True}},
            sort=[("fetchDate", -1)]
        ).limit(100) # Limit to a reasonable number for 

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


@app.route("/api/history", methods=["DELETE"])
def api_delete_history():
    store.fetch_history.delete_many({})
    store.fetch_logs.delete_many({})
    return jsonify({"status": "deleted"})





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

        # compute_topper now returns a dict with 'top5' and 'top10' DataFrames
        top = compute_topper(df, platform, month)
        if not top or not top.get('top5'):
            error = "No records found for selected month"
        else:
            # Convert DataFrames to list of records for template rendering
            result = {
                'top5': top['top5'].to_dict('records'),
                'top10': top['top10'].to_dict('records')
            }

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
