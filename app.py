from flask import Flask, render_template, request, send_file

from parsers.csv_parser import parse_csv
from services.codeforces_service import get_cf_summary
from services.codechef_service import get_cc_summary
from services.leetcode_service import get_lc_summary
from utils.excel_writer import build_excel

app = Flask(__name__)

cache_tables = {"codeforces": [], "codechef": [], "leetcode": []}


@app.route("/", methods=["GET", "POST"])
def index():

    if request.method == "POST":

        codeforces_table = []
        codechef_table = []
        leetcode_table = []

        csv_file = request.files.get("csvfile")

        if csv_file and csv_file.filename:
            rows = parse_csv(csv_file)
        else:
            rows = [{
                "name": request.form.get("name"),
                "register_no": request.form.get("register_no"),
                "department": request.form.get("department"),
                "codeforces": request.form.get("codeforces"),
                "codechef": request.form.get("codechef"),
                "leetcode": request.form.get("leetcode"),
            }]

        for i, row in enumerate(rows, start=1):

            if not row or not row.get("name"):
                continue

            name = row.get("name")
            regno = row.get("register_no")
            dept = row.get("department")

            codeforces_id = (row.get("codeforces") or "").strip()
            codechef_id = (row.get("codechef") or "").strip()
            leetcode_id = (row.get("leetcode") or "").strip()

            if codeforces_id:
                r = get_cf_summary(i, name, regno, dept, codeforces_id)
                if r:
                    codeforces_table.append(r)

            if codechef_id:
                r = get_cc_summary(i, name, regno, dept, codechef_id)
                if r:
                    codechef_table.append(r)

            if leetcode_id:
                r = get_lc_summary(i, name, regno, dept, leetcode_id)
                if r:
                    leetcode_table.append(r)

        global cache_tables
        cache_tables = {
            "codeforces": codeforces_table,
            "codechef": codechef_table,
            "leetcode": leetcode_table
        }

        return render_template(
            "results.html",
            codeforces=codeforces_table,
            codechef=codechef_table,
            leetcode=leetcode_table
        )

    return render_template("index.html")


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


if __name__ == "__main__":
    app.run(debug=True)
