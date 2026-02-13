from flask import Flask, render_template, request, send_file

from parsers.csv_parser import parse_csv
from services.codeforces_service import get_cf_summary
from services.codechef_service import get_cc_summary
from services.leetcode_service import get_lc_summary
from utils.excel_writer import build_excel

app = Flask(__name__)

cache_tables = {"cf": [], "cc": [], "lc": []}


@app.route("/", methods=["GET", "POST"])
def index():

    if request.method == "POST":

        cf_table = []
        cc_table = []
        lc_table = []

        csv_file = request.files.get("csvfile")

        if csv_file and csv_file.filename:
            rows = parse_csv(csv_file)
        else:
            rows = [{
                "name": request.form.get("name"),
                "register_no": request.form.get("register_no"),
                "department": request.form.get("department"),
                "cf": request.form.get("cf"),
                "cc": request.form.get("cc"),
                "lc": request.form.get("lc"),
            }]

        for i, row in enumerate(rows, start=1):

            if not row or not row.get("name"):
                continue

            name = row.get("name")
            regno = row.get("register_no")
            dept = row.get("department")

            cf_id = (row.get("cf") or "").strip()
            cc_id = (row.get("cc") or "").strip()
            lc_id = (row.get("lc") or "").strip()

            if cf_id:
                r = get_cf_summary(i, name, regno, dept, cf_id)
                if r:
                    cf_table.append(r)

            if cc_id:
                r = get_cc_summary(i, name, regno, dept, cc_id)
                if r:
                    cc_table.append(r)

            if lc_id:
                r = get_lc_summary(i, name, regno, dept, lc_id)
                if r:
                    lc_table.append(r)

        global cache_tables
        cache_tables = {
            "cf": cf_table,
            "cc": cc_table,
            "lc": lc_table
        }

        return render_template(
            "results.html",
            cf=cf_table,
            cc=cc_table,
            lc=lc_table
        )

    return render_template("index.html")


@app.route("/download")
def download():

    if not any(cache_tables.values()):
        return "No data to download."

    file_path = build_excel(
        cache_tables["cf"],
        cache_tables["cc"],
        cache_tables["lc"]
    )

    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
