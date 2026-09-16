from datetime import datetime

from nicegui import ui

from .. import storage as db
from .common import header, notebook_dialog, theme


def home():
    theme()
    header()
    with ui.element("main").classes("home-main"):
        with ui.row().classes("welcome-row items-end justify-between w-full"):
            with ui.column().classes("gap-3"):
                ui.label("A SPACE FOR YOUR CURIOSITY").classes("eyebrow")
                ui.label("Good ideas start\nwith a little exploration.").classes("hero-title whitespace-pre-line")
                ui.label("Bring your sources. Connect the dots. Make it yours.").classes("hero-subtitle")
            ui.button("Create notebook", icon="add", on_click=notebook_dialog).classes("primary-btn create-btn")
        with ui.row().classes("library-toolbar w-full items-center"):
            ui.label("Your notebooks").classes("section-title")
            count = len(db.notebooks())
            ui.label(str(count).zfill(2)).classes("count-badge")
            ui.space()
            search = ui.input(placeholder="Find a notebook…").props("outlined dense clearable").classes("notebook-search")
            with search.add_slot("prepend"):
                ui.icon("search", size="19px")
            sort = ui.select(["Last opened", "Name"], value="Last opened").props("borderless dense options-dense").classes("sort-control")
            with ui.button_group().props("flat").classes("view-toggle"):
                grid_button = ui.button(icon="grid_view").props("flat dense").classes("active-view")
                list_button = ui.button(icon="view_list").props("flat dense")
        state = {"list": False}

        @ui.refreshable
        def cards():
            books = [book for book in db.notebooks() if (search.value or "").lower() in book["title"].lower()]
            if sort.value == "Name":
                books.sort(key=lambda book: book["title"].lower())
            with ui.element("div").classes("notebook-grid" + (" list-layout" if state["list"] else "")):
                for book in books:
                    notebook_card(book)
                with ui.card().classes("new-notebook-card").props('role=button tabindex=0 aria-label="Start a new notebook"').on("click", notebook_dialog).on("keydown.enter", notebook_dialog):
                    with ui.element("div").classes("new-circle"):
                        ui.icon("add", size="28px")
                    ui.label("Start something new").classes("font-medium text-base")
                    ui.label("A blank page. Endless possibilities.").classes("muted text-sm")
            if not books and search.value:
                ui.label("No notebooks match your search.").classes("muted")

        def switch_view(as_list):
            state["list"] = as_list
            grid_button.classes(remove="active-view" if as_list else "", add="active-view" if not as_list else "")
            list_button.classes(remove="active-view" if not as_list else "", add="active-view" if as_list else "")
            cards.refresh()

        grid_button.on_click(lambda: switch_view(False))
        list_button.on_click(lambda: switch_view(True))
        search.on_value_change(cards.refresh)
        sort.on_value_change(cards.refresh)
        cards()
        with ui.row().classes("home-bottom w-full items-center"):
            with ui.row().classes("items-center gap-3"):
                ui.icon("shield", size="18px")
                ui.label("An open workspace. A private library.")
            ui.space()
            ui.label("Built for curious minds.").classes("muted")
        with ui.row().classes("feature-strip"):
            feature("library_books", "All your sources, together", "PDFs, documents, slides, spreadsheets, and the web.")
            feature("forum", "Ask. Understand. Connect.", "Follow the evidence with answers linked to your sources.")
            feature("account_tree", "Turn knowledge into something", "Explore mind maps, test yourself, and write better notes.")
    with ui.element("footer").classes("home-footer"):
        ui.label("FOLIO / LOCAL NOTEBOOK")
        ui.label("No accounts. Just ideas.")


def feature(icon, title, caption):
    with ui.row().classes("feature-item gap-4"):
        ui.icon(icon, size="22px")
        with ui.column().classes("gap-1"):
            ui.label(title).classes("font-medium")
            ui.label(caption).classes("text-xs muted leading-relaxed")


def notebook_card(book):
    with ui.link(target=f"/notebook/{book['id']}").classes("notebook-link no-underline"):
        with ui.card().classes("notebook-card"):
            with ui.element("div").classes(f"card-art art-{book['color']}"):
                ui.element("div").classes("orbit orbit-one")
                ui.element("div").classes("orbit orbit-two")
                ui.element("div").classes("orbit orbit-three")
                ui.icon(book["icon"], size="52px").classes("art-icon")
                ui.label("NOTEBOOK").classes("art-caption")
                ui.icon("north_east", size="20px").classes("card-arrow")
            with ui.column().classes("card-body gap-2"):
                ui.label(book["title"]).classes("card-title")
                ui.label(book["description"] or "Your next discovery starts here.").classes("card-description")
                with ui.row().classes("card-meta w-full items-center"):
                    ui.icon("description", size="14px")
                    ui.label(f"{book['source_count']} sources")
                    ui.space()
                    ui.label(datetime.fromisoformat(book["updated_at"]).strftime("%b %d, %Y"))
