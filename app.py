from io import BytesIO

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory

from parsers.csv_parser import parse_csv
from parsers.excel_parser import parse_excel
from services.codechef_service import get_cc_summary, get_latest_cc_contests
from services.codeforces_service import get_cf_summary
from services.contest_scheduler import contest_scheduler
from services.contest_service import contest_service
from services.leetcode_service import find_latest_lc_contest, get_lc_summary, get_latest_lc_contests
from services.notification_service import notification_manager
from services.student_service import StudentService
from services.topper_service import compute_topper
from utils.date_utils import get_export_filename
from utils.excel_utils import create_excel_file

try:
    contest_scheduler.start()
except Exception as _e:
    pass


app = Flask(__name__)


cache_tables = {
    "codeforces": [],
    "codechef": [],
    "leetcode": [],
}


def _clean_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _selected_platforms(form):
    selected = []
    for platform in ("codeforces", "codechef", "leetcode"):
        if form.get(f"platform_{platform}"):
            selected.append(platform)
    return selected


def _row_value(row, *keys):
    for key in keys:
        value = _clean_text(row.get(key))
        if value:
            return value
    return ""


def _normalize_rows(rows):
    normalized = []
    for row in rows:
        normalized.append(
            {
                "name": _row_value(row, "name", "studentName"),
                "studentName": _row_value(row, "studentName", "name"),
                "register_no": _row_value(row, "register_no", "registerNo"),
                "registerNo": _row_value(row, "registerNo", "register_no"),
                "department": _row_value(row, "department", "dept"),
                "codeforces": _row_value(row, "codeforces"),
                "codechef": _row_value(row, "codechef"),
                "leetcode": _row_value(row, "leetcode"),
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


def _analyze_rows(rows, selected_platforms, selected_lc_title=None, selected_lc_time=None, selected_cc_title=None, selected_cc_date=None):
    tables = {"codeforces": [], "codechef": [], "leetcode": []}

    latest_lc_title = selected_lc_title
    latest_lc_time = selected_lc_time
    if "leetcode" in selected_platforms and not latest_lc_title:
        latest_lc_title, latest_lc_time = find_latest_lc_contest(rows)

    for idx, row in enumerate(rows, start=1):
        name = _clean_text(row.get("name") or row.get("studentName"))
        regno = _clean_text(row.get("register_no") or row.get("registerNo"))
        dept = _clean_text(row.get("department"))

        if not name:
            continue

        if "codeforces" in selected_platforms:
            handle = _clean_text(row.get("codeforces"))
            if handle:
                tables["codeforces"].append(get_cf_summary(idx, name, regno, dept, handle))

        if "codechef" in selected_platforms:
            handle = _clean_text(row.get("codechef"))
            if handle:
                tables["codechef"].append(get_cc_summary(idx, name, regno, dept, handle, target_contest_title=selected_cc_title, target_contest_date=selected_cc_date))

        if "leetcode" in selected_platforms:
            handle = _clean_text(row.get("leetcode"))
            if handle:
                tables["leetcode"].append(
                    get_lc_summary(
                        idx,
                        name,
                        regno,
                        dept,
                        handle,
                        latest_lc_title,
                        latest_lc_time,
                    )
                )

    return tables


def _combined_export_frame(tables):
    frames = []
    for platform, rows in tables.items():
        if not rows:
            continue
        frame = pd.DataFrame(rows).copy()
        frame.insert(0, "Platform", platform.capitalize())
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _tables_to_excel_stream(tables):
    output = BytesIO()
    sections = [
        ("Codeforces", tables.get("codeforces", [])),
        ("CodeChef", tables.get("codechef", [])),
        ("LeetCode", tables.get("leetcode", [])),
    ]

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        workbook = writer.book
        worksheet = workbook.create_sheet("Results")
        writer.sheets["Results"] = worksheet

        row_cursor = 0
        for section_name, rows in sections:
            worksheet.cell(row=row_cursor + 1, column=1, value=f"{section_name}:")
            row_cursor += 1

            if rows:
                frame = pd.DataFrame(rows)
                frame.to_excel(writer, sheet_name="Results", startrow=row_cursor, index=False)
                row_cursor += len(frame) + 3
            else:
                worksheet.cell(row=row_cursor + 1, column=1, value="No data found")
                row_cursor += 3

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


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template("index.html")

    selected_platforms = _selected_platforms(request.form)
    if not selected_platforms:
        return render_template("index.html", error="Select at least one platform to track."), 400

    selected_lc_title = None
    selected_lc_time = None
    if "leetcode" in selected_platforms:
        lc_contest_val = _clean_text(request.form.get("leetcode_contest"))
        if not lc_contest_val:
            return render_template("index.html", error="Please select a LeetCode contest before fetching rankings."), 400

        try:
            contests = get_latest_lc_contests(6)
            matched = next((c for c in contests if c["title"] == lc_contest_val or c["titleSlug"] == lc_contest_val), None)
            if matched:
                selected_lc_title = matched["title"]
                selected_lc_time = matched["startTime"]
            else:
                selected_lc_title = lc_contest_val
                selected_lc_time = 0
        except Exception as e:
            return render_template("index.html", error=f"Failed to fetch LeetCode contests from API: {str(e)}"), 500

    selected_cc_title = None
    selected_cc_date = None
    if "codechef" in selected_platforms:
        selected_cc_title = _clean_text(request.form.get("codechef_contest"))
        if selected_cc_title:
            try:
                cc_contests = get_latest_cc_contests(10)
                matched_cc = next((c for c in cc_contests if c["title"] == selected_cc_title), None)
                if matched_cc:
                    selected_cc_date = matched_cc["date"]
            except Exception:
                pass

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

    tables = _analyze_rows(rows, selected_platforms, selected_lc_title, selected_lc_time, selected_cc_title, selected_cc_date)

    global cache_tables
    cache_tables = tables

    return render_template(
        "results.html",
        codeforces=tables["codeforces"],
        codechef=tables["codechef"],
        leetcode=tables["leetcode"],
        selected_platforms=selected_platforms,
    )


@app.route("/download")
def download():
    export_format = request.args.get("format", "xlsx").lower()
    requested_platform = request.args.get("platform", "").lower().strip()

    has_data = any(cache_tables.get(key) for key in ("codeforces", "codechef", "leetcode"))
    if not has_data:
        return "No data to download.", 404

    active_platforms = [k for k, v in cache_tables.items() if v]

    if requested_platform and cache_tables.get(requested_platform):
        platform_name = requested_platform
        export_tables = {requested_platform: cache_tables[requested_platform]}
    else:
        if len(active_platforms) == 1:
            platform_name = active_platforms[0]
        else:
            platform_name = requested_platform if requested_platform else "platstat"
        export_tables = cache_tables

    filename = get_export_filename(platform_name=platform_name, extension=export_format)

    if export_format == "csv":
        frame = _combined_export_frame(export_tables)
        output = BytesIO()
        output.write(frame.to_csv(index=False).encode("utf-8"))
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv",
        )

    excel_file = _tables_to_excel_stream(export_tables)
    return send_file(
        excel_file,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/classes/<class_id>/students/export", methods=["GET"])
def export_class_students(class_id):
    export_format = request.args.get("format", "xlsx").lower()
    platform_name = request.args.get("platform", "platstat").lower().strip()
    student_service = StudentService()
    excel_stream = student_service.export_students_to_excel(class_id)
    if not excel_stream:
        return "No student records found.", 404
    filename = get_export_filename(platform_name=platform_name, extension=export_format)
    if export_format == "csv":
        df = pd.read_excel(excel_stream)
        csv_output = BytesIO()
        csv_output.write(df.to_csv(index=False).encode("utf-8"))
        csv_output.seek(0)
        return send_file(
            csv_output,
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv",
        )
    return send_file(
        excel_stream,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


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


@app.route("/api/contests/sync", methods=["POST"])
def sync_contests():
    res = contest_service.sync_contests()
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
    if hasattr(e, "code") and e.code < 500:
        return e
    return render_template("index.html", error=f"Unexpected error: {str(e)}"), 500


if __name__ == "__main__":
    app.run(debug=True)
