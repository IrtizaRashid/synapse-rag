from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import fitz
import requests
from bs4 import BeautifulSoup
from docx import Document
from PIL import Image
from pptx import Presentation
from rapidocr_onnxruntime import RapidOCR
from openpyxl import load_workbook
import xlrd
from striprtf.striprtf import rtf_to_text

TEXT_TYPES = {
    ".txt", ".md", ".markdown", ".json", ".xml", ".tsv", ".js", ".jsx", ".ts", ".tsx",
    ".py", ".java", ".c", ".cpp", ".h", ".hpp", ".html", ".css", ".sql", ".php", ".go",
    ".rs", ".rb", ".sh", ".yaml", ".yml", ".log", ".ini", ".env", ".config",
}
SUPPORTED = {".pdf", ".doc", ".docx", ".rtf", ".ppt", ".pptx", ".csv", ".xls", ".xlsx", *TEXT_TYPES,
             ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_ocr: RapidOCR | None = None


@dataclass
class Section:
    text: str
    location: str


@dataclass
class Chunk:
    id: str
    source: str
    location: str
    text: str
    owner_id: int = 0

    def to_dict(self) -> dict:
        return asdict(self)



def _ocr_engine() -> RapidOCR:
    global _ocr
    if _ocr is None:
        _ocr = RapidOCR()
    return _ocr


def ocr_image(data: bytes) -> str:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    result, _ = _ocr_engine()(image)
    if not result:
        return ""
    return "\n".join(str(row[1]) for row in result if len(row) > 1).strip()


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf(data: bytes) -> list[Section]:
    sections: list[Section] = []
    doc = fitz.open(stream=data, filetype="pdf")
    for number, page in enumerate(doc, 1):
        text = _clean(page.get_text("text"))
        method = "text"
        if len(text) < 50:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            ocr_text = _clean(ocr_image(pix.tobytes("png")))
            if len(ocr_text) > len(text):
                text, method = ocr_text, "OCR"
        if text:
            sections.append(Section(text, f"page {number} ({method})"))
    doc.close()
    return sections


def _tables_from_docx(doc: Document) -> list[str]:
    rows: list[str] = []
    for table in doc.tables:
        for row in table.rows:
            value = " | ".join(_clean(cell.text) for cell in row.cells)
            if value.strip(" |"):
                rows.append(value)
    return rows


def _embedded_images(data: bytes, prefix: str) -> Iterable[Section]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if "/media/" in n.lower()]
        for index, name in enumerate(names, 1):
            try:
                text = _clean(ocr_image(archive.read(name)))
            except Exception:
                continue
            if text:
                yield Section(text, f"{prefix} embedded image {index} (OCR)")


def extract_docx(data: bytes) -> list[Section]:
    doc = Document(io.BytesIO(data))
    body = [_clean(p.text) for p in doc.paragraphs if _clean(p.text)]
    body.extend(_tables_from_docx(doc))
    sections = [Section("\n".join(body), "document text")] if body else []
    sections.extend(_embedded_images(data, "DOCX"))
    return sections


def extract_pptx(data: bytes) -> list[Section]:
    prs = Presentation(io.BytesIO(data))
    sections: list[Section] = []
    for number, slide in enumerate(prs.slides, 1):
        values: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and _clean(shape.text):
                values.append(_clean(shape.text))
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    values.append(" | ".join(_clean(cell.text) for cell in row.cells))
        if values:
            sections.append(Section("\n".join(values), f"slide {number}"))
    sections.extend(_embedded_images(data, "PPTX"))
    return sections


def extract_csv(data: bytes) -> list[Section]:
    text = data.decode("utf-8-sig", errors="replace")
    rows = []
    for number, row in enumerate(csv.reader(io.StringIO(text)), 1):
        rows.append(f"Row {number}: " + " | ".join(cell.strip() for cell in row))
    return [Section("\n".join(rows), "CSV rows")] if rows else []


def extract_delimited(data: bytes, delimiter: str, label: str) -> list[Section]:
    text = data.decode("utf-8-sig", errors="replace")
    rows = []
    for number, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), 1):
        rows.append(f"Row {number}: " + " | ".join(cell.strip() for cell in row))
    return [Section("\n".join(rows), f"{label} rows")] if rows else []


def extract_xlsx(data: bytes) -> list[Section]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sections: list[Section] = []
    for sheet in workbook.worksheets:
        rows = []
        for number, row in enumerate(sheet.iter_rows(values_only=True), 1):
            values = ["" if value is None else str(value) for value in row]
            if any(value.strip() for value in values):
                rows.append(f"Row {number}: " + " | ".join(values))
        if rows:
            sections.append(Section("\n".join(rows), f"sheet {sheet.title}"))
    workbook.close()
    return sections


def extract_xls(data: bytes) -> list[Section]:
    workbook = xlrd.open_workbook(file_contents=data)
    sections: list[Section] = []
    for sheet in workbook.sheets():
        rows = []
        for number in range(sheet.nrows):
            values = [str(sheet.cell_value(number, col)) for col in range(sheet.ncols)]
            if any(value.strip() for value in values):
                rows.append(f"Row {number + 1}: " + " | ".join(values))
        if rows:
            sections.append(Section("\n".join(rows), f"sheet {sheet.name}"))
    return sections


def extract_rtf(data: bytes) -> list[Section]:
    text = rtf_to_text(data.decode("utf-8", errors="replace"))
    text = _clean(text)
    return [Section(text, "RTF document")] if text else []


def extract_structured_text(filename: str, data: bytes) -> list[Section]:
    suffix = Path(filename).suffix.lower()
    raw = data.decode("utf-8-sig", errors="replace")
    if suffix == ".json":
        try:
            raw = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
        except ValueError:
            pass
    elif suffix == ".xml":
        try:
            root = ET.fromstring(raw)
            values = []
            for element in root.iter():
                value = (element.text or "").strip()
                if value:
                    values.append(f"{element.tag}: {value}")
            raw = "\n".join(values) or raw
        except ET.ParseError:
            pass
    elif suffix == ".html":
        soup = BeautifulSoup(raw, "html.parser")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        raw = soup.get_text("\n")
    text = _clean(raw)
    return [Section(text, "document text")] if text else []


def analyze_file(filename: str, data: bytes, sections: list[Section] | None = None) -> dict:
    """Cheap metadata used by file cards/previews; never calls an LLM."""
    suffix = Path(filename).suffix.lower()
    metadata: dict = {"extension": suffix, "size_bytes": len(data)}
    try:
        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace")), delimiter=delimiter))
            metadata.update({"rows": max(0, len(rows) - 1), "columns": len(rows[0]) if rows else 0,
                             "column_names": rows[0][:100] if rows else [], "preview_rows": rows[:20]})
        elif suffix == ".xlsx":
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheet = workbook.active
            preview = [["" if value is None else str(value) for value in row] for row in list(sheet.iter_rows(values_only=True))[:20]]
            metadata.update({"sheet": sheet.title, "rows": max(0, sheet.max_row - 1), "columns": sheet.max_column,
                             "column_names": preview[0] if preview else [], "preview_rows": preview})
            workbook.close()
        elif suffix == ".xls":
            workbook = xlrd.open_workbook(file_contents=data)
            sheet = workbook.sheet_by_index(0)
            preview = [[str(sheet.cell_value(r, c)) for c in range(sheet.ncols)] for r in range(min(20, sheet.nrows))]
            metadata.update({"sheet": sheet.name, "rows": max(0, sheet.nrows - 1), "columns": sheet.ncols,
                             "column_names": preview[0] if preview else [], "preview_rows": preview})
    except Exception:
        pass
    if sections:
        metadata["sections"] = len(sections)
        metadata["characters"] = sum(len(section.text) for section in sections)
    return metadata


def extract_file(filename: str, data: bytes) -> list[Section]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")
    if suffix == ".pdf":
        return extract_pdf(data)
    if suffix == ".docx":
        return extract_docx(data)
    if suffix == ".pptx":
        return extract_pptx(data)
    if suffix == ".csv":
        return extract_csv(data)
    if suffix == ".tsv":
        return extract_delimited(data, "\t", "TSV")
    if suffix == ".xlsx":
        return extract_xlsx(data)
    if suffix == ".xls":
        return extract_xls(data)
    if suffix == ".rtf":
        return extract_rtf(data)
    if suffix in {".doc", ".ppt"}:
        # Legacy Office binaries need LibreOffice/antiword for perfect parsing;
        # still recover readable strings instead of rejecting the upload.
        text = _clean(data.decode("latin-1", errors="ignore"))
        return [Section(text, "legacy Office text recovery")] if text else []
    if suffix in IMAGE_TYPES:
        text = _clean(ocr_image(data))
        return [Section(text, "image (OCR)")] if text else []
    return extract_structured_text(filename, data)


def scan_directory(root: Path, max_bytes: int, ignore: set[str] | None = None) -> Iterable[tuple[Path, bytes]]:
    """Recursively walk a folder and yield (path, bytes) for every supported file.

    Skips hidden files/dirs, files over ``max_bytes``, and paths matching ``ignore``
    (set of lower-cased names, e.g. node_modules, .git).
    """
    if ignore is None:
        ignore = {".git", ".venv", "venv", "node_modules", "__pycache__", ".idea", ".vscode", ".env", "data"}
    for entry in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name.lower() in ignore or any(part.lower() in ignore for part in entry.parts):
            continue
        if entry.suffix.lower() not in SUPPORTED:
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            continue
        if size > max_bytes:
            continue
        try:
            yield entry, entry.read_bytes()
        except OSError:
            continue


def ingest_directory(root: Path, max_bytes: int = 25 * 1024 * 1024) -> dict:
    """Extract + chunk every supported file under ``root``.

    Returns a report dict with per-file results and the flat list of Chunk
    objects ready to be stored/embedded by the caller.
    """
    report: dict = {"root": str(root), "files_found": 0, "indexed": [], "errors": [], "chunks": []}
    for path, data in scan_directory(root, max_bytes):
        report["files_found"] += 1
        source = str(path.relative_to(root))
        try:
            sections = extract_file(path.name, data)
            chunks = chunk_sections(source, sections)
            if not chunks:
                raise ValueError("No readable text was found")
            report["indexed"].append({"source": source, "sections": len(sections), "chunks": len(chunks)})
            report["chunks"].extend(chunks)
        except Exception as exc:
            report["errors"].append({"source": source, "error": str(exc)})
    return report


def extract_url(url: str) -> tuple[str, list[Section]]:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    response = requests.get(url, timeout=20, headers={"User-Agent": "RAGPlatform/1.0"})
    response.raise_for_status()
    if "text/html" not in response.headers.get("content-type", ""):
        raise ValueError("URL must return an HTML page")
    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        node.decompose()
    title = _clean(soup.title.get_text(" ")) if soup.title else url
    text = _clean(soup.get_text("\n"))
    return title, [Section(text, "web page")]


def chunk_sections(source: str, sections: list[Section], size: int = 900, overlap: int = 150) -> list[Chunk]:
    chunks: list[Chunk] = []
    step = max(1, size - overlap)
    for section in sections:
        text = _clean(section.text)
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            if end < len(text):
                boundary = max(text.rfind("\n", start + size // 2, end), text.rfind(". ", start + size // 2, end))
                if boundary > start:
                    end = boundary + 1
            value = text[start:end].strip()
            if value:
                digest = hashlib.sha256(f"{source}|{section.location}|{start}|{value}".encode()).hexdigest()[:20]
                chunks.append(Chunk(digest, source, section.location, value))
            if end >= len(text):
                break
            start = max(start + step, end - overlap)
    return chunks
