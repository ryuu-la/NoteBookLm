import asyncio
import json
import re
import time

from nicegui import ui

from .. import chat, providers, storage as db
from ..retrieval.workflow import ResearchWorkflow
from .artifacts import note_editor
from .common import error_message, header, theme
from .sources import source_panel
from .studio_panel import studio_panel


def workspace(notebook_id: str):
    book = db.one("SELECT * FROM notebooks WHERE id=?", (notebook_id,))
    theme()
    if not book:
        header()
        ui.label("This notebook could not be found.").classes("p-10 text-xl")
        ui.link("Back to your notebooks", "/").classes("px-10")
        return
    db.touch(notebook_id)
    header(book["title"])
    with ui.row().classes("notebook-toolbar w-full items-center"):
        ui.link("Your notebooks", "/").classes("breadcrumb")
        ui.icon("chevron_right", size="14px").classes("muted")
        ui.label(book["title"]).classes("text-xs muted")
        ui.space()
        ui.button("Rename", icon="edit", on_click=lambda: rename_dialog(book)).props("flat dense size=sm").classes("muted")
        with ui.button(icon="more_horiz").props("flat dense round"):
            with ui.menu():
                ui.menu_item("Delete notebook", on_click=lambda: delete_notebook_dialog(book))
    with ui.element("main").classes("workspace"):
        source_panel(notebook_id)
        chat_panel(book)
        studio_panel(notebook_id)
    with ui.element("footer").classes("workspace-footer"):
        ui.label("A little clarity goes a long way. Always check important details against your sources.")


def chat_panel(book: dict):
    notebook_id = book["id"]
    state = {"busy": False, "task": None, "follow": True}
    with ui.column().classes("chat-panel panel"):
        with ui.row().classes("panel-heading w-full items-center"):
            ui.label("Chat")
            ui.space()
            ui.label("GROUNDED IN YOUR SOURCES").classes("chat-kicker")
            ui.button(icon="restart_alt", on_click=lambda: clear_dialog(notebook_id, messages)).props("flat dense round size=sm").classes("muted").tooltip("Clear conversation")
        def track_scroll(event):
            state["follow"] = event.vertical_size - event.vertical_container_size - event.vertical_position < 100
        conversation = ui.scroll_area(on_scroll=track_scroll).classes("conversation")

        @ui.refreshable
        def messages():
            history = db.messages(notebook_id)
            if not history:
                welcome(book, lambda text: ask(text))
            else:
                for item in history:
                    message_view(item, notebook_id)
        with conversation:
            messages()
            live = ui.column().classes("w-full gap-2")
        with ui.column().classes("composer-wrap w-full"):
            status = ui.label("").classes("retrieval-status")
            with ui.column().classes("composer w-full"):
                question = ui.textarea(placeholder="Ask a question. Make a connection.").props("borderless autogrow rows=1").classes("w-full question-input")
                with ui.row().classes("w-full items-center"):
                    source_count = ui.label("").classes("text-xs muted")
                    ui.space()
                    settings = db.settings()
                    mode = ui.toggle({"fast": "Fast", "main": "Main"},
                                     value="fast" if settings["provider"] == "Gemini" else "main").props("dense no-caps size=sm")
                    mode.tooltip(f"Fast: {settings['fast_model']} · Main: {settings['model']}")
                    stop_button = ui.button(icon="stop", on_click=lambda: state["task"].cancel() if state["task"] else None).props('round flat dense aria-label="Stop generation"').tooltip("Stop generation")
                    stop_button.visible = False
                    send_button = ui.button(icon="arrow_upward", on_click=lambda: ask(question.value)).props('round unelevated aria-label="Send question"').classes("send-btn").tooltip("Send question")
            ui.label("Your sources do the talking. You do the discovering.").classes("composer-caption")

        def update_count():
            count = sum(source["selected"] for source in db.sources(notebook_id) if source["status"] == "ready")
            source_count.set_text(f"{count} sources selected")
        ui.timer(1.5, update_count)
        update_count()

        async def ask(value):
            question_text = (value or "").strip()
            if not question_text or state["busy"]:
                return
            state["busy"], state["task"] = True, asyncio.current_task()
            state["follow"] = True
            started, first_token, rendered = time.perf_counter(), None, 0
            send_button.disable()
            mode.disable()
            question.disable()
            stop_button.visible = True
            question.set_value("")
            db.add_message(notebook_id, "user", question_text)
            messages.refresh()
            status.set_text("Finding connections in your sources…")
            answer, evidence = "", None
            with live:
                spinner = ui.spinner(size="20px")
                pending = ui.label("Searching your sources…").classes("text-xs muted")
                markdown = ui.markdown("").classes("markdown assistant-message w-full")
            conversation.scroll_to(percent=1)
            try:
                history = db.messages(notebook_id)
                retrieval_query = question_text
                if len(question_text.split()) < 7 and len(history) > 1:
                    earlier = [item["text"] for item in history[:-1] if item["role"] == "user"]
                    retrieval_query = " ".join(earlier[-1:] + [question_text])
                evidence = await ResearchWorkflow(timeout=180).run(notebook_id=notebook_id, query=retrieval_query)
                retrieval_status = f"{evidence.mode} · {len(evidence.passages)} passages · {evidence.elapsed_ms} ms"
                status.set_text(retrieval_status)
                settings = db.settings()
                model = settings["fast_model"] if mode.value == "fast" else settings["model"]
                pending.set_text(f"Sources found. Waiting for {model}…")
                if evidence.warning:
                    status.set_text(evidence.warning)
                if not evidence.passages or not providers.configured():
                    answer = chat.extractive_answer(evidence)
                    markdown.set_content(answer)
                else:
                    async for token in providers.stream(chat.SYSTEM, chat.prompt(notebook_id, question_text, evidence), fast=mode.value == "fast"):
                        answer += token
                        now = time.perf_counter()
                        if first_token is None:
                            first_token = now - started
                            spinner.visible = pending.visible = False
                            status.set_text(f"{retrieval_status} · First words {first_token:.1f}s")
                        if now - rendered >= .05:
                            markdown.set_content(answer)
                            if state["follow"]:
                                conversation.scroll_to(percent=1)
                            rendered = now
                            await asyncio.sleep(0)
                    markdown.set_content(answer)
                answer = chat.validate_citations(answer, evidence)
                if not answer.strip():
                    raise ValueError("The model returned no answer. Try again or choose another model.")
                citations = chat.cited_passages(answer, evidence)
                db.add_message(notebook_id, "assistant", answer, citations)
            except asyncio.CancelledError:
                if answer and evidence:
                    db.add_message(notebook_id, "assistant", answer + "\n\n*Generation stopped.*", chat.cited_passages(answer, evidence))
                status.set_text("Generation stopped")
            except Exception as exc:
                error_message(exc)
                status.set_text("Could not finish. Your question is saved; you can try again.")
            finally:
                live.clear()
                messages.refresh()
                if state["follow"]:
                    ui.timer(.1, lambda: conversation.scroll_to(percent=1), once=True)
                state["busy"], state["task"] = False, None
                send_button.enable()
                mode.enable()
                question.enable()
                stop_button.visible = False
        question.on("keydown.enter.exact.prevent", lambda: ask(question.value))


def welcome(book, ask):
    with ui.column().classes("chat-welcome w-full"):
        with ui.element("div").classes("welcome-symbol"):
            ui.icon("auto_awesome", size="30px")
        ui.label("A few sources.\nA whole new perspective.").classes("welcome-title whitespace-pre-line")
        ui.label(book["description"] or "This is your space to explore ideas, find answers, and see the bigger picture. Start by adding a source.").classes("welcome-description")
        ui.label("WHERE WOULD YOU LIKE TO START?").classes("eyebrow mt-7 mb-1")
        suggestions = ["What are the key ideas in these sources?", "How do these concepts connect?", "Explain the most important concept with an example."]
        for suggestion in suggestions:
            with ui.button(on_click=lambda text=suggestion: ask(text)).props("flat align=left").classes("suggestion w-full"):
                ui.label(suggestion).classes("text-left")
                ui.space()
                ui.icon("north_east", size="16px")
        with ui.row().classes("welcome-footnote items-center gap-2"):
            ui.icon("verified", size="15px")
            ui.label("Every good answer has a source.")


def message_view(item, notebook_id):
    if item["role"] == "user":
        with ui.row().classes("user-message w-full justify-end"):
            ui.label(item["text"]).classes("user-bubble whitespace-pre-wrap")
        return
    citations = json.loads(item["citations"])
    text = item["text"]
    for citation in citations:
        number = citation["number"]
        text = re.sub(rf"\[{number}\](?!\()", f"[{number}](/evidence/{citation['id']})", text)
    with ui.column().classes("assistant-message w-full"):
        with ui.row().classes("items-center gap-2 assistant-label"):
            ui.icon("auto_awesome", size="16px")
            ui.label("Folio")
        ui.markdown(text).classes("markdown w-full")
        if citations:
            with ui.row().classes("citation-chips w-full"):
                for citation in citations:
                    ui.link(f"{citation['number']} · {citation['name'][:25]}", f"/evidence/{citation['id']}", new_tab=True).classes("citation-chip")
        ui.button("Save to notes", icon="bookmark_add", on_click=lambda: note_editor(notebook_id, initial=item["text"], citations=citations)).props("flat dense size=sm").classes("muted")


def clear_dialog(notebook_id, refresh):
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        ui.label("Clear this conversation?").classes("text-xl")
        ui.label("Your sources and saved notes stay in the notebook.").classes("muted")

        def clear():
            db.execute("DELETE FROM messages WHERE notebook_id=?", (notebook_id,))
            refresh.refresh()
            dialog.close()
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Clear chat", on_click=clear).classes("primary-btn")
    dialog.open()


def rename_dialog(book):
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        title = ui.input("Notebook title", value=book["title"]).props("outlined").classes("w-full")

        def save():
            if title.value.strip():
                db.execute("UPDATE notebooks SET title=? WHERE id=?", (title.value.strip()[:120], book["id"]))
                ui.navigate.reload()
        ui.button("Save", on_click=save).classes("primary-btn")
    dialog.open()


def delete_notebook_dialog(book):
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        ui.label(f"Delete “{book['title']}”?").classes("text-xl")
        ui.label("All its sources, conversations, and saved study materials will be removed.").classes("muted")

        async def remove():
            from ..ingestion.jobs import delete_source
            try:
                for source in db.sources(book["id"]):
                    await asyncio.to_thread(delete_source, source["id"])
                db.execute("DELETE FROM notebooks WHERE id=?", (book["id"],))
                ui.navigate.to("/")
            except Exception as exc:
                error_message(exc)
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Delete notebook", on_click=remove).props("color=negative")
    dialog.open()
