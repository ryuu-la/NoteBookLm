from nicegui import events, run, ui

from .. import storage as db
from ..config import MAX_UPLOAD
from ..ingestion import jobs
from ..ingestion.parsers import SUPPORTED
from ..ingestion.web import fetch
from .common import empty, error_message, filename_label, source_icon


def add_sources_dialog(notebook_id: str):
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        with ui.row().classes("w-full items-center"):
            ui.label("Add sources").classes("text-xl font-medium")
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props('flat round dense aria-label="Close dialog"')
        ui.label("Bring your documents, websites, and ideas together.").classes("muted")
        with ui.tabs().classes("w-full") as tabs:
            upload_tab = ui.tab("Files", icon="upload_file")
            web_tab = ui.tab("Website", icon="language")
            text_tab = ui.tab("Paste text", icon="content_paste")
        with ui.tab_panels(tabs, value=upload_tab).classes("w-full bg-transparent"):
            with ui.tab_panel(upload_tab).classes("p-0"):
                async def uploaded(event: events.UploadEventArguments):
                    try:
                        data = await event.file.read()
                        await run.io_bound(jobs.add_file, notebook_id, event.file.name, data)
                        ui.notify(f"Added {event.file.name}. Indexing in the background.", type="positive")
                    except Exception as exc:
                        error_message(exc)
                ui.upload(on_upload=uploaded, multiple=True, auto_upload=True, max_file_size=MAX_UPLOAD,
                          on_rejected=lambda: ui.notify("File exceeds the 150 MB limit", type="negative"),
                          label="Drop your sources here, or browse").props(
                              f"accept={','.join(sorted(SUPPORTED))} flat bordered").classes("source-upload w-full")
                ui.label("PDF, Word, slides, spreadsheets, CSV, text, and images · 150 MB per file").classes("text-xs muted mt-3")
                ui.label("Uploads are indexed in the background. Follow their progress in Sources.").classes("text-xs muted mt-2")
                ui.button("Done", on_click=dialog.close).props("flat").classes("mt-3")
            with ui.tab_panel(web_tab).classes("p-0"):
                url = ui.input("Public website URL", placeholder="https://…").props("outlined").classes("w-full")
                status = ui.label("We’ll save a readable snapshot with a link to the original.").classes("text-xs muted")

                async def import_url():
                    import_button.disable()
                    import_button.props("loading")
                    status.set_text("Reading the page…")
                    try:
                        name, data, final_url = await run.io_bound(fetch, url.value.strip())
                        await run.io_bound(jobs.add_file, notebook_id, name, data, final_url)
                        ui.notify("Website added to your sources", type="positive")
                        dialog.close()
                    except Exception as exc:
                        error_message(exc)
                        status.set_text("Try a public article URL, or paste the text in the next tab.")
                    finally:
                        import_button.enable()
                        import_button.props(remove="loading")

                import_button = ui.button("Add website", icon="add_link", on_click=import_url).classes("primary-btn mt-4")
            with ui.tab_panel(text_tab).classes("p-0"):
                title = ui.input("Source title", placeholder="Lecture notes").props("outlined").classes("w-full")
                text = ui.textarea("Your text").props("outlined rows=8").classes("w-full")

                async def paste():
                    try:
                        if not text.value.strip():
                            raise ValueError("Paste some text first.")
                        await run.io_bound(jobs.add_file, notebook_id, (title.value.strip() or "Pasted notes") + ".txt",
                                           text.value.encode())
                        dialog.close()
                        ui.notify("Text added to your sources", type="positive")
                    except Exception as exc:
                        error_message(exc)
                ui.button("Add text", icon="add", on_click=paste).classes("primary-btn mt-3")
    dialog.open()


def source_preview(source: dict):
    with ui.dialog() as dialog, ui.card().classes("modal-card source-preview"):
        with ui.row().classes("items-center w-full"):
            ui.icon(source_icon(source["kind"]), size="24px")
            ui.label(source["name"]).classes("text-lg font-medium break-all")
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props('flat round dense aria-label="Close dialog"')
        if source["url"]:
            ui.link("Open original website", source["url"], new_tab=True).classes("text-sm")
        else:
            ui.link("Open original file", f"/original/{source['id']}", new_tab=True).classes("text-sm")
        timing = f" · Indexed in {source['elapsed_seconds']:.1f}s" if source.get("elapsed_seconds") else ""
        ui.label(f"{source['chunks']:,} searchable passages" + timing).classes("muted text-xs")
        chunks = db.rows("SELECT * FROM chunks WHERE source_id=? ORDER BY ordinal LIMIT 80", (source["id"],))
        with ui.scroll_area().classes("w-full h-96"):
            for chunk in chunks:
                ui.label(chunk["locator"]).classes("eyebrow mt-4 mb-2")
                ui.label(chunk["text"]).classes("whitespace-pre-wrap leading-relaxed text-sm")
        if source["chunks"] > 80:
            ui.label("Preview shows the first 80 passages. Search chat to find evidence throughout the file.").classes("muted text-xs")
    dialog.open()


def source_panel(notebook_id: str, on_collapse=None):
    from .discovery import discovery_dialog
    with ui.column().classes("source-panel panel"):
        with ui.row().classes("panel-heading w-full items-center"):
            ui.icon("library_books", size="18px")
            ui.label("Sources")
            ui.space()
            ui.button(icon="first_page", on_click=on_collapse).props('flat dense round size=sm aria-label="Collapse sources"').classes("sidebar-collapse").tooltip("Collapse sources")
        with ui.column().classes("source-actions w-full"):
            ui.button("Add sources", icon="add", on_click=lambda: add_sources_dialog(notebook_id)).props("outline").classes("w-full add-sources-btn")
            ui.button("Discover sources on the web", icon="travel_explore", on_click=lambda: discovery_dialog(notebook_id)).props("flat dense size=sm").classes("w-full discovery-btn")
            search = ui.input(placeholder="Find a source…").props('dense borderless clearable aria-label="Find a source"').classes("source-search")
            with search.add_slot("prepend"):
                ui.icon("search", size="18px").classes("muted")

        controls = {}

        def retry_source(identifier):
            try:
                jobs.retry(identifier)
                poll()
            except Exception as exc:
                error_message(exc)

        def select_one(event, identifier):
            db.execute("UPDATE sources SET selected=? WHERE id=?", (int(event.value), identifier))
            poll()

        @ui.refreshable
        def listing():
            controls.clear()
            all_sources = db.sources(notebook_id)
            query = (search.value or "").strip().lower()
            sources = [row for row in all_sources if query in row["name"].lower()]
            if not all_sources:
                empty("note_add", "Your library starts here", "Add a document, paste your notes, or bring something from the web.")
                return
            with ui.row().classes("source-select-all items-center w-full"):
                ui.label(f"{len(all_sources)} SOURCE{'S' if len(all_sources) != 1 else ''}").classes("eyebrow")
                ui.space()
                def select_all(event):
                    db.execute("UPDATE sources SET selected=? WHERE notebook_id=?", (int(event.value), notebook_id))
                    poll()
                ui.checkbox(value=all(row["selected"] for row in all_sources), on_change=select_all).props('dense size=sm aria-label="Select all sources"').tooltip("Select all sources")
            if not sources:
                empty("search_off", "No matching sources", "Try a different name.")
            for source in sources:
                with ui.row().classes("source-item w-full items-start no-wrap"):
                    ui.icon(source_icon(source["kind"]), size="20px").classes(f"source-file-icon kind-{source['kind']}")
                    with ui.column().classes("source-details gap-1"):
                        ui.button(filename_label(source["name"]), on_click=lambda row=source: source_preview(db.one("SELECT * FROM sources WHERE id=?", (row["id"],)) or row)).props("flat dense align=left").classes("source-name").tooltip(source["name"])
                        label = ui.label("").classes("source-status")
                        bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
                        detail = ui.label("").classes("source-status import-detail").props('role=status aria-live=polite')
                        controls[source["id"]] = (label, bar, detail)
                        if source["status"] == "error":
                            label.classes(add="source-error")
                            ui.button("Retry", icon="refresh", on_click=lambda sid=source["id"]: retry_source(sid)).props("flat dense size=sm")
                    with ui.column().classes("gap-1 items-center"):
                        ui.checkbox(value=bool(source["selected"]), on_change=lambda event, sid=source["id"]: select_one(event, sid)).props('dense size=sm aria-label="Use this source"').tooltip("Use this source")
                        with ui.button(icon="more_horiz").props('flat dense round size=xs aria-label="Source options"'):
                            with ui.menu():
                                ui.menu_item("Preview", on_click=lambda row=source: source_preview(db.one("SELECT * FROM sources WHERE id=?", (row["id"],)) or row))
                                if source["status"] in {"ready", "error", "cancelled"}:
                                    ui.menu_item("Reindex", on_click=lambda sid=source["id"]: retry_source(sid))
                                if source["status"] in {"queued", "parsing", "indexing"}:
                                    ui.menu_item("Cancel import", on_click=lambda sid=source["id"]: jobs.update(sid, status="cancelled", detail="Import cancelled"))
                                ui.menu_item("Remove source", on_click=lambda row=source: remove_dialog(row))
            update_progress(all_sources)

        def update_progress(sources):
            for source in sources:
                if source["id"] not in controls:
                    continue
                label, bar, detail = controls[source["id"]]
                status, percent = source["status"], source["progress"]
                if status == "ready":
                    label.set_text(f"{source['chunks']} passage{'s' if source['chunks'] != 1 else ''} · indexed")
                else:
                    label.set_text({"queued": "Waiting to index", "parsing": "Reading document", "indexing": "Building search index", "error": "Needs attention", "cancelled": "Import cancelled"}.get(status, status) + (f" · {percent}%" if status in {"parsing", "indexing"} and percent else ""))
                bar.visible = status in {"queued", "parsing", "indexing"}
                bar.set_value(percent / 100)
                bar.props("indeterminate" if not percent else "", remove="indeterminate" if percent else "")
                detail.set_text(source["error"] if status == "error" else (source.get("detail") or ""))
                detail.visible = status in {"parsing", "indexing", "error"}

        with ui.element("div").classes("source-list"):
            listing()
        with ui.row().classes("source-footer items-center gap-2"):
            ui.icon("lock_outline", size="14px")
            ui.label("Saved on this computer")
        previous = {"value": None}

        def poll():
            sources = db.sources(notebook_id)
            signature = [(row["id"], row["status"], row["selected"]) for row in sources]
            if signature != previous["value"]:
                previous["value"] = signature
                listing.refresh()
            else:
                update_progress(sources)
        search.on_value_change(listing.refresh)
        ui.timer(.6, poll)


def remove_dialog(source):
    with ui.dialog() as dialog, ui.card().classes("modal-card"):
        ui.label("Remove this source?").classes("text-xl")
        ui.label("The original and search passages will be removed. Saved notes and answers may still quote this source.").classes("muted")

        async def remove():
            try:
                await run.io_bound(jobs.delete_source, source["id"])
                dialog.close()
            except Exception as exc:
                error_message(exc)
        with ui.row().classes("justify-end w-full"):
            ui.button("Keep source", on_click=dialog.close).props("flat")
            ui.button("Remove", on_click=remove).props("color=negative")
    dialog.open()
