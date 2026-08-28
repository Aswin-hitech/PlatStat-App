import io
import pandas as pd
from datetime import datetime
from services.class_service import ClassService
from services.student_service import StudentService
from services.topper_service import compute_topper, clean_excel
from services.notification_service import notification_manager
from services.contest_service import contest_service
from services.ranking_service import compute_rankings
from repositories import ClassRepository, StudentRepository, ReminderRepository, ContestRepository


def test_class_lifecycle():
    service = ClassService()
    
    # 1. Create Class
    created = service.create_class({
        'className': 'AI & ML Final Year',
        'academicYear': '4th Year',
        'department': 'Artificial Intelligence',
        'college': 'Tata Tech Institute',
        'section': 'A',
        'description': 'Production batch testing',
        'createdBy': 'QA Lead',
        'academicBatch': '2023-2027'
    })
    assert created is not None
    class_id = str(created['_id'])
    assert created['className'] == 'AI & ML Final Year'
    assert created['studentCount'] == 0
    
    # 2. Get Class
    found = service.get_class(class_id)
    assert found is not None
    assert str(found['_id']) == class_id
    
    # 3. List Classes
    classes = service.list_classes(search='Final Year')
    assert any(str(c['_id']) == class_id for c in classes)
    
    # 4. Update Class
    service.update_class(class_id, {'description': 'Updated Description for QA'})
    updated = service.get_class(class_id)
    assert updated['description'] == 'Updated Description for QA'
    
    # 5. Archive & Restore Class
    service.archive_class(class_id)
    archived_list = service.list_classes(archived=True)
    assert any(str(c['_id']) == class_id for c in archived_list)
    
    service.restore_class(class_id)
    active_list = service.list_classes(archived=False)
    assert any(str(c['_id']) == class_id for c in active_list)
    
    # 6. Delete Class
    service.delete_class(class_id)
    deleted = service.get_class(class_id)
    assert deleted is None


def test_student_service_and_import_export():
    class_service = ClassService()
    student_service = StudentService()
    
    # Setup test class
    cls = class_service.create_class({
        'className': 'CSE 3rd Year Beta',
        'academicYear': '3rd Year',
        'department': 'CSE',
        'college': 'Tata Institute'
    })
    class_id = str(cls['_id'])
    
    # 1. Add Single Student
    res1 = student_service.add_single_student(class_id, {
        'studentName': 'Rahul Sharma',
        'registerNo': 'TATA2026_01',
        'department': 'CSE',
        'codeforces': 'rahul_cf',
        'codechef': 'rahul_cc',
        'leetcode': 'rahul_lc'
    })
    assert res1['status'] == 'inserted'
    st_id = res1['student']['studentId']
    
    # 2. Duplicate Detection
    res_dup = student_service.add_single_student(class_id, {
        'studentName': 'Rahul Sharma',
        'registerNo': 'TATA2026_01'
    })
    assert res_dup['status'] == 'skipped'
    
    # 3. Edit Student
    student_service.edit_student(st_id, {'department': 'Information Technology'})
    students, total = student_service.find_by_class(class_id)
    assert total == 1
    assert students[0]['department'] == 'Information Technology'
    
    # 4. Import from CSV
    csv_content = io.StringIO(
        'Name,Register No,Department,Codeforces,CodeChef,LeetCode\n'
        'Priya Patel,TATA2026_02,CSE,priya_cf,priya_cc,priya_lc\n'
        'Amit Verma,TATA2026_03,CSE,amit_cf,amit_cc,amit_lc\n'
    )
    import_res = student_service.import_students_from_file(class_id, csv_content, 'csv')
    assert import_res['inserted'] == 2
    assert import_res['failed'] == 0
    
    # 5. Export to Excel
    excel_stream = student_service.export_students_to_excel(class_id)
    assert excel_stream is not None
    df_exp = pd.read_excel(excel_stream)
    assert len(df_exp) == 3
    assert 'Student Name' in df_exp.columns
    assert 'Register No' in df_exp.columns
    
    # 6. Delete Student
    del_res = student_service.delete_student(st_id)
    assert del_res['status'] == 'deleted'
    students_after, total_after = student_service.find_by_class(class_id)
    assert total_after == 2
    
    # Cleanup class
    class_service.delete_class(class_id)


def test_topper_service():
    sample_data = {
        'Name of the Student': ['Alice', 'Bob', 'Charlie', 'Alice'],
        'Date': ['28.08.2026', '15.08.2026', '10.08.2026', '20.07.2026'],
        'Contest Rating': [1800, 1950, 1600, 1750],
        'Current Rating': [1700, 1850, 1500, 1650]
    }
    df = pd.DataFrame(sample_data)
    
    # August (month 8) LeetCode Toppers
    ranked_lc = compute_topper(df, 'leetcode', 8)
    assert not ranked_lc.empty
    assert ranked_lc.iloc[0]['Name of the Student'] == 'Bob'
    assert ranked_lc.iloc[0]['Contest Rating'] == 1950
    assert ranked_lc.iloc[1]['Name of the Student'] == 'Alice'
    assert ranked_lc.iloc[1]['Contest Rating'] == 1800
    
    # August (month 8) Codeforces Toppers
    ranked_cf = compute_topper(df, 'codeforces', 8)
    assert not ranked_cf.empty
    assert ranked_cf.iloc[0]['Name of the Student'] == 'Bob'
    assert ranked_cf.iloc[0]['Current Rating'] == 1850


def test_notification_manager():
    notification_manager.clear_all('test_user')
    
    # Send test notifications
    notification_manager.send_notification(
        user_id='test_user',
        title='System Ready',
        message='PlatStat is running in production mode',
        n_type='info'
    )
    
    items, unread = notification_manager.get_user_notifications('test_user')
    assert len(items) == 1
    assert unread == 1
    assert items[0]['title'] == 'System Ready'
    
    # Mark read
    notification_manager.mark_read('test_user', items[0]['notificationId'])
    items_after, unread_after = notification_manager.get_user_notifications('test_user')
    assert unread_after == 0
    
    # Clear all
    notification_manager.clear_all('test_user')
    items_cleared, _ = notification_manager.get_user_notifications('test_user')
    assert len(items_cleared) == 0


def test_contest_service_features():
    # Toggle favorite
    contest_service.toggle_favorite('test_user_c', 'lc_weekly_400', 'leetcode', favorite=True)
    reminders = contest_service.reminder_repo.get_user_reminders('test_user_c')
    assert any(r['contestId'] == 'lc_weekly_400' and r.get('favorite') for r in reminders)
    
    # Subscribe reminder
    contest_service.subscribe_reminder('test_user_c', 'lc_weekly_400', 'leetcode', ['1h', '30m'])
    reminders_sub = contest_service.reminder_repo.get_user_reminders('test_user_c')
    target = next((r for r in reminders_sub if r['contestId'] == 'lc_weekly_400'), None)
    assert target is not None
    assert '1h' in target['intervals']
    
    # Unsubscribe reminder
    contest_service.unsubscribe_reminder('test_user_c', 'lc_weekly_400')
    reminders_unsub = contest_service.reminder_repo.get_user_reminders('test_user_c')
    assert not any(r['contestId'] == 'lc_weekly_400' for r in reminders_unsub)
