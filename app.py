from flask import Flask, render_template, request, send_file

from parsers.csv_parser import parse_csv
from services.codeforces_service import get_cf_summary
from services.codechef_service import get_cc_summary
from services.leetcode_service import get_lc_summary
from utils.excel_writer import build_excel

app = Flask(__name__)

# cache last generated tables for download
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

    if request.method == "POST":

        codeforces_table = []
        codechef_table = []
        leetcode_table = []

        csv_file = request.files.get("csvfile")

        # ---------------------------------------------
        # INPUT SOURCE — CSV OR FORM
        # ---------------------------------------------

        if csv_file and csv_file.filename:
            rows = parse_csv(csv_file)
        else:
            rows = [{
                "name": request.form.get("name", "").strip(),
                "register_no": request.form.get("register_no", "").strip(),
                "department": request.form.get("department", "").strip(),
                "codeforces": request.form.get("codeforces", "").strip(),
                "codechef": request.form.get("codechef", "").strip(),
                "leetcode": request.form.get("leetcode", "").strip(),
            }]

        # ---------------------------------------------
        # PROCESS EACH STUDENT
        # ---------------------------------------------

        for i, row in enumerate(rows, start=1):

            if not row:
                continue

            name = (row.get("name") or "").strip()
            if not name:
                continue

            regno = (row.get("register_no") or "").strip()
            dept = (row.get("department") or "").strip()

            codeforces_id = (row.get("codeforces") or "").strip()
            codechef_id = (row.get("codechef") or "").strip()
            leetcode_id = (row.get("leetcode") or "").strip()

            # -------------------------
            # Codeforces
            # -------------------------

            if codeforces_id:
                try:
                    r = get_cf_summary(
                        i, name, regno, dept, codeforces_id
                    )
                    if r:
                        codeforces_table.append(r)
                except Exception as e:
                    print("CF call failed:", e)

            # -------------------------
            # CodeChef
            # -------------------------

            if codechef_id:
                try:
                    r = get_cc_summary(
                        i, name, regno, dept, codechef_id
                    )
                    if r:
                        codechef_table.append(r)
                except Exception as e:
                    print("CC call failed:", e)

            # -------------------------
            # LeetCode
            # -------------------------

            if leetcode_id:
                try:
                    r = get_lc_summary(
                        i, name, regno, dept, leetcode_id
                    )
                    if r:
                        leetcode_table.append(r)
                except Exception as e:
                    print("LC call failed:", e)

        # ---------------------------------------------
        # CACHE RESULTS
        # ---------------------------------------------

        global cache_tables
        cache_tables = {
            "codeforces": codeforces_table,
            "codechef": codechef_table,
            "leetcode": leetcode_table
        }

        # ---------------------------------------------
        # SHOW RESULTS
        # ---------------------------------------------

        return render_template(
            "results.html",
            codeforces=codeforces_table,
            codechef=codechef_table,
            leetcode=leetcode_table
        )

    # GET request
    return render_template("index.html")


# =====================================================
# DOWNLOAD EXCEL
# =====================================================

@app.route("/download")
def download():

    if not any(cache_tables.values()):
        return "No data to download."

    file_path = build_excel(
        cache_tables["codeforces"],
        cache_tables["codechef"],
        cache_tables["leetcode"]
    )

    return send_file(file_path, as_attachment=True)


# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    app.run(debug=True)
