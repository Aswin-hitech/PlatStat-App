import io
import pandas as pd
from datetime import datetime
from parsers.csv_parser import parse_csv
from parsers.excel_parser import parse_excel
from utils.date_utils import today_ddmmyyyy, get_export_filename
from utils.ranking_utils import week_key, month_key, year_key, safe_number
from utils.excel_utils import create_excel_file, read_excel_file
from utils.excel_writer import build_excel


def test_today_ddmmyyyy():
    res = today_ddmmyyyy()
    assert isinstance(res, str)
    assert len(res.split('.')) == 3


def test_get_export_filename():
    dt = datetime(2026, 8, 28)
    fn = get_export_filename('codeforces', 'xlsx', date_obj=dt)
    assert fn == 'codeforces-2026-08-28.xlsx'
    fn_csv = get_export_filename('leetcode', '.csv', date_obj=dt)
    assert fn_csv == 'leetcode-2026-08-28.csv'


def test_ranking_utils():
    dt = datetime(2026, 8, 28)
    assert '2026' in week_key(dt)
    assert month_key(dt) == '2026-08'
    assert year_key(dt) == '2026'
    assert safe_number('123.45') == 123.45
    assert safe_number(None, 10) == 10
    assert safe_number('invalid', -1) == -1


def test_csv_parser():
    csv_data = "studentName,registerNo,department\nJohn Doe,REG001,CSE\n"
    stream = io.StringIO(csv_data)
    rows = parse_csv(stream)
    assert len(rows) == 1
    assert rows[0]['studentName'] == 'John Doe'
    assert rows[0]['registerNo'] == 'REG001'


def test_excel_parser_and_excel_utils():
    df = pd.DataFrame([{'name': 'Alice', 'reg': '101'}])
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    stream.seek(0)
    
    rows = parse_excel(stream)
    assert len(rows) == 1
    assert rows[0]['name'] == 'Alice'
    
    # Test create_excel_file and read_excel_file
    stream2 = create_excel_file([df], ['TestSheet'])
    df_read = read_excel_file(stream2)
    assert len(df_read) == 1
    assert df_read.iloc[0]['name'] == 'Alice'


def test_build_excel():
    cf = [{'Name of the Student': 'User1', 'Current Rating': 1500}]
    cc = [{'Name of the Student': 'User2', 'Current Rating': 1600}]
    lc = [{'Name of the Student': 'User3', 'Contest Rating': 1700}]
    
    out = build_excel(cf, cc, lc)
    assert out is not None
    assert isinstance(out, io.BytesIO)
    df_read = pd.read_excel(out)
    assert not df_read.empty
