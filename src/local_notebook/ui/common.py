from pathlib import Path

from nicegui import ui

from .. import storage as db
from ..config import STYLES


def theme():
    ui.context.client.folio_dark = ui.dark_mode(db.settings().get('theme', 'dark') != 'light')
    ui.colors(primary="#a8c7fa", secondary="#c2b5ea", accent="#c2b5ea", dark="#1b1d20", positive="#a8d5ba", negative="#f2aaa5")
    for filename in ("base.css", "home.css", "workspace.css", "mindmap.css", "light.css"):
        ui.add_css((STYLES / filename).read_text(encoding="utf-8"))


def theme_toggle():
    dark = ui.context.client.folio_dark

    def toggle():
        dark.toggle()
        db.save_settings({'theme': 'dark' if dark.value else 'light'})
        button.props(f'icon={"light_mode" if dark.value else "dark_mode"}')

    button = ui.button(icon='light_mode' if dark.value else 'dark_mode', on_click=toggle).props(
        'flat round dense aria-label="Toggle light theme"').classes('quiet-btn').tooltip('Switch light / dark theme')


def brand():
    with ui.link(target="/").classes("brand no-underline"):
        with ui.element("div").classes("brand-symbol"):
            ui.icon("auto_stories", size="23px")
        ui.label("folio").classes("brand-word")


def local_badge():
    with ui.row().classes("local-badge items-center gap-2"):
        ui.element("span").classes("status-dot")
        ui.label("LOCAL WORKSPACE")


def header(title=None):
    from .settings import settings_dialog
    with ui.element("header").classes("topbar"):
        brand()
        if title:
            ui.element("div").classes("header-divider")
            ui.label(title).classes("header-title").tooltip(title)
        ui.space()
        theme_toggle()
        local_badge()
        if title:
            ui.button("New notebook", icon="add", on_click=notebook_dialog).props('flat aria-label="Create notebook"').classes("header-create")
        ui.button(icon="bar_chart", on_click=lambda: ui.navigate.to("/benchmarks")).props('flat round aria-label="Retrieval benchmarks"').classes("quiet-btn").tooltip("Retrieval benchmarks")
        ui.button(icon="settings", on_click=settings_dialog).props('flat round aria-label="Settings"').classes("quiet-btn").tooltip("Settings")


def empty(icon: str, title: str, subtitle: str):
    with ui.column().classes("empty-state items-center text-center"):
        ui.icon(icon, size="32px").classes("muted")
        ui.label(title).classes("empty-title")
        ui.label(subtitle).classes("muted text-sm leading-relaxed")


def error_text(exc: Exception) -> str:
    message = str(exc)
    code = getattr(exc, "code", None)
    if code == 429:
        message = "Your model provider’s quota has been reached. Wait and retry, or choose another configured model."
    elif code in {500, 502, 503, 504}:
        message = "The model provider is temporarily busy. Try Fast mode or retry shortly. Your question is saved."
    elif code in {401, 403}:
        message = "The provider rejected access. Check GEMINI_API_KEY in .env and this model’s permissions."
    elif code == 404:
        message = "This model is unavailable for your API key. Check its identifier in .env."
    elif isinstance(exc, TimeoutError):
        message = str(exc) or "The model timed out. Try another model or retry your question."
    elif code == 400:
        message = "The model rejected this request. Check its model name and thinking settings, or try the other model."
    elif not isinstance(exc, ValueError):
        message = "The operation could not finish. Check your connection and model settings, then try again."
    return message[:400]


def error_message(exc: Exception):
    ui.notify(error_text(exc), type="negative", position="top", timeout=7000)


def notebook_dialog():
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        ui.label("A fresh page for your ideas").classes("text-xl font-medium")
        ui.label("Give your notebook a name. You can change it anytime.").classes("muted")
        title = ui.input("Notebook name", placeholder="e.g. Machine learning, semester 2").props("outlined autofocus").classes("w-full")
        description = ui.textarea("A little context (optional)").props("outlined rows=2").classes("w-full")

        def create():
            if not title.value.strip():
                title.error = "Enter a notebook name"
                return
            try:
                identifier = db.create_notebook(title.value.strip()[:120], description.value.strip()[:500])
                ui.navigate.to(f"/notebook/{identifier}")
            except Exception as exc:
                error_message(exc)

        title.on("keydown.enter", create)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Create notebook", icon="add", on_click=create).classes("primary-btn")
    dialog.open()


def source_icon(kind: str) -> str:
    return {"pdf": "picture_as_pdf", "docx": "description", "pptx": "slideshow", "xlsx": "table_chart",
            "csv": "table_chart", "html": "language", "png": "image", "jpg": "image"}.get(kind, "description")


def filename_label(name: str) -> str:
    return Path(name).stem.replace("_", " ")
