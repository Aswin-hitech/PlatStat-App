import io
import json
import pytest
from app import app
from services.class_service import ClassService
from services.student_service import StudentService


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_homepage_analyzer_get(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'PlatStat Analyzer' in resp.data or b'Performance & Contest Analytics' in resp.data


def test_dashboard_page(client):
    resp = client.get('/dashboard')
    assert resp.status_code == 200
    assert b'PlatStat Dashboard' in resp.data or b'Your Classes' in resp.data


def test_contests_page(client):
    resp = client.get('/contests')
    assert resp.status_code == 200
    assert b'Unified Contest Center' in resp.data or b'Upcoming Competitive Contests' in resp.data


def test_notifications_page(client):
    resp = client.get('/notifications')
    assert resp.status_code == 200
    assert b'Notification Center' in resp.data or b'Alerts & Reminder History' in resp.data


def test_topper_page_get_and_post(client):
    resp = client.get('/topper')
    assert resp.status_code == 200
    assert b'Monthly Topper Calculator' in resp.data
    
    # Test POST with CSV
    csv_data = (
        'Name of the Student,Date,Contest Rating\n'
        'Student Alpha,15.08.2026,1900\n'
        'Student Beta,20.08.2026,1750\n'
    )
    data = {
        'platform': 'leetcode',
        'month': '8',
        'view_mode': 'both',
        'sheet': (io.BytesIO(csv_data.encode('utf-8')), 'topper_test.csv')
    }
    resp_post = client.post('/topper', data=data, content_type='multipart/form-data')
    assert resp_post.status_code == 200
    assert b'Student Alpha' in resp_post.data


def test_class_crud_api_and_page(client):
    # 1. Create class via API
    create_payload = {
        'className': 'QA Automation Engineering',
        'academicYear': '2026-2027',
        'department': 'Software Quality',
        'college': 'Tata Production Academy',
        'section': 'P1',
        'description': 'End to end validation class'
    }
    resp = client.post('/api/classes', json=create_payload)
    assert resp.status_code == 201
    cls_data = resp.get_json()
    assert cls_data['className'] == 'QA Automation Engineering'
    class_id = cls_data['_id']
    
    # 2. Get class page
    resp_page = client.get(f'/class/{class_id}')
    assert resp_page.status_code == 200
    assert b'QA Automation Engineering' in resp_page.data
    
    # 3. List classes API
    resp_list = client.get('/api/classes')
    assert resp_list.status_code == 200
    assert any(c['_id'] == class_id for c in resp_list.get_json()['classes'])
    
    # 4. Get class API
    resp_get = client.get(f'/api/classes/{class_id}')
    assert resp_get.status_code == 200
    assert resp_get.get_json()['_id'] == class_id
    
    # 5. Update class API
    resp_put = client.put(f'/api/classes/{class_id}', json={'section': 'P2'})
    assert resp_put.status_code == 200
    assert resp_put.get_json()['status'] == 'updated'
    
    # 6. Add student API
    st_payload = {
        'classId': class_id,
        'studentName': 'Vikram Mehta',
        'registerNo': 'TCS_9901',
        'department': 'Software Quality',
        'codeforces': 'vikram_cf',
        'codechef': 'vikram_cc',
        'leetcode': 'vikram_lc'
    }
    resp_st = client.post('/api/students', json=st_payload)
    assert resp_st.status_code == 200
    st_data = resp_st.get_json()
    assert st_data['status'] == 'inserted'
    student_id = st_data['student']['studentId']
    
    # 7. Edit student API
    resp_st_edit = client.put(f'/api/students/{student_id}', json={'department': 'QA Automation'})
    assert resp_st_edit.status_code == 200
    
    # 8. Import students API
    import_csv = (
        'studentName,registerNo,department,codeforces,codechef,leetcode\n'
        'Kavita Sen,TCS_9902,QA,kavita_cf,kavita_cc,kavita_lc\n'
    )
    resp_imp = client.post(
        f'/api/classes/{class_id}/import',
        data={'file': (io.BytesIO(import_csv.encode('utf-8')), 'import.csv')},
        content_type='multipart/form-data'
    )
    assert resp_imp.status_code == 200
    assert resp_imp.get_json()['status'] == 'success'
    
    # 9. Export students API
    resp_exp = client.get(f'/api/classes/{class_id}/students/export?format=xlsx')
    assert resp_exp.status_code == 200
    assert resp_exp.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    resp_exp_csv = client.get(f'/api/classes/{class_id}/students/export?format=csv')
    assert resp_exp_csv.status_code == 200
    assert resp_exp_csv.mimetype == 'text/csv'
    
    # 10. Delete student API
    resp_st_del = client.delete(f'/api/students/{student_id}')
    assert resp_st_del.status_code == 200
    
    # 11. Delete class API
    resp_del = client.delete(f'/api/classes/{class_id}')
    assert resp_del.status_code == 200
    assert resp_del.get_json()['status'] == 'deleted'


def test_contests_and_notifications_api(client):
    # Contest APIs
    resp_contests = client.get('/api/contests')
    assert resp_contests.status_code == 200
    data_c = resp_contests.get_json()
    assert 'contests' in data_c
    
    # Favorite API
    resp_fav = client.post('/api/contests/test_c_1/favorite', json={'favorite': True, 'platform': 'leetcode', 'user_id': 'qa_user'})
    assert resp_fav.status_code == 200
    
    # Subscribe / Unsubscribe API
    resp_sub = client.post('/api/contests/test_c_1/subscribe', json={'intervals': ['1h', '30m'], 'platform': 'leetcode', 'user_id': 'qa_user'})
    assert resp_sub.status_code == 200
    
    resp_unsub = client.post('/api/contests/test_c_1/unsubscribe', json={'user_id': 'qa_user'})
    assert resp_unsub.status_code == 200
    
    # Notifications API
    resp_notif = client.get('/api/notifications?user_id=qa_user')
    assert resp_notif.status_code == 200
    
    resp_clear = client.post('/api/notifications/clear', json={'user_id': 'qa_user'})
    assert resp_clear.status_code == 200
    
    # Dashboard widget API
    resp_widget = client.get('/api/dashboard/contest-widget')
    assert resp_widget.status_code == 200
    assert 'platformCounts' in resp_widget.get_json()


def test_analyzer_post_and_download(client):
    # 1. Post analysis with single student manual input
    payload = {
        'platform_codeforces': 'on',
        'platform_codechef': 'on',
        'platform_leetcode': 'on',
        'name': 'Test Student',
        'register_no': 'TEST_REG_101',
        'department': 'CSE',
        'codeforces': 'tourist',
        'codechef': 'chef',
        'leetcode': 'lee215',
        'leetcode_contest': 'weekly-contest-400'
    }
    resp = client.post('/', data=payload)
    assert resp.status_code in (200, 302)
    
    # 2. Download Excel
    resp_down_xlsx = client.get('/download?format=xlsx')
    assert resp_down_xlsx.status_code in (200, 404)
    if resp_down_xlsx.status_code == 200:
        assert resp_down_xlsx.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        
    # 3. Download CSV
    resp_down_csv = client.get('/download?format=csv')
    assert resp_down_csv.status_code in (200, 404)
    if resp_down_csv.status_code == 200:
        assert resp_down_csv.mimetype.startswith('text/csv')


def test_validation_errors(client):
    # No platforms selected
    resp1 = client.post('/', data={'name': 'No Platform Student'})
    assert resp1.status_code == 400
    assert b'Select at least one platform' in resp1.data

    # Invalid file upload format in topper
    resp2 = client.post('/topper', data={'platform': 'leetcode', 'month': '8', 'sheet': (io.BytesIO(b'dummy'), 'test.txt')})
    assert resp2.status_code in (200, 400)


def test_unique_table_download(client):
    from app import _save_cache_tables
    dummy_tables = {
        "codechef": [
            {
                "contest": "Starters 150",
                "date": "2026-09-24",
                "rows": [
                    {"S. No": 1, "Name": "Alice CodeChef", "Current Rating": "1650"}
                ]
            }
        ],
        "leetcode": [
            {
                "contest": "Weekly Contest 400",
                "rows": [
                    {"S. No": 1, "Name": "Bob LeetCode", "Current Rating": "1800"}
                ]
            }
        ]
    }
    _save_cache_tables(dummy_tables)

    # 1. Test unique table export for CodeChef table (.xlsx)
    resp_cc_xlsx = client.get('/download?platform=codechef&table_idx=0&format=xlsx')
    assert resp_cc_xlsx.status_code == 200
    assert resp_cc_xlsx.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert 'Codechef_Starters_150' in resp_cc_xlsx.headers.get('Content-Disposition', '')

    # 2. Test unique table export for CodeChef table (.csv)
    resp_cc_csv = client.get('/download?platform=codechef&table_idx=0&format=csv')
    assert resp_cc_csv.status_code == 200
    assert resp_cc_csv.mimetype.startswith('text/csv')
    assert b'Alice CodeChef' in resp_cc_csv.data
    assert b'Bob LeetCode' not in resp_cc_csv.data  # Verify export is uniquely for this table only

    # 3. Test unique table export for LeetCode table (.csv)
    resp_lc_csv = client.get('/download?platform=leetcode&table_idx=0&format=csv')
    assert resp_lc_csv.status_code == 200
    assert b'Bob LeetCode' in resp_lc_csv.data
    assert b'Alice CodeChef' not in resp_lc_csv.data


def test_results_template_client_export_elements(client):
    from flask import render_template
    from app import app
    with app.test_request_context():
        rendered = render_template(
            "results.html",
            codeforces=[{"contest": "Round 950", "rows": [{"Name": "Tester", "Rating": 1500}]}],
            codechef=[{"contest": "Starters 150", "rows": [{"Name": "Chef", "Rating": 1600}]}],
            leetcode=[{"contest": "Weekly 400", "rows": [{"Name": "Leet", "Rating": 1700}]}],
            selected_platforms=["codeforces", "codechef", "leetcode"],
            evaluation_time=12.5,
            student_count=1
        )
        assert "xlsx.full.min.js" in rendered
        assert "exportSingleContestTable" in rendered
        assert "exportAllContests" in rendered
        assert "data-platform=\"Codeforces\"" in rendered
        assert "data-platform=\"CodeChef\"" in rendered
        assert "data-platform=\"LeetCode\"" in rendered
        assert "btn-table-export-excel" in rendered
        assert "btn-table-export-csv" in rendered
        assert "Export All Tables (.xlsx)" in rendered
        assert "Export All Tables (.csv)" in rendered


def test_cache_persistence_and_fallback():
    import app as app_mod
    import tempfile
    import os
    import json

    # Set up dummy tables
    test_tables = {
        "codeforces": [{"contest": "Round 999", "rows": [{"Name": "Persistent User", "Rating": 2100}]}],
        "codechef": [],
        "leetcode": []
    }
    app_mod._save_cache_tables(test_tables)

    # Wipe in-memory cache to simulate serverless cold-start or worker reboot
    app_mod.cache_tables = {"codeforces": [], "codechef": [], "leetcode": []}

    # Verify _load_cache_tables restores from temp file or DB
    loaded = app_mod._load_cache_tables()
    assert any(b.get("rows") for b in loaded.get("codeforces", []))
    assert loaded["codeforces"][0]["contest"] == "Round 999"



