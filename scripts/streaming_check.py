"""Deterministic browser checks for partial streaming and cancellation; no external API."""
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
from playwright.sync_api import expect, sync_playwright


class DelayedProvider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            time.sleep(1)
            value = {"choices": [{"delta": {"content": "Visible first words [1]. "}}]}
            self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
            self.wfile.flush()
            time.sleep(4)
            value = {"choices": [{"delta": {"content": "Final words after delay."}}]}
            self.wfile.write(("data: " + json.dumps(value) + "\n\ndata: [DONE]\n\n").encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "test-results" / "streaming"
    output.mkdir(exist_ok=True)
    os.environ["NOTEBOOK_DATA_DIR"] = str(output / f"data-{time.time_ns()}")
    os.environ["NOTEBOOK_OFFLINE"] = "0"
    os.environ["NOTEBOOK_NO_SAMPLE"] = "1"
    os.environ["NOTEBOOK_PORT"] = "8083"
    from local_notebook import storage as db
    from local_notebook.ingestion import jobs
    db.initialize()
    provider = ThreadingHTTPServer(("127.0.0.1", 0), DelayedProvider)
    Thread(target=provider.serve_forever, daemon=True).start()
    db.save_settings({"semantic": False, "rerank": False, "provider": "Local / compatible",
                      "model": "delayed-fixture", "fast_model": "delayed-fixture",
                      "endpoint": f"http://127.0.0.1:{provider.server_port}/v1"})
    book = db.create_notebook("Streaming regression fixture")
    source = jobs.add_file(book, "evidence.txt", b"Photosynthesis converts light energy into chemical energy.")
    jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    errors, passed = [], []
    with (output / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-m", "local_notebook.main"], cwd=root, stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for _ in range(100):
                try:
                    if httpx.get("http://127.0.0.1:8083/health").is_success:
                        break
                except httpx.ConnectError:
                    time.sleep(.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:8083/notebook/{book}")
                page.wait_for_function("window.socket?.connected === true")
                page.get_by_placeholder("Ask a question. Make a connection.").fill("Explain photosynthesis")
                page.locator(".send-btn").click()
                expect(page.get_by_text("Sources found. Waiting for delayed-fixture…", exact=True)).to_be_visible()
                expect(page.get_by_text("Visible first words", exact=False)).to_be_visible()
                assert not page.get_by_text("Final words after delay.", exact=False).count()
                passed.extend(["visible waiting state", "partial answer before completion"])
                page.get_by_role("button", name="Stop generation", exact=True).click()
                expect(page.get_by_text("Generation stopped.", exact=False)).to_be_visible()
                assert not page.get_by_text("Final words after delay.", exact=False).count()
                passed.append("stop preserves partial answer")
                page.locator(".studio-tile").filter(has_text="Mind map").click()
                page.get_by_role("button", name="Generate", exact=True).click()
                expect(page.get_by_text("Creating with delayed-fixture", exact=False)).to_be_visible()
                page.get_by_role("button", name="Cancel", exact=True).click()
                expect(page.get_by_text("Create a mind map", exact=True)).not_to_be_visible()
                page.wait_for_timeout(5500)
                assert not db.rows("SELECT id FROM artifacts WHERE notebook_id=?", (book,))
                passed.append("cancelled Studio does not save an artifact")
                browser.close()
            assert not errors, errors
            print(json.dumps({"passed": passed, "javascript_errors": errors}, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=15)
            provider.shutdown()
            provider.server_close()


if __name__ == "__main__":
    main()
