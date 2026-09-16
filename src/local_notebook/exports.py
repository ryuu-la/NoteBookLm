import json
import re
from pathlib import Path

from fpdf import FPDF


def artifact_markdown(artifact: dict) -> str:
    if artifact["kind"] == "quiz":
        quiz = json.loads(artifact["content"])
        parts = [f"# {quiz['title']}"]
        if quiz.get("coverage"):
            parts.append("> " + quiz["coverage"])
        for index, question in enumerate(quiz["questions"], 1):
            parts.append(f"## {index}. {question['question']}")
            parts.extend(f"- {option}" for option in question["options"])
            parts.append(f"Answer: {question['options'][question['answer']]}\n\n{question['explanation']}")
        text = "\n\n".join(parts)
    elif artifact["kind"] == "mindmap":
        mindmap = json.loads(artifact["content"])
        parts = [f"# {mindmap['title']}"]
        if mindmap.get("coverage"):
            parts.append("> " + mindmap["coverage"])

        def visit(node, depth=0):
            parts.append("  " * depth + "- " + node["name"])
            for child in node.get("children", []):
                visit(child, depth + 1)
        visit(mindmap["root"])
        text = "\n".join(parts)
    else:
        text = artifact["content"]
    citations = json.loads(artifact.get("citations", "[]"))
    if citations:
        text += "\n\n## Sources\n\n" + "\n".join(
            f"[{item.get('number', index)}] {item['name']} — {item['locator']}"
            for index, item in enumerate(citations, 1))
    return text


class NotebookPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Notebook", size=8)
        self.set_text_color(120)
        self.cell(0, 10, f"Folio · Local Notebook                                      {self.page_no()}")


def export_pdf(title: str, text: str) -> bytes:
    fonts = [Path("C:/Windows/Fonts/segoeui.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font = next((path for path in fonts if path.exists()), None)
    if font is None:
        raise ValueError("PDF export needs a Unicode font: install DejaVu Sans or Segoe UI.")
    pdf = NotebookPDF()
    pdf.add_font("Notebook", fname=str(font))
    pdf.set_auto_page_break(True, margin=22)
    pdf.set_margins(22, 20, 22)
    pdf.add_page()
    pdf.set_font("Notebook", size=9)
    pdf.set_text_color(90, 105, 130)
    pdf.cell(0, 10, "FOLIO / YOUR KNOWLEDGE, CONNECTED", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(25, 30, 42)
    pdf.set_font("Notebook", size=23)
    pdf.multi_cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    for line in text.splitlines():
        heading = len(line) - len(line.lstrip("#")) if line.startswith("#") else 0
        clean = re.sub(r"\*\*|`", "", line.lstrip("# ") if heading else line)
        clean = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", clean)
        pdf.set_font("Notebook", size=15 if heading else 10)
        pdf.set_text_color(30, 40, 60) if heading else pdf.set_text_color(55, 60, 70)
        if not clean.strip():
            pdf.ln(3)
            continue
        pdf.multi_cell(0, 8 if heading else 6, clean, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
