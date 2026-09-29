import asyncio
import json
import logging
import re

from nicegui import ui

from .. import agent, chat, providers, research, storage as db
from ..retrieval.workflow import ResearchWorkflow
from .artifacts import note_editor
from .common import error_message, error_text, header, notebook_dialog, theme, theme_toggle
from .settings import settings_dialog
from .sources import add_sources_dialog, source_panel
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
    collapsed = {"sources": True, "studio": True}

    def apply_layout():
        for side, value in collapsed.items():
            layout.classes(add=f"{side}-collapsed" if value else "", remove="" if value else f"{side}-collapsed")
            toggles[side].props(f'aria-expanded={str(not value).lower()}')

    def toggle(side):
        collapsed[side] = not collapsed[side]
        apply_layout()
        ui.run_javascript("localStorage.setItem('folio.layout.v2', " + json.dumps(json.dumps(collapsed)) + ")")

    toggles = {}
    with ui.element("header").classes("notebook-header"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
            'flat round dense aria-label="Your notebooks"').classes("quiet-btn").tooltip("Your notebooks")
        ui.label(book["title"]).classes("notebook-title").tooltip(book["title"])
        ui.space()
        theme_toggle()
        for side, label, icon in [("sources", "Sources", "vertical_split"), ("studio", "Studio", "auto_awesome")]:
            toggles[side] = ui.button(label, icon=icon, on_click=lambda s=side: toggle(s)).props(
                f'flat dense aria-label="Toggle {side}" aria-expanded=false').classes("panel-toggle")
        ui.button("Create notebook", icon="add", on_click=notebook_dialog).props(
            'flat aria-label="Create notebook"').classes("notebook-create")
        with ui.button(icon="more_vert").props('flat dense round aria-label="Notebook options"').classes("quiet-btn"):
            with ui.menu().props('role=menu'):
                ui.menu_item("Rename notebook", on_click=lambda: rename_dialog(book)).props('role=menuitem')
                ui.menu_item("Clear conversation", on_click=lambda: clear_chat()).props('role=menuitem')
                ui.menu_item("Retrieval benchmarks", on_click=lambda: ui.navigate.to("/benchmarks")).props('role=menuitem')
                ui.separator()
                ui.menu_item("Delete notebook", on_click=lambda: delete_notebook_dialog(book)).props('role=menuitem')
        ui.button(icon="settings", on_click=settings_dialog).props(
            'flat dense round aria-label="Settings"').classes("quiet-btn").tooltip("Settings")

    mobile_buttons = {}

    def show_panel(side):
        layout.props(f'data-mobile-panel={side}')
        for name, button in mobile_buttons.items():
            button.classes(add="active-tab" if name == side else "", remove="" if name == side else "active-tab")
            button.props(f'aria-pressed={str(name == side).lower()}')

    with ui.row().classes("mobile-tabs").props('role=group aria-label="Notebook panels"'):
        for side, icon in [("sources", "library_books"), ("chat", "chat_bubble_outline"), ("studio", "auto_awesome")]:
            mobile_buttons[side] = ui.button(side.title(), icon=icon, on_click=lambda s=side: show_panel(s)).props(
                f'flat aria-label="Show {side}" aria-pressed={str(side == "chat").lower()}').classes("active-tab" if side == "chat" else "")

    with ui.element("main").classes("workspace sources-collapsed studio-collapsed").props('data-mobile-panel=chat') as layout:
        with ui.element("aside").classes("side-shell source-shell").props('aria-label="Source library"'):
            source_panel(notebook_id, lambda: toggle("sources"))
        clear_chat = chat_panel(book)
        with ui.element("aside").classes("side-shell studio-shell").props('aria-label="Study studio"'):
            studio_panel(notebook_id, lambda: toggle("studio"))

    async def restore_layout():
        try:
            saved = await ui.run_javascript("localStorage.getItem('folio.layout.v2')")
            values = json.loads(saved or "{}")
            if isinstance(values, dict):
                collapsed.update({key: values.get(key, True) is True for key in collapsed})
            apply_layout()
        except (ValueError, TypeError, TimeoutError):
            pass
    ui.timer(.1, restore_layout, once=True)


def chat_panel(book: dict):
    notebook_id = book["id"]
    state = {"busy": False, "task": None, "welcome_sig": None, "revision": None, "last_request": None}
    with ui.column().classes("chat-panel panel") as panel:
        client = panel.client
        conversation = ui.element("div").classes("conversation").props('tabindex=0 aria-label="Conversation"')
        conversation.on("scroll", js_handler="event => { const el = event.target; el.dataset.follow = el.scrollHeight - el.clientHeight - el.scrollTop < 100 ? 'true' : 'false'; }")

        def scroll_end(force=False):
            client.run_javascript("""requestAnimationFrame(() => {
                const el = document.querySelector('.conversation');
                if (el && (FORCE || el.dataset.follow !== 'false')) {
                    el.scrollTop = el.scrollHeight;
                    el.dataset.follow = 'true';
                }
            })""".replace("FORCE", "true" if force else "false"))

        @ui.refreshable
        def messages():
            history = db.messages(notebook_id)
            if state["revision"]:
                user_id, value = state["revision"]
                index = next((i for i, item in enumerate(history) if item["id"] == user_id), None)
                if index is not None:
                    history = history[:index + 1]
                    history[-1] = {**history[-1], "text": value}
            if not history:
                welcome(book, lambda text: ask(text))
            else:
                user_id = None
                for item in history:
                    if item["role"] == "user":
                        user_id = item["id"]
                    message_view(item, notebook_id, on_edit=lambda row: edit_question(row),
                                 on_retry=lambda uid=user_id: retry_answer(uid), busy=state["busy"],
                                 can_retry=user_id is not None)
        with conversation, ui.element("div").classes("conversation-inner"):
            messages()
            live = ui.column().classes("live-answer w-full gap-2").props('aria-live=off aria-label="Answer being generated"')
        if db.messages(notebook_id):
            ui.timer(.2, lambda: scroll_end(True), once=True)

        with ui.column().classes("composer-wrap w-full"):
            status = ui.label("").classes("retrieval-status").props('role=status aria-live=polite')
            retry_button = ui.button("Retry answer", icon="refresh", on_click=lambda: ask(*state["last_request"]) if state["last_request"] else None).props('flat dense').classes("retry-generation")
            retry_button.visible = False
            other_model_button = ui.button('Try Main model', icon='swap_horiz', on_click=lambda: retry_other_model()).props('flat dense').classes('retry-other-model')
            other_model_button.visible = False
            with ui.row().classes("composer w-full"):
                ui.button(icon="add", on_click=lambda: add_sources_dialog(notebook_id)).props(
                    'flat round dense aria-label="Add sources"').classes("composer-add").tooltip("Add sources")
                question = ui.textarea(placeholder="Ask your sources, or ask to search online").props('borderless dense hide-bottom-space autogrow rows=1 aria-label="Ask about your sources"').classes("question-input")
                question.tooltip("Enter to send · Shift + Enter for a new line")
                with ui.row().classes("w-full items-center composer-controls"):
                    source_count = ui.label("").classes("source-count").tooltip("Selected, indexed sources")
                    settings = db.settings()
                    saved_mode = settings.get('research_mode', 'auto')
                    research_mode = ui.select({'auto': 'Auto', 'sources': 'Sources', 'web': 'Agent'},
                                              value=saved_mode if saved_mode in {'auto', 'sources', 'web'} else 'auto').props(
                        'borderless dense options-dense hide-bottom-space aria-label="Research mode"').classes('research-mode')
                    research_mode.tooltip('Agent can retrieve notebook documents, search the web, and read websites together')
                    mode = ui.select({"fast": "Fast", "main": "Main"},
                                     value="fast" if settings["provider"] == "Gemini" else "main").props(
                                         'borderless dense options-dense hide-bottom-space aria-label="Answer model"').classes("model-select")
                    mode.tooltip(f"Fast: {settings['fast_model']} · Main: {settings['model']}")
                    stop_button = ui.button(icon="stop", on_click=lambda: state["task"].cancel() if state["task"] else None).props('round flat dense aria-label="Stop generation"').tooltip("Stop generation")
                    stop_button.visible = False
                    send_button = ui.button(icon="arrow_upward", color=None, on_click=lambda: ask(question.value)).props('round unelevated aria-label="Send question"').classes("send-btn").tooltip("Send question")
            ui.label("Folio can make mistakes. Check answers against your sources.").classes("composer-caption")

        def update_count():
            sources = db.sources(notebook_id)
            count = sum(source["selected"] for source in sources if source["status"] == "ready")
            source_count.set_text(f"{count} source{'s' if count != 1 else ''}")
            web_request = research.use_web(question.value or '', research_mode.value, db.messages(notebook_id))
            tool_request = agent.requested_tools(question.value or '')
            send_button.set_enabled(bool((count or web_request or tool_request) and (question.value or "").strip() and not state["busy"]))
            signature = [(row["id"], row["status"]) for row in sources]
            if signature != state["welcome_sig"]:
                state["welcome_sig"] = signature
                if not state["busy"] and not db.messages(notebook_id):
                    messages.refresh()
        ui.timer(1, update_count)
        question.on_value_change(update_count)
        research_mode.on_value_change(update_count)
        research_mode.on_value_change(lambda event: db.save_settings({'research_mode': event.value}))
        update_count()
        saved_history = db.messages(notebook_id)
        if saved_history and saved_history[-1]['role'] == 'user':
            unfinished = saved_history[-1]
            state['last_request'] = (unfinished['text'], unfinished['id'])
            status.set_text('Your last question has no saved answer. Retry it below.')
            retry_button.visible = True

        async def ask(value, user_id=None):
            # Suggestion and message-action buttons are deleted by messages.refresh().
            # Keep every await, UI update, and cleanup attached to the stable panel.
            with panel:
                await generate(value, user_id)

        async def retry_answer(user_id):
            item = db.one("SELECT * FROM messages WHERE id=? AND notebook_id=? AND role='user'", (user_id, notebook_id))
            if item:
                await ask(item["text"], user_id)

        async def retry_other_model():
            if state['last_request'] and not state['busy']:
                mode.set_value('main' if mode.value == 'fast' else 'fast')
                await ask(*state['last_request'])

        def edit_question(item):
            if state["busy"]:
                return
            with panel, ui.dialog() as dialog, ui.card().classes("modal-card"):
                ui.label("Edit your question").classes("text-xl")
                edited = ui.textarea("Your question", value=item["text"]).props("outlined autogrow").classes("w-full")
                ui.label("Saving sends this question again and replaces the replies after it. If generation fails, your original conversation is kept.").classes("text-sm muted")

                async def save():
                    if not edited.value.strip():
                        edited.error = "Enter a question."
                        return
                    value = edited.value
                    dialog.close()
                    await ask(value, item["id"])

                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")
                    ui.button("Save and send", on_click=save).classes("primary-btn")
            dialog.open()

        async def generate(value, user_id=None):
            question_text = (value or "").strip()
            if not question_text or state["busy"]:
                return
            web_request = research.use_web(question_text, research_mode.value, db.messages(notebook_id))
            tool_request = agent.requested_tools(question_text)
            if not web_request and not tool_request and not any(row["selected"] and row["status"] == "ready" for row in db.sources(notebook_id)):
                ui.notify("Add or select a ready source to start a conversation.", position="top")
                return
            state["busy"], state["task"] = True, asyncio.current_task()
            state["revision"] = (user_id, question_text) if user_id else None
            retry_button.visible = False
            other_model_button.visible = False
            first_token = False
            send_button.disable()
            mode.disable()
            research_mode.disable()
            question.disable()
            stop_button.visible = True
            send_button.visible = False
            question.set_value("")
            answer, evidence, tool_run = "", None, None
            is_revision = user_id is not None
            try:
                if user_id is None:
                    user_id = db.add_message(notebook_id, "user", question_text)
                state["last_request"] = (question_text, user_id)
                messages.refresh()
                status.set_text("")
                with live:
                    with ui.column().classes("pending-answer") as skeleton:
                        with ui.row().classes("thinking-label"):
                            ui.icon("auto_awesome", size="18px")
                            pending = ui.label("Searching your sources…").props('role=status')
                    if web_request or tool_request:
                        with ui.expansion('Agent activity', icon='travel_explore', value=True).classes('research-activity w-full'):
                            activity = ui.column().classes('gap-1 w-full')
                    with ui.column().classes("assistant-message streaming-answer w-full"):
                        markdown = ui.markdown("").classes("markdown w-full")
                scroll_end(True)
                history = db.messages(notebook_id)
                index = next(i for i, item in enumerate(history) if item["id"] == user_id)
                history = history[:index + 1]
                history[-1] = {**history[-1], "text": question_text}
                def research_progress(text):
                    pending.set_text(text)
                    with activity:
                        ui.label(text).classes('text-xs muted')
                    scroll_end()

                if tool_request:
                    tool_run = await agent.run(notebook_id, question_text, history[:-1], web=web_request,
                                               on_status=research_progress)
                    evidence = tool_run.evidence
                elif web_request:
                    evidence = await research.research(notebook_id, question_text, history[:-1], research_progress, depth='quick')
                else:
                    evidence = await ResearchWorkflow(timeout=180).run(
                        notebook_id=notebook_id, query=question_text, history=history[:-1])
                logging.getLogger(__name__).info(
                    "RAG route=%s mode=%s indexed=%s candidates=%s context=%d retrieval_ms=%d",
                    evidence.diagnostics.get('route'), evidence.mode,
                    evidence.diagnostics.get('indexed_passages'), evidence.diagnostics.get('candidate_count'),
                    len(evidence.passages), evidence.elapsed_ms)
                if evidence.warning:
                    logging.getLogger(__name__).info("RAG evidence scope: %s", evidence.warning)
                pending.set_text("Preparing your answer…")
                if not evidence.passages and not (tool_run and tool_run.outputs):
                    answer = "I couldn’t find evidence for that in the selected sources. Try a more specific question or add a source that covers it."
                    markdown.set_content(answer)
                elif not providers.configured():
                    raise ValueError("Set GEMINI_API_KEY in the project .env and restart the server to get a source-grounded answer.")
                else:
                    extra = tool_run.answer_instruction() if tool_run else ''
                    async for token in providers.stream(chat.SYSTEM, chat.prompt(notebook_id, question_text, evidence, history=history) + extra,
                                                        fast=mode.value == "fast", on_status=pending.set_text,
                                                        **({'max_output_tokens': 12000} if tool_run and tool_run.deep else {})):
                        answer += token
                        if not first_token:
                            first_token = True
                            skeleton.visible = False
                        markdown.set_content(re.sub(r'\[\[tool:[a-z_]+\]\]', '', answer))
                        scroll_end()
                        await asyncio.sleep(0)
                answer = chat.validate_citations(answer, evidence)
                if web_request and research.references_documents(question_text) and chat.missing_comparison_citations(answer, evidence):
                    pending.set_text('Checking document and website citations…')
                    answer = ''
                    repaired = await providers.complete(
                        chat.SYSTEM, chat.prompt(notebook_id, question_text, evidence, history=history)
                        + '\n\nWrite the requested comparison of notebook text versus websites. '
                        'Cite at least one relevant NOTEBOOK DOCUMENT and at least one WEBSITE. '
                        'Distinguish agreements and differences. Do not substitute a comparison of unrelated topics.',
                        fast=mode.value == 'fast')
                    answer = chat.validate_citations(repaired, evidence)
                    if chat.missing_comparison_citations(answer, evidence):
                        answer = ''
                        raise ValueError('The model did not cite both the notebook and web evidence for this comparison. Please retry.')
                if not answer.strip():
                    raise ValueError("The model returned no answer. Try again or choose another model.")
                citations = chat.cited_passages(answer, evidence)
                if tool_run:
                    agent.commit_answer(notebook_id, tool_run, answer, citations,
                                        user_id=user_id if is_revision else None, question=question_text)
                elif is_revision:
                    db.replace_turn(notebook_id, user_id, question_text, answer, citations)
                else:
                    db.add_message(notebook_id, "assistant", answer, citations)
                status.set_text("")
            except asyncio.CancelledError:
                if answer and evidence and not is_revision:
                    db.add_message(notebook_id, "assistant", chat.validate_citations(answer, evidence) + "\n\n*Generation stopped.*", chat.cited_passages(answer, evidence))
                status.set_text("Generation stopped. Original conversation kept." if is_revision else "Generation stopped.")
                retry_button.visible = True
            except Exception as exc:
                logging.getLogger(__name__).error('Generation failed error=%s code=%s partial_characters=%d',
                                                 type(exc).__name__, getattr(exc, 'code', None), len(answer))
                if answer and evidence and not is_revision:
                    db.add_message(notebook_id, "assistant", chat.validate_citations(answer, evidence) + "\n\n*Connection interrupted. You can retry this answer.*", chat.cited_passages(answer, evidence))
                error_message(exc)
                status.set_text(error_text(exc) + (' Your original conversation is kept.' if is_revision else ''))
                retry_button.visible = True
                other_model_button.set_text('Try Main model' if mode.value == 'fast' else 'Try Fast model')
                other_model_button.visible = True
            finally:
                state["busy"], state["task"], state["revision"] = False, None, None
                mode.enable()
                research_mode.enable()
                question.enable()
                stop_button.visible = False
                send_button.visible = True
                live.clear()
                messages.refresh()
                ui.timer(.1, scroll_end, once=True)
                update_count()
        question.on("keydown.enter.exact.prevent", lambda: ask(question.value))
    def clear_chat():
        if state["busy"]:
            ui.notify("Stop the current answer before clearing the conversation.")
        else:
            clear_dialog(notebook_id, messages)
    return clear_chat


def welcome(book, ask):
    sources = db.sources(book["id"])
    ready = [source for source in sources if source["status"] == "ready"]
    with ui.column().classes("chat-welcome w-full"):
        with ui.element("div").classes("welcome-symbol"):
            ui.icon(book.get("icon", "auto_stories"), size="28px")
        ui.label(book["title"]).classes("welcome-title")
        ui.label(f"{len(ready)} source{'s' if len(ready) != 1 else ''} ready · Your private notebook").classes("welcome-meta")
        description = book["description"] or (
            "Your reading, ready for a conversation. Ask a question, explore a connection, or turn your sources into a study guide."
            if ready else "A little knowledge goes a long way. Add a document, a website, or your notes to begin.")
        ui.label(description).classes("welcome-description")
        if ready:
            ui.label("EXPLORE YOUR SOURCES").classes("eyebrow mt-3")
            with ui.column().classes("welcome-suggestions"):
                suggestions = ["What are the key ideas in these sources?", "How do these concepts connect?", "Explain the most important concept with an example."]
                for suggestion in suggestions:
                    with ui.button(color=None, on_click=lambda text=suggestion: ask(text)).props("flat align=left").classes("suggestion w-full"):
                        ui.label(suggestion).classes("text-left")
                        ui.space()
                        ui.icon("north_east", size="16px")
        elif any(source["status"] in {"queued", "parsing", "indexing"} for source in sources):
            with ui.row().classes("thinking-label"):
                ui.icon("hourglass_top", size="18px")
                ui.label("Your sources are being prepared. Progress is in the Sources panel.")
        elif sources:
            ui.label("Your sources need attention. Open Sources to retry an import or add another document.").classes("welcome-description")
        else:
            from .sources import add_sources_dialog
            ui.button("Add your first source", icon="add", on_click=lambda: add_sources_dialog(book["id"])).classes("primary-btn mt-3")
        with ui.row().classes("welcome-footnote items-center gap-2"):
            ui.icon("fact_check", size="16px")
            ui.label("Follow the citations back to the original.")


def message_view(item, notebook_id, *, on_edit, on_retry, busy=False, can_retry=True):
    if item["role"] == "user":
        with ui.column().classes("user-message w-full items-end"):
            ui.label(item["text"]).classes("user-bubble whitespace-pre-wrap")
            with ui.row().classes("message-actions user-actions"):
                ui.button(icon="content_copy", on_click=lambda: ui.clipboard.write(item["text"])).props('flat dense round size=sm aria-label="Copy question"').classes("muted").tooltip("Copy question")
                edit = ui.button(icon="edit", on_click=lambda: on_edit(item)).props('flat dense round size=sm aria-label="Edit question"').classes("muted").tooltip("Edit question")
                edit.set_enabled(not busy)
        return
    citations = json.loads(item["citations"])
    text = item["text"]
    for citation in citations:
        number = citation["number"]
        text = re.sub(rf"\[{number}\](?!\()", lambda match: f"[{number}]({chat.citation_target(citation)})", text)
    with ui.column().classes("assistant-message w-full"):
        if any(citation.get('kind') == 'web' for citation in citations):
            mixed = any(citation.get('kind') != 'web' for citation in citations)
            ui.label('Agent research · documents + web' if mixed else 'Agent research · website citations').classes('text-xs muted')
        from .data_artifacts import message_results
        message_results(item['id'], text, answer_content)
        if citations:
            with ui.row().classes("citation-chips w-full"):
                for citation in citations:
                    origin = 'Web' if citation.get('kind') == 'web' else 'Document'
                    ui.link(f"{citation['number']} · {origin} · {citation['name']}", chat.citation_target(citation), new_tab=True).classes("citation-chip").tooltip(citation.get('url') or citation["name"])
        with ui.row().classes("message-actions"):
            ui.button(icon="content_copy", on_click=lambda: ui.clipboard.write(item["text"])).props('flat dense round size=sm aria-label="Copy answer"').classes("muted").tooltip("Copy answer")
            retry = ui.button(icon="refresh", on_click=on_retry).props('flat dense round size=sm aria-label="Retry answer"').classes("muted").tooltip("Retry answer from this question")
            retry.set_enabled(not busy and can_retry)
            ui.button(icon="bookmark_add", on_click=lambda: note_editor(notebook_id, initial=item["text"], citations=citations)).props('flat dense round size=sm aria-label="Save to notes"').classes("muted").tooltip("Save to notes")


def answer_content(text):
    """Keep Markdown rendering safe while adding usable headers to fenced code."""
    fence = re.compile(r"^(`{3,}|~{3,})([^\n]*)\n(.*?)^\1[ \t]*$", re.MULTILINE | re.DOTALL)
    end = 0
    with ui.column().classes("answer-content w-full"):
        for match in fence.finditer(text):
            if text[end:match.start()].strip():
                ui.markdown(text[end:match.start()]).classes("markdown w-full")
            language = match[2].strip() or "Code"
            with ui.column().classes("answer-code w-full"):
                with ui.row().classes("code-toolbar w-full items-center"):
                    ui.icon("code", size="18px")
                    ui.label(language).classes("code-language")
                    ui.space()
                    ui.button(icon="content_copy", on_click=lambda code=match[3]: ui.clipboard.write(code)).props(
                        'flat dense round size=sm aria-label="Copy code"').tooltip("Copy code")
                ui.markdown(match[0]).classes("markdown w-full")
            end = match.end()
        if text[end:].strip():
            ui.markdown(text[end:]).classes("markdown w-full")


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
