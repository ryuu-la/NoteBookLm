from pathlib import Path

import pytest


def test_local_ocr_reads_image_and_scanned_pdf(tmp_path):
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image, ImageDraw, ImageFont
    from fpdf import FPDF
    from local_notebook.ingestion.parsers import parse
    font_paths = [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font_path = next((path for path in font_paths if path.exists()), None)
    if font_path is None:
        pytest.skip("No test font installed")
    image = Image.new("RGB", (1300, 220), "white")
    ImageDraw.Draw(image).text((40, 60), "Retrieval practice improves learning.",
                              font=ImageFont.truetype(str(font_path), 44), fill="black")
    image_path = tmp_path / "scan.png"
    image.save(image_path)
    assert "learning" in list(parse(image_path))[0].text.lower()
    pdf = FPDF()
    pdf.add_page()
    pdf.image(str(image_path), x=10, y=20, w=190)
    pdf_path = tmp_path / "scanned.pdf"
    pdf.output(pdf_path)
    block = list(parse(pdf_path))[0]
    assert block.locator == "Page 1" and "learning" in block.text.lower()
