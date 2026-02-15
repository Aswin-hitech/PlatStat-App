from flask import Flask, render_template, request, send_file
import pandas as pd

from parsers.csv_parser import parse_csv
from services.codeforces_service import get_cf_summary
from services.codechef_service import get_cc_summary
from services.leetcode_service import get_lc_summary
from services.topper_service import compute_topper
from utils.excel_writer import build_excel

app = Flask(__name__)

# store last analysis for download
cache_tables = {
    "codeforces": [],
    "codechef": [],
    "leetcode": []
}


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
        if use_lc and row.get("leetcode"):
            try:
                r = get_lc_summary(i, name, regno, dept, row.get("leetcode").strip())
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
        return "No data to download. Run analysis first."

    try:
        path = build_excel(
            cache_tables.get("codeforces", []),
            cache_tables.get("codechef", []),
            cache_tables.get("leetcode", [])
        )
        return send_file(path, as_attachment=True)
    except Exception as e:
        return f"Excel generation failed: {e}"


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
# RUN
# =====================================================

if __name__ == "__main__":
    app.run(debug=True)
