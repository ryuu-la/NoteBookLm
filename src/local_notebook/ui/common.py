from pathlib import Path

from nicegui import ui

from .. import storage as db
from ..config import STYLES


def theme():
    ui.dark_mode().enable()
    ui.colors(primary="#b5c8ff", secondary="#a7a2ff", accent="#c8b8f5", dark="#202125", positive="#a7d5ba")
    for filename in ("base.css", "home.css", "workspace.css"):
        ui.add_css((STYLES / filename).read_text(encoding="utf-8"))


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
            ui.label(title).classes("header-title")
        ui.space()
        local_badge()
        ui.button(icon="bar_chart", on_click=lambda: ui.navigate.to("/benchmarks")).props('flat round aria-label="Retrieval benchmarks"').classes("quiet-btn").tooltip("Retrieval benchmarks")
        ui.button(icon="settings", on_click=settings_dialog).props('flat round aria-label="Settings"').classes("quiet-btn").tooltip("Settings")


def empty(icon: str, title: str, subtitle: str):
    with ui.column().classes("empty-state items-center text-center"):
        ui.icon(icon, size="32px").classes("muted")
        ui.label(title).classes("empty-title")
        ui.label(subtitle).classes("muted text-sm leading-relaxed")


def error_message(exc: Exception):
    message = str(exc)
    code = getattr(exc, "code", None)
    if code == 429:
        message = "Your model provider’s quota has been reached. Wait and retry, or choose another configured model."
    elif code in {500, 502, 503, 504}:
        message = "The model provider is temporarily busy. Try Fast mode or retry shortly. Your question is saved."
    elif code in {401, 403}:
        message = "The provider rejected access. Check the API key and this model’s permissions in Settings."
    elif code == 404:
        message = "This model is unavailable for your API key. Check its identifier in Settings."
    elif not isinstance(exc, ValueError):
        message = "The operation could not finish. Check your connection and model settings, then try again."
    ui.notify(message[:400], type="negative", position="top", timeout=7000)


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
            identifier = db.create_notebook(title.value.strip()[:120], description.value.strip()[:500])
            ui.navigate.to(f"/notebook/{identifier}")

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
