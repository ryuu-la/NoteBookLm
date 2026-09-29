import logging
import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from nicegui import app, ui
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from urllib.parse import urlsplit

from . import providers, storage as db
from .config import DATA
from .ingestion import jobs
from .seed import seed
from .ui.common import header, theme
from .ui.home import home
from .ui.workspace import workspace


class LocalOnlyMiddleware:
    """Check both HTTP and WebSocket origins; the app has no account boundary."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("latin1")
        origin = headers.get(b"origin", b"").decode("latin1")
        valid_host = urlsplit("http://" + host).hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
        valid_origin = not origin or urlsplit(origin).netloc == host
        if not valid_host or not valid_origin:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                response = JSONResponse({"detail": "Only same-origin local access is allowed"}, status_code=403)
                await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def configure():
    db.initialize()
    if os.environ.get("NOTEBOOK_NO_SAMPLE") != "1":
        seed()
    app.add_middleware(LocalOnlyMiddleware)
    app.on_startup(jobs.start)
    app.on_shutdown(jobs.stop)
    app.on_shutdown(providers.close_clients)

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "Folio", "version": "0.2.0",
                "notebooks": len(db.notebooks()), "storage": "local"}

    @app.get("/original/{source_id}")
    def original(source_id: str):
        source = db.one("SELECT * FROM sources WHERE id=?", (source_id,))
        if not source:
            raise HTTPException(404, "Source not found")
        path = Path(source["path"]).resolve()
        if not path.is_relative_to(DATA / "originals") or not path.is_file():
            raise HTTPException(404, "Source file unavailable")
        return FileResponse(path, filename=source["name"], media_type="application/octet-stream",
                            headers={"X-Content-Type-Options": "nosniff"})

    ui.page("/", title="Folio · Your knowledge, connected")(home)
    ui.page("/notebook/{notebook_id}", title="Notebook · Folio")(workspace)
    from .ui.benchmarks import benchmark_page
    ui.page("/benchmarks", title="Retrieval benchmarks · Folio")(benchmark_page)

    @ui.page("/evidence/{chunk_id}", title="Source evidence · Folio")
    def evidence_page(chunk_id: str):
        theme()
        header("Source evidence")
        source = db.one("""SELECT c.*,s.name,s.url FROM chunks c JOIN sources s ON s.id=c.source_id
            WHERE c.id=? AND s.status='ready'""", (chunk_id,))
        with ui.column().classes("p-10 max-w-4xl mx-auto w-full gap-5"):
            if not source:
                ui.label("This passage is no longer available. Its source may have been removed or reindexed.")
                ui.link("Return to notebooks", "/")
                return
            ui.link("Back to notebook", f"/notebook/{source['notebook_id']}")
            ui.label(source["name"]).classes("text-3xl")
            ui.label(source["locator"]).classes("eyebrow")
            ui.label(source["text"]).classes("whitespace-pre-wrap leading-loose text-base")
            ui.link("Download original", f"/original/{source['source_id']}")
            if source["url"]:
                ui.link("Visit original page", source["url"], new_tab=True)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    configure()
    ui.run(host="127.0.0.1", port=int(os.environ.get("NOTEBOOK_PORT", "8080")),
           title="Folio", favicon="📖", reload=False, show=False, reconnect_timeout=30)


if __name__ == "__main__":
    main()
