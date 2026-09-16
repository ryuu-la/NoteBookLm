import json

from nicegui import run, ui

from .. import storage as db
from ..exports import artifact_markdown, export_pdf
from .common import error_message


def note_editor(notebook_id: str, artifact=None, initial="", citations=()):
    citations = json.loads(artifact["citations"]) if artifact else list(citations)
    with ui.dialog() as dialog, ui.card().classes("modal-card artifact-dialog"):
        with ui.row().classes("items-center w-full"):
            ui.label("Your notes, your words").classes("text-xl")
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props("flat round")
        title = ui.input("Title", value=artifact["title"] if artifact else "Untitled note").props("outlined").classes("w-full")
        text = ui.textarea("Markdown notes", value=artifact["content"] if artifact else initial).props("outlined rows=12").classes("w-full")
        state = {"id": artifact["id"] if artifact else None, "last": None}
        status = ui.label("Changes are saved automatically.").classes("text-xs muted")

        def save():
            if not text.value.strip() and state["id"] is None:
                return
            values = (title.value.strip() or "Untitled note", text.value)
            if values == state["last"]:
                return
            if state["id"]:
                db.execute("UPDATE artifacts SET title=?,content=?,updated_at=? WHERE id=?",
                           (*values, db.now(), state["id"]))
            else:
                state["id"] = db.save_artifact(notebook_id, "note", *values, citations=citations)
            state["last"] = values
            status.set_text("Saved on this computer")
        text.on_value_change(lambda: save())
        title.on_value_change(lambda: save())

        def done():
            save()
            dialog.close()

        def pdf():
            try:
                content = artifact_markdown({"kind": "note", "content": text.value, "citations": json.dumps(citations)})
                ui.download.content(export_pdf(title.value, content), "notes.pdf", "application/pdf")
            except Exception as exc:
                error_message(exc)
        with ui.row().classes("w-full justify-between"):
            ui.button("Save as PDF", icon="download", on_click=pdf).props("flat")
            ui.button("Done", on_click=done).classes("primary-btn")
    dialog.open()


def artifact_view(artifact: dict):
    if artifact["kind"] == "note":
        return note_editor(artifact["notebook_id"], artifact)
    with ui.dialog() as dialog, ui.card().classes("modal-card artifact-dialog"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label(artifact["title"]).classes("text-xl")
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props("flat round")
        if artifact["kind"] in {"quiz", "mindmap"}:
            coverage = json.loads(artifact["content"]).get("coverage")
            if coverage:
                ui.label(coverage).classes("text-xs muted")
        if artifact["kind"] == "quiz":
            quiz_view(json.loads(artifact["content"]))
        elif artifact["kind"] == "mindmap":
            mindmap_view(json.loads(artifact["content"]), json.loads(artifact["citations"]))
        else:
            with ui.scroll_area().classes("w-full h-96"):
                ui.markdown(artifact["content"]).classes("markdown w-full")

        async def pdf():
            try:
                data = await run.io_bound(export_pdf, artifact["title"], artifact_markdown(artifact))
                ui.download.content(data, "study-material.pdf", "application/pdf")
            except Exception as exc:
                error_message(exc)
        with ui.row().classes("w-full items-center"):
            ui.button("Export PDF", icon="download", on_click=pdf).props("flat")
            ui.button("Markdown", on_click=lambda: ui.download.content(artifact_markdown(artifact), "study-material.md")).props("flat")
            if artifact["kind"] in {"quiz", "mindmap"}:
                ui.button("JSON", on_click=lambda: ui.download.content(artifact["content"], "study-material.json")).props("flat")
            if artifact["kind"] == "report":
                ui.button("Edit as note", icon="edit_note", on_click=lambda: note_editor(artifact["notebook_id"], initial=artifact["content"], citations=json.loads(artifact["citations"]))).props("flat")
        citations = json.loads(artifact["citations"])
        if citations:
            with ui.expansion("Source evidence", icon="fact_check").classes("w-full"):
                for citation in citations:
                    ui.link(f"[{citation.get('number', '')}] {citation['name']} · {citation['locator']}",
                            f"/evidence/{citation['id']}", new_tab=True).classes("block text-xs mb-2")
    dialog.open()


def quiz_view(quiz: dict):
    answers = {}
    submitted = {"value": False}

    @ui.refreshable
    def body():
        with ui.scroll_area().classes("w-full h-96"):
            for index, question in enumerate(quiz["questions"]):
                with ui.column().classes("quiz-question w-full"):
                    ui.label(f"{index + 1}. {question['question']}").classes("font-medium")
                    radio = ui.radio({i: option for i, option in enumerate(question["options"])},
                                     value=answers.get(index), on_change=lambda event, i=index: answers.update({i: event.value}))
                    if submitted["value"]:
                        radio.disable()
                        correct = answers.get(index) == question["answer"]
                        ui.label("Correct" if correct else "Correct answer: " + question["options"][question["answer"]]).classes("quiz-correct" if correct else "quiz-incorrect")
                        ui.label(question["explanation"]).classes("text-sm muted")
                        ui.label("Evidence: " + ", ".join(f"[{n}]" for n in question["citations"])).classes("text-xs muted")
        if submitted["value"]:
            score = sum(answers.get(index) == question["answer"] for index, question in enumerate(quiz["questions"]))
            ui.label(f"{score} / {len(quiz['questions'])} correct").classes("text-lg font-medium")
    body()

    def submit():
        if len(answers) < len(quiz["questions"]):
            ui.notify("Answer every question before checking your score.")
            return
        submitted["value"] = True
        body.refresh()

    def retry():
        answers.clear()
        submitted["value"] = False
        body.refresh()
    with ui.row():
        ui.button("Check answers", on_click=submit).classes("primary-btn")
        ui.button("Try again", on_click=retry).props("flat")


def mindmap_view(mindmap: dict, citations: list[dict]):
    hint = ui.label("Scroll to zoom · drag to explore · click a branch to expand it").classes("text-xs muted")
    ui.echart({"backgroundColor": "transparent", "animation": False,
               "tooltip": {"trigger": "item", "triggerOn": "mousemove"},
               "series": [{"type": "tree", "data": [mindmap["root"]], "top": "8%", "left": "15%",
                           "bottom": "8%", "right": "26%", "symbolSize": 10, "roam": True,
                           "initialTreeDepth": 3, "expandAndCollapse": True,
                           "itemStyle": {"color": "#b5c8ff"}, "lineStyle": {"color": "#64708c", "width": 1.5},
                           "label": {"position": "left", "color": "#dddff1", "fontSize": 12, "width": 130, "overflow": "break"},
                           "leaves": {"label": {"position": "right"}}}]},
              on_point_click=lambda event: hint.set_text(
                  "Evidence: " + ", ".join(f"[{n}]" for n in event.data.get("citations", []))
                  if isinstance(event.data, dict) else "Select a node to inspect its sources")
              ).classes("w-full h-96")
