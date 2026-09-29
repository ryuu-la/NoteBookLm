from urllib.parse import quote_plus

from nicegui import run, ui

from ..ingestion.discovery import discover
from ..ingestion.jobs import add_file
from ..ingestion.web import fetch
from .common import error_message


def discovery_dialog(notebook_id: str):
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        with ui.row().classes("w-full items-center"):
            ui.label("Follow your curiosity").classes("text-xl")
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props('flat round aria-label="Close dialog"')
        query = ui.input("What would you like to explore?").props("outlined").classes("w-full")
        engine = ui.select(["Browser search", "Wikipedia", "Gemini web search"], value="Browser search", label="Search with").props("outlined").classes("w-full")
        ui.label("Browser search opens public results in a new tab. Copy a useful URL and add it with Add sources → Website. Integrated search depends on provider availability and quota.").classes("text-xs muted")
        results = ui.column().classes("w-full gap-3")

        async def add(item, button):
            button.disable()
            button.props("loading")
            try:
                name, data, url = await run.io_bound(fetch, item["url"])
                await run.io_bound(add_file, notebook_id, name, data, url)
                button.set_text("Added")
                ui.notify("Source added and queued for indexing", type="positive")
            except Exception as exc:
                button.enable()
                error_message(exc)
            finally:
                button.props(remove="loading")

        async def search():
            if not query.value.strip():
                ui.notify("Enter a topic to search.")
                return
            if engine.value == "Browser search":
                with results:
                    results.clear()
                    ui.link("Open search results ↗", "https://www.google.com/search?q=" + quote_plus(query.value),
                            new_tab=True).classes("text-base font-medium")
                    ui.label("Copy a result’s URL, then add it from the Website tab. You choose exactly what enters your library.").classes("text-xs muted")
                return
            search_button.disable()
            search_button.props("loading")
            results.clear()
            try:
                found = await discover(query.value, engine.value)
                with results:
                    if not found:
                        ui.label("No sources found. Try a more specific topic.").classes("muted")
                    for item in found:
                        with ui.column().classes("w-full discovery-result"):
                            ui.link(item["title"], item["url"], new_tab=True).classes("font-medium")
                            ui.label(item["description"]).classes("text-xs muted")
                            button = ui.button("Add source", icon="add").props("flat dense size=sm")
                            button.on_click(lambda row=item, control=button: add(row, control))
            except Exception as exc:
                error_message(exc)
            finally:
                search_button.enable()
                search_button.props(remove="loading")
        search_button = ui.button("Find sources", icon="search", on_click=search).classes("primary-btn")
        query.on("keydown.enter", search)
    dialog.open()
