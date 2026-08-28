import uuid
from datetime import datetime
import pandas as pd
from bson import ObjectId
import io
from repositories import StudentRepository, ClassRepository, ImportLogRepository
from db import store

student_repo = StudentRepository()
class_repo = ClassRepository()
import_log_repo = ImportLogRepository()

class StudentService:
    def _to_object_id(self, class_id):
        try:
            if isinstance(class_id, ObjectId):
                return class_id
            return ObjectId(str(class_id))
        except Exception:
            return str(class_id)

    def find_by_class(self, class_id, search="", page=1, page_size=25):
        """Return a list of students for a class with pagination and optional search.
        Returns (students, total_count)."""
        return student_repo.find_by_class(class_id, search=search, page=page, page_size=page_size)

    def add_single_student(self, class_id, student_data):
        oid = self._to_object_id(class_id)
        student_data["classId"] = oid
        reg_no = student_data.get("registerNo") or student_data.get("register_no") or ""
        name = student_data.get("studentName") or student_data.get("name") or ""
        student_data["studentName"] = str(name).strip()
        student_data["registerNo"] = str(reg_no).strip()

        existing_student = student_repo.find_duplicate(
            class_id,
            register_no=student_data["registerNo"],
            name=student_data["studentName"]
        )
        if existing_student:
            return {"status": "skipped", "reason": "Duplicate student", "student": existing_student}
        new_student = student_repo.create_student(student_data)
        class_repo.refresh_student_count(class_id)
        return {"status": "inserted", "student": new_student}

    @staticmethod
    def _normalize_column_name(col):
        clean = str(col).strip().lower().replace(" ", "").replace("_", "").replace(".", "").replace("-", "")
        if clean in ("studentname", "name", "nameofstudent", "fullname", "student"):
            return "studentName"
        if clean in ("registerno", "registernumber", "regno", "rollno", "rollnumber", "regno", "register"):
            return "registerNo"
        if clean in ("department", "dept", "branch"):
            return "department"
        if clean in ("section", "sec"):
            return "section"
        if clean in ("email", "emailid", "mail"):
            return "email"
        if clean in ("codeforces", "codeforcesid", "codeforceshandle", "cf"):
            return "codeforces"
        if clean in ("codechef", "codechefid", "codechefhandle", "cc"):
            return "codechef"
        if clean in ("leetcode", "leetcodeid", "leetcodehandle", "lc"):
            return "leetcode"
        return str(col).strip()

    def import_students_from_file(self, class_id, file_content, file_type, update_existing=False):
        if file_type == "csv":
            df = pd.read_csv(file_content)
        elif file_type in ("excel", "xlsx", "xls"):
            df = pd.read_excel(file_content)
        else:
            raise ValueError("Unsupported file type. Please upload a CSV or Excel file.")

        # Normalize dataframe columns
        rename_map = {col: self._normalize_column_name(col) for col in df.columns}
        df = df.rename(columns=rename_map)

        required_columns = ["studentName", "registerNo"]
        if not all(col in df.columns for col in required_columns):
            missing = [col for col in required_columns if col not in df.columns]
            raise ValueError(f"Missing required columns: {', '.join(missing)}. Please include student name and register number.")

        oid = self._to_object_id(class_id)
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        failed_rows = []

        for index, row in df.iterrows():
            student_data = row.to_dict()
            student_data["classId"] = oid

            name = str(student_data.get("studentName") or "").strip()
            if name.lower() in ("nan", "none", "null"):
                name = ""
            reg_no = str(student_data.get("registerNo") or "").strip()
            if reg_no.lower() in ("nan", "none", "null"):
                reg_no = ""

            student_data["studentName"] = name
            student_data["registerNo"] = reg_no
            student_data["department"] = str(student_data.get("department") or "").strip()
            if student_data["department"].lower() in ("nan", "none"):
                student_data["department"] = ""
            student_data["section"] = str(student_data.get("section") or "").strip()
            if student_data["section"].lower() in ("nan", "none"):
                student_data["section"] = ""
            student_data["codeforces"] = str(student_data.get("codeforces") or "").strip()
            if student_data["codeforces"].lower() in ("nan", "none"):
                student_data["codeforces"] = ""
            student_data["codechef"] = str(student_data.get("codechef") or "").strip()
            if student_data["codechef"].lower() in ("nan", "none"):
                student_data["codechef"] = ""
            student_data["leetcode"] = str(student_data.get("leetcode") or "").strip()
            if student_data["leetcode"].lower() in ("nan", "none"):
                student_data["leetcode"] = ""

            if not name or not reg_no:
                failed_count += 1
                failed_rows.append({"row": index + 2, "reason": "Missing studentName or registerNo"})
                continue

            existing_student = student_repo.find_duplicate(
                class_id,
                register_no=reg_no,
                name=name
            )

            if existing_student:
                if update_existing:
                    student_repo.update_one({"studentId": existing_student["studentId"]}, student_data)
                    updated_count += 1
                else:
                    skipped_count += 1
            else:
                student_repo.create_student(student_data)
                inserted_count += 1

        class_repo.refresh_student_count(class_id)

        import_log_repo.create({
            "classId": oid,
            "importType": file_type,
            "inserted": inserted_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "failedRows": failed_rows,
            "createdAt": datetime.utcnow(),
        })

        return {
            "inserted": inserted_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "failedRows": failed_rows,
        }

    def edit_student(self, student_id, student_data):
        if "studentName" in student_data or "name" in student_data:
            student_data["studentName"] = str(student_data.get("studentName") or student_data.get("name") or "").strip()
        if "registerNo" in student_data or "register_no" in student_data:
            student_data["registerNo"] = str(student_data.get("registerNo") or student_data.get("register_no") or "").strip()
        
        # update platformIds structure if passed flat
        platform_ids = student_data.get("platformIds") or {
            "codeforces": student_data.get("codeforces", ""),
            "codechef": student_data.get("codechef", ""),
            "leetcode": student_data.get("leetcode", ""),
        }
        student_data["platformIds"] = platform_ids
        return student_repo.update_one({"studentId": student_id}, student_data)

    def delete_student(self, student_id):
        student = student_repo.find_one({"studentId": student_id})
        student_repo.delete({"studentId": student_id})
        if student and student.get("classId"):
            class_repo.refresh_student_count(student["classId"])
        return {"status": "deleted"}

    def export_students_to_excel(self, class_id):
        students, _ = student_repo.find_by_class(class_id, page_size=0)
        if not students:
            return None

        export_rows = []
        for idx, st in enumerate(students, start=1):
            plat_ids = st.get("platformIds") or {}
            export_rows.append({
                "S. No": idx,
                "Student Name": st.get("studentName", ""),
                "Register No": st.get("registerNo", ""),
                "Department": st.get("department", ""),
                "Section": st.get("section", ""),
                "Email": st.get("email", ""),
                "Codeforces ID": plat_ids.get("codeforces") or st.get("codeforces", ""),
                "CodeChef ID": plat_ids.get("codechef") or st.get("codechef", ""),
                "LeetCode ID": plat_ids.get("leetcode") or st.get("leetcode", ""),
            })

        df = pd.DataFrame(export_rows)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Students Roster", index=False)
            ws = writer.sheets["Students Roster"]
            # Auto-fit column widths
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        output.seek(0)
        return output

