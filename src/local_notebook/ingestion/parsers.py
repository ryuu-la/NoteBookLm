import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from bs4 import BeautifulSoup


@dataclass
class Block:
    text: str
    locator: str


SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".tsv", ".txt", ".md",
             ".html", ".htm", ".json", ".png", ".jpg", ".jpeg", ".tiff", ".doc", ".ppt", ".xls"}


def validate_archive(path: Path) -> None:
    if is_zipfile(path):
        with ZipFile(path) as archive:
            items = archive.infolist()
            if len(items) > 20000 or sum(item.file_size for item in items) > 1_000_000_000:
                raise ValueError("The expanded document is too large to process safely.")


def parse(path: Path):
    extension = path.suffix.lower()
    validate_archive(path)
    if extension == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("This PDF is password protected. Import an unlocked copy.")
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if len(text.strip()) < 20 and page.images:
                text = ocr_pdf_page(path, number - 1)
            yield Block(text, f"Page {number}")
    elif extension == ".docx":
        from docx import Document
        document = Document(path)
        for number, paragraph in enumerate(document.paragraphs, 1):
            if paragraph.text.strip():
                yield Block(paragraph.text, f"Paragraph {number}")
        for number, table in enumerate(document.tables, 1):
            yield Block("\n".join(" | ".join(cell.text for cell in row.cells) for row in table.rows),
                        f"Table {number}")
    elif extension == ".pptx":
        from pptx import Presentation
        for number, slide in enumerate(Presentation(path).slides, 1):
            texts = [shape.text for shape in slide.shapes if shape.has_text_frame]
            for shape in slide.shapes:
                if shape.has_table:
                    texts.extend(" | ".join(cell.text for cell in row.cells) for row in shape.table.rows)
            if slide.has_notes_slide:
                texts.append(slide.notes_slide.notes_text_frame.text)
            yield Block("\n".join(texts), f"Slide {number}")
    elif extension == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in book:
                yield from row_blocks(sheet.iter_rows(values_only=True), sheet.title)
        finally:
            book.close()
    elif extension in {".csv", ".tsv"}:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            yield from row_blocks(csv.reader(handle, delimiter="\t" if extension == ".tsv" else ","), "Rows")
    elif extension in {".png", ".jpg", ".jpeg", ".tiff"}:
        yield Block(ocr_image(str(path)), "Image")
    elif extension in {".doc", ".ppt", ".xls"}:
        from .legacy import convert
        yield from parse(convert(path))
    elif extension in SUPPORTED:
        if extension in {".html", ".htm", ".json"}:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if extension in {".html", ".htm"}:
                soup = BeautifulSoup(text, "html.parser")
                for item in soup(["script", "style", "nav", "footer"]):
                    item.decompose()
                text = soup.get_text("\n", strip=True)
            else:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            for start in range(0, len(text), 16000):
                yield Block(text[start:start + 16000], f"Section {start // 16000 + 1}")
        else:
            with path.open(encoding="utf-8-sig", errors="replace") as handle:
                lines, first = [], 1
                for number, line in enumerate(handle, 1):
                    lines.append(line)
                    if sum(map(len, lines)) >= 12000:
                        yield Block("".join(lines), f"Lines {first}–{number}")
                        lines, first = [], number + 1
                if lines:
                    yield Block("".join(lines), f"Lines {first}–{first + len(lines) - 1}")
    else:
        raise ValueError(f"Unsupported file type: {extension}")


def row_blocks(rows, label: str):
    header, batch, start = "", [], 2
    for number, row in enumerate(rows, 1):
        line = " | ".join(str(value) if value is not None else "" for value in row)
        if number == 1:
            header = line
            continue
        batch.append(line)
        if len(batch) >= 30:
            yield Block(header + "\n" + "\n".join(batch), f"{label} · rows {start}–{number}")
            batch, start = [], number + 1
    if batch:
        yield Block(header + "\n" + "\n".join(batch), f"{label} · rows {start}–{start + len(batch) - 1}")
    elif header and start == 2:
        yield Block(header, f"{label} · row 1")


@lru_cache(maxsize=1)
def ocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError("Scanned pages need OCR. Install the optional package: pip install -e '.[ocr]'.") from exc
    return RapidOCR()


def ocr_image(image) -> str:
    result, _ = ocr_engine()(image)
    return "\n".join(item[1] for item in (result or []))


def ocr_pdf_page(path: Path, number: int) -> str:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ValueError("This PDF contains scanned/empty pages. Install the OCR extra to read them.") from exc
    with pdfium.PdfDocument(path) as document:
        return ocr_image(document[number].render(scale=1.5).to_numpy())
