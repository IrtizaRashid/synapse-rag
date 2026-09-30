import io
import json

from openpyxl import Workbook

from rag.ingest import SUPPORTED, analyze_file, extract_file


def test_requested_text_data_and_code_formats_are_supported():
    expected = {
        ".pdf", ".doc", ".docx", ".txt", ".rtf", ".md", ".csv", ".xls", ".xlsx",
        ".json", ".xml", ".tsv", ".js", ".jsx", ".ts", ".tsx", ".py", ".java",
        ".c", ".cpp", ".h", ".hpp", ".html", ".css", ".sql", ".php", ".go",
        ".rs", ".rb", ".sh", ".yaml", ".yml", ".log", ".ini", ".env", ".config",
    }
    assert expected <= SUPPORTED


def test_json_xml_tsv_html_and_code_extract_readable_text():
    assert '"revenue": 42' in extract_file("report.json", json.dumps({"revenue": 42}).encode())[0].text
    assert "revenue: 42" in extract_file("report.xml", b"<root><revenue>42</revenue></root>")[0].text
    assert "Row 2: A | 42" in extract_file("report.tsv", b"product\trevenue\nA\t42")[0].text
    html = extract_file("page.html", b"<style>bad</style><h1>Useful title</h1><script>bad()</script>")[0].text
    assert "Useful title" in html and "bad()" not in html
    assert "def total" in extract_file("analysis.py", b"def total(values):\n    return sum(values)")[0].text


def test_xlsx_extraction_and_structured_metadata():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["product", "revenue"])
    sheet.append(["A", 100])
    sheet.append(["B", 250])
    buffer = io.BytesIO()
    workbook.save(buffer)
    data = buffer.getvalue()

    sections = extract_file("sales.xlsx", data)
    metadata = analyze_file("sales.xlsx", data, sections)
    assert "Row 3: B | 250" in sections[0].text
    assert metadata["rows"] == 2
    assert metadata["columns"] == 2
    assert metadata["column_names"] == ["product", "revenue"]
    assert metadata["preview_rows"][2] == ["B", "250"]
