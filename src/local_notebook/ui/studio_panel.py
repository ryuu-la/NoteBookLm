import asyncio
import logging
import time

from nicegui import ui

from .. import providers, storage as db
from ..config import RUNINFRA_MODELS
from ..retrieval.workflow import source_evidence
from ..studio import generate
from .artifacts import artifact_view, note_editor
from .common import error_message, error_text
from .studio_tasks import StudioWindow, task_dock
from .progress import RunProgress

KINDS = {"mindmap": ("account_tree", "Mind map", "See the connections", "pink"),
         "quiz": ("quiz", "Quiz", "Put yourself to the test", "blue"),
         "report": ("description", "Reports", "Go a little deeper", "yellow"),
         "note": ("edit_note", "Notes", "Make it your own", "green"),
         "analytics": ("bar_chart", "Data Analytics", "Find insights and chart data", "blue"),
         "spreadsheet": ("table_view", "Spreadsheet", "Organize and export data", "green"),
         "deep_research": ("travel_explore", "Deep Research", "Explore websites in depth", "pink")}



def model_control(busy=lambda: False):
    """One shared choice for new Studio runs and the RunInfra chat selector."""
    def options(settings):
        return RUNINFRA_MODELS if settings['provider'] == 'RunInfra' else {
            'main': settings['model'], 'fast': settings['fast_model']}

    def value(settings):
        return settings['model'] if settings['provider'] == 'RunInfra' else ('fast' if settings['studio_fast'] else 'main')

    settings = db.settings()
    choice = ui.select(options(settings), value=value(settings), label='Model').props(
        'dense outlined options-dense aria-label="Studio model"').classes('w-full studio-model')
    choice.tooltip('Used for new Studio tasks. Running tasks keep their original model.')

    def changed(event):
        current = db.settings()
        if current['provider'] == 'RunInfra' and event.value in RUNINFRA_MODELS:
            db.save_settings({'runinfra_model': event.value})
        elif current['provider'] != 'RunInfra' and event.value in {'main', 'fast'}:
            db.save_settings({'studio_fast': event.value == 'fast'})
    choice.on_value_change(changed)

    def sync():
        choice.set_enabled(not busy())
        if busy():
            return
        current = db.settings()
        if choice.options != options(current):
            choice.set_options(options(current), value=value(current))
        elif choice.value != value(current):
            choice.set_value(value(current))
    ui.timer(.5, sync)
    return choice


def studio_panel(notebook_id: str, on_collapse=None):
    with ui.column().classes("studio-panel panel"):
        with ui.row().classes("panel-heading w-full items-center"):
            ui.icon("auto_awesome", size="18px")
            ui.label("Studio")
            ui.space()
            ui.button(icon="last_page", on_click=on_collapse).props('flat dense round size=sm aria-label="Collapse studio"').classes("sidebar-collapse").tooltip("Collapse Studio")
        with ui.column().classes("studio-content w-full"):
            ui.label("Make something meaningful.").classes("studio-title")
            ui.label("Study, connect, and keep the ideas that matter.").classes("studio-subtitle")
            model_control()
            task_dock()
            with ui.element("div").classes("studio-grid"):
                for kind, (icon, label, caption, color) in KINDS.items():
                    def action(k=kind):
                        if k in {'analytics', 'spreadsheet', 'deep_research'}:
                            return agent_dialog(notebook_id, k)
                        if k != "note" and not any(row["selected"] and row["status"] == "ready" for row in db.sources(notebook_id)):
                            ui.notify("Select a ready source to create study material.", position="top")
                            return
                        return note_editor(notebook_id) if k == "note" else generate_dialog(notebook_id, k)
                    with ui.card().classes(f"studio-tile tile-{color}").props(f'role=button tabindex=0 aria-label="{label}"').on(
                        "click", action).on("keydown.enter", action).on("keydown.space.prevent", action):
                        with ui.row().classes("items-center w-full"):
                            ui.icon(icon, size="22px")
                            ui.space()
                            ui.icon("north_east", size="13px").classes("tile-arrow")
                        ui.label(label).classes("tile-title")
                        ui.label(caption).classes("tile-caption")
            with ui.row().classes("w-full items-center mt-7 mb-1"):
                ui.label("SAVED IN THIS NOTEBOOK").classes("eyebrow")
                ui.space()
                ui.icon("history", size="15px").classes("muted")

            @ui.refreshable
            def artifacts():
                saved = db.rows("SELECT * FROM artifacts WHERE notebook_id=? ORDER BY updated_at DESC", (notebook_id,))
                if not saved:
                    with ui.column().classes("studio-empty w-full items-center text-center"):
                        ui.icon("bookmarks", size="27px")
                        ui.label("Keep your discoveries close").classes("text-sm")
                        ui.label("Your notes, maps, and study guides\nwill find a home here.").classes("text-xs muted whitespace-pre-line")
                for item in saved:
                    with ui.row().classes("artifact-row w-full items-center no-wrap"):
                        ui.icon(KINDS.get(item["kind"], KINDS["note"])[0], size="20px")
                        with ui.column().classes("gap-0 flex-1 min-w-0"):
                            ui.button(item["title"], on_click=lambda a=item: artifact_view(a)).props("flat dense align=left").classes("artifact-title").tooltip(item["title"])
                            ui.label(item["kind"].capitalize()).classes("text-xs muted")
                        ui.button(icon="delete_outline", on_click=lambda a=item: delete_artifact(a)).props("flat round dense size=sm").classes("muted").tooltip("Delete saved item")
            artifacts()
            previous = {"value": db.rows("SELECT id,updated_at FROM artifacts WHERE notebook_id=?", (notebook_id,))}

            def poll():
                value = db.rows("SELECT id,updated_at FROM artifacts WHERE notebook_id=?", (notebook_id,))
                if value != previous["value"]:
                    previous["value"] = value
                    artifacts.refresh()
            ui.timer(2, poll)
        with ui.element("div").classes("studio-footer"):
            ui.button("Add a note", icon="edit_note", on_click=lambda: note_editor(notebook_id)).props("outline").classes("w-full")


def generate_dialog(notebook_id, kind):
    state = {"task": None, "started": 0, "stage": "", "retrieval_s": 0, "first_token_s": None}
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        window = StudioWindow(dialog, KINDS[kind][1], lambda: state['task'].cancel() if state['task'] else None)
        with ui.row().classes('w-full items-center'):
            ui.label(f"Create a {KINDS[kind][1].lower()}").classes("text-xl")
            ui.space()
            window.button()
        ui.label("Grounded in the sources you’ve selected.").classes("muted")
        model_control(lambda: bool(state["task"]))
        topic = ui.input("Focus on a topic (optional)", placeholder="Leave blank for a source overview").props("outlined").classes("w-full")
        defaults = {"quiz": "Create 5 medium-difficulty multiple choice questions.",
                    "mindmap": "Explore the topic in depth: key concepts, subtopics, how they connect, practical examples, and limitations. Use concise labels and source-backed explanations.",
                    "report": "Create a study guide with key concepts, practical examples, and a concise summary."}
        instructions = ui.textarea("Instructions", value=defaults[kind]).props("outlined rows=3").classes("w-full")
        status = RunProgress()
        status.expansion.visible = False
        with ui.column().classes("studio-preview w-full") as preview:
            ui.label("Taking shape").classes("eyebrow")
            preview_text = ui.label("").classes("studio-preview-text whitespace-pre-line")
        preview.visible = False
        timing = ui.label("").classes("text-xs muted")

        def on_progress(event):
            if event['stage'] == 'retrying':
                state['stage'] = 'Completing a fresh draft after an incomplete model response'
                preview_text.set_text('')
                preview.visible = False
                tick()
                return
            if event["stage"] == "complete":
                logging.getLogger(__name__).info(
                    "Studio timing kind=%s retrieval_s=%.3f first_token_s=%s generation_s=%.3f prompt_chars=%d output_chars=%d",
                    kind, state["retrieval_s"], event["first_token_s"], event["elapsed_s"],
                    event["prompt_characters"], event["characters"])
                return
            state["first_token_s"] = event["first_token_s"]
            items = event["items"]
            label = ("question" if kind == "quiz" else "topic") + ("s" if len(items) != 1 else "")
            state["stage"] = f"Building your {KINDS[kind][1].lower()}" + (f" · {len(items)} {label} received" if items else " · receiving content")
            content = "\n".join(f"• {item}" for item in items[-8:]) if items else event["preview"]
            if content:
                preview_text.set_text(content)
                preview.visible = True
            timing.set_text(f"Sources ready in {state['retrieval_s']:.1f}s · First response in {event['first_token_s']:.1f}s")
            tick()
        def tick():
            if state["task"]:
                status.set_text(state["stage"])
                window.update(f"{state['stage']} · {time.perf_counter() - state['started']:.0f}s")
        ui.timer(1, tick)

        def cancel():
            window.stop()
            if state["task"]:
                state["task"].cancel()
            dialog.close()

        @providers.model_run
        async def create():
            if state["task"]:
                return
            state.update(task=asyncio.current_task(), started=time.perf_counter(), stage="Reading selected sources")
            button.disable()
            button.props("loading")
            topic.disable()
            instructions.disable()
            status.reset()
            preview.visible = False
            timing.set_text("")
            status.set_text("Reading your sources and creating your study material…")
            try:
                evidence = await source_evidence(notebook_id, topic.value.strip() or "source overview")
                state["retrieval_s"] = time.perf_counter() - state["started"]
                settings = providers.current_settings()
                model = settings["fast_model"] if settings["studio_fast"] else settings["model"]
                state["stage"] = f"Creating with {model}"
                tick()
                # The topic scopes both retrieval and the actual model request.
                preference = (f"Focus topic: {topic.value.strip()}\n" if topic.value.strip() else "") + instructions.value
                identifier = await generate(notebook_id, kind, evidence, preference, on_progress=on_progress)
                state["task"] = None
                window.finish(lambda: artifact_view(db.one("SELECT * FROM artifacts WHERE id=?", (identifier,))))
            except asyncio.CancelledError:
                status.set_text("Generation cancelled")
                window.update('Cancelled')
            except Exception as exc:
                error_message(exc)
                status.set_text(error_text(exc))
                window.update('Failed · reopen to retry')
            finally:
                state["task"] = None
                button.enable()
                button.props(remove="loading")
                topic.enable()
                instructions.enable()
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=cancel).props("flat")
            button = ui.button("Generate", icon="auto_awesome", on_click=create).classes("primary-btn")
    dialog.open()


def agent_dialog(notebook_id, kind):
    from .. import agent, chat, providers
    state = {'task': None}
    with ui.dialog() as dialog, ui.card().classes('modal-card'):
        window = StudioWindow(dialog, KINDS[kind][1], lambda: state['task'].cancel() if state['task'] else None)
        with ui.row().classes('w-full items-center'):
            ui.label(KINDS[kind][1]).classes('text-xl')
            ui.space()
            window.button()
        ui.label('Use selected sources, research the web, and create saved results.').classes('text-sm muted')
        model_control(lambda: bool(state["task"]))
        request = ui.textarea('What should the agent do?', placeholder='Describe the topic, data, and result you need').props('outlined rows=4').classes('w-full')
        online = ui.checkbox('Search the web', value=kind == 'deep_research')
        if kind == 'deep_research':
            online.disable()
        status = RunProgress()
        status.expansion.visible = False

        def cancel():
            window.stop()
            if state['task']:
                state['task'].cancel()
            dialog.close()

        @providers.model_run
        async def create():
            if state['task'] or not (request.value or '').strip():
                return
            state['task'] = asyncio.current_task()
            button.disable()
            request.disable()
            online.disable()
            status.reset()
            def update_status(text):
                status.set_text(text)
                window.update(text)
            try:
                result = await agent.run(notebook_id, request.value, web=online.value, forced=[kind], on_status=update_status)
                answer = ''
                if result.deep:
                    update_status('Writing your detailed report…')
                    answer = await providers.complete(chat.SYSTEM, chat.prompt(notebook_id, request.value, result.evidence)
                                                      + result.answer_instruction(), fast=False, max_output_tokens=12000)
                    answer = chat.validate_citations(answer, result.evidence)
                identifiers = agent.save_outputs(notebook_id, result, answer)
                if not identifiers:
                    raise ValueError('; '.join(result.errors) or 'No usable data was found. Select a data source or enable web search.')
                state['task'] = None
                window.finish(lambda: artifact_view(db.one('SELECT * FROM artifacts WHERE id=?', (identifiers[0],))))
                if result.errors:
                    ui.notify('Some tools could not finish: ' + '; '.join(result.errors), type='warning')
            except asyncio.CancelledError:
                status.set_text('Cancelled')
                window.update('Cancelled')
            except Exception as exc:
                error_message(exc)
                status.set_text(str(exc))
                window.update('Failed · reopen to retry')
            finally:
                state['task'] = None
                button.enable()
                request.enable()
                if kind != 'deep_research':
                    online.enable()
        with ui.row().classes('w-full justify-end'):
            ui.button('Cancel', on_click=cancel).props('flat')
            button = ui.button('Run agent', icon='auto_awesome', on_click=create).classes('primary-btn')
    dialog.open()


def delete_artifact(artifact):
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        ui.label(f"Delete “{artifact['title']}”?").classes("text-lg")
        ui.label("This saved item will be removed from your notebook.").classes("muted")

        def remove():
            db.execute("DELETE FROM artifacts WHERE id=?", (artifact["id"],))
            dialog.close()
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Delete", on_click=remove).props("color=negative")
    dialog.open()
