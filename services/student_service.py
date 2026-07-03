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
    def find_by_class(self, class_id, search="", page=1, page_size=25):
        """Return a list of students for a class with pagination and optional search.
        Returns (students, total_count)."""
        return student_repo.find_by_class(class_id, search=search, page=page, page_size=page_size)


    def add_single_student(self, class_id, student_data):
        # Store class reference as ObjectId
        student_data["classId"] = ObjectId(class_id)
        existing_student = student_repo.find_duplicate(
            class_id,
            register_no=student_data.get("registerNo"),
            name=student_data.get("studentName")
        )
        if existing_student:
            return {"status": "skipped", "reason": "Duplicate student", "student": existing_student}
        new_student = student_repo.create_student(student_data)
        class_repo.refresh_student_count(class_id)
        return {"status": "inserted", "student": new_student}

    def import_students_from_file(self, class_id, file_content, file_type, update_existing=False):
        if file_type == "csv":
            df = pd.read_csv(file_content)
        elif file_type == "excel":
            df = pd.read_excel(file_content)
        else:
            raise ValueError("Unsupported file type")

        # Validate required columns (add more as needed)
        required_columns = ["studentName", "registerNo"]
        if not all(col in df.columns for col in required_columns):
            raise ValueError(f"Missing required columns. Expected: {', '.join(required_columns)}")

        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        failed_rows = []

        for index, row in df.iterrows():
            student_data = row.to_dict()
            student_data["classId"] = ObjectId(class_id)
            student_data["studentName"] = (student_data.get("studentName") or "").strip()
            student_data["registerNo"] = (student_data.get("registerNo") or "").strip()

            if not student_data["studentName"] or not student_data["registerNo"]:
                failed_count += 1
                failed_rows.append({"row": index + 2, "reason": "Missing studentName or registerNo"})
                continue

            existing_student = student_repo.find_duplicate(
                class_id,
                register_no=student_data["registerNo"],
                name=student_data["studentName"]
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
            "classId": ObjectId(class_id),
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
        return student_repo.update_one({"studentId": student_id}, student_data)

    def delete_student(self, student_id):
        student_repo.delete({"studentId": student_id})
        # Optionally, refresh student count for the class
        # class_repo.refresh_student_count(class_id_of_student)
        return {"status": "deleted"}

    def export_students_to_excel(self, class_id):
        students = student_repo.find({"classId": class_id})
        if not students:
            return None
        df = pd.DataFrame(list(students))
        # Remove MongoDB _id field if present
        if "_id" in df.columns:
            df = df.drop(columns=["_id"])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Students", index=False)
        output.seek(0)
        return output
