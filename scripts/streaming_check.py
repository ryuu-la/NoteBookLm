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
        self.server.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        behavior = self.server.behavior
        if behavior == "fail":
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            time.sleep(.5)
            value = {"choices": [{"delta": {"content": "Visible first words [1]. "}}]}
            self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
            self.wfile.flush()
            time.sleep(5 if behavior == "stall" else .5)
            value = {"choices": [{"delta": {"content": "More words arriving continuously. "}}]}
            self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
            self.wfile.flush()
            time.sleep(1.5)
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
    provider.behavior, provider.requests = "normal", []
    Thread(target=provider.serve_forever, daemon=True).start()
    db.save_settings({"semantic": False, "rerank": False, "provider": "Local / compatible",
                      "model": "delayed-fixture", "fast_model": "delayed-fixture",
                      "endpoint": f"http://127.0.0.1:{provider.server_port}/v1"})
    book = db.create_notebook("Streaming regression fixture")
    source = jobs.add_file(book, "evidence.txt", b"Photosynthesis converts light energy into chemical energy.")
    jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    errors, passed = [], []
    with (output / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-c", "from local_notebook import providers; providers.STREAM_IDLE_TIMEOUT=2; from local_notebook.main import main; main()"], cwd=root, stdout=log, stderr=log,
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
                page = browser.new_page(viewport={"width": 1354, "height": 624})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:8083/notebook/{book}")
                page.wait_for_function("window.socket?.connected === true")
                page.locator('.suggestion').first.click()
                expect(page.get_by_text("Preparing your answer…", exact=True)).to_be_visible()
                expect(page.locator('.chat-progress, .skeleton-line')).to_have_count(0)
                expect(page.locator('.retrieval-status')).to_have_text('')
                expect(page.get_by_text("Visible first words", exact=False)).to_be_visible()
                expect(page.locator('.streaming-answer .markdown')).to_be_in_viewport()
                expect(page.locator('.streaming-answer .markdown')).to_contain_text('More words arriving continuously.')
                assert not page.get_by_text("Final words after delay.", exact=False).count()
                page.screenshot(path=str(output / 'visible-stream.png'))
                passed.extend(["suggestion streams in a stable context", "successive chunks appear in viewport before completion"])

                def finished():
                    expect(page.get_by_role('button', name='Stop generation', exact=True)).not_to_be_visible(timeout=10000)
                    expect(page.locator('.chat-progress')).not_to_be_visible()
                    expect(page.locator('.send-btn')).to_be_visible()

                finished()
                expect(page.locator('.retrieval-status')).to_have_text('')
                assert len(db.messages(book)) == 2
                page.get_by_role('button', name='Retry answer', exact=True).click()
                expect(page.locator('.streaming-answer .markdown')).to_contain_text('Visible first words')
                finished()
                assert len(db.messages(book)) == 2
                passed.append('retry streams and replaces answer without a duplicate question')

                page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
                page.get_by_role('button', name='Copy question', exact=True).click()
                page.wait_for_function("async () => (await navigator.clipboard.readText()).includes('key ideas')")
                page.get_by_role('button', name='Edit question', exact=True).click()
                page.get_by_label('Your question', exact=True).fill('Explain photosynthesis with an example.')
                page.get_by_role('button', name='Save and send', exact=True).click()
                expect(page.locator('.streaming-answer .markdown')).to_contain_text('Visible first words')
                finished()
                assert db.messages(book)[0]['text'] == 'Explain photosynthesis with an example.'
                assert len(db.messages(book)) == 2
                passed.append('copy and edit user question, then stream the revised answer')

                page.get_by_label('Ask about your sources', exact=True).fill('How does photosynthesis work?')
                page.locator('.send-btn').click()
                expect(page.locator('.streaming-answer .markdown')).to_contain_text('Visible first words')
                page.get_by_role("button", name="Stop generation", exact=True).click()
                finished()
                assert 'Generation stopped.' in db.messages(book)[-1]['text']
                passed.append("stop preserves partial answer")

                provider.behavior = 'stall'
                page.get_by_label('Ask about your sources', exact=True).fill('Explain photosynthesis again')
                page.locator('.send-btn').click()
                expect(page.locator('.streaming-answer .markdown')).to_contain_text('Visible first words')
                finished()
                expect(page.locator('.retry-generation')).to_be_visible()
                assert 'Connection interrupted.' in db.messages(book)[-1]['text']
                original = db.messages(book)
                provider.behavior = 'fail'
                page.locator('.retry-generation').click()
                expect(page.locator('.retrieval-status')).to_contain_text('Your original conversation is kept')
                finished()
                assert db.messages(book) == original
                provider.behavior = 'normal'
                page.locator('.retry-generation').click()
                expect(page.locator('.streaming-answer .markdown')).to_contain_text('Visible first words')
                finished()
                assert len(db.messages(book)) == 6
                assert 'Final words after delay.' in db.messages(book)[-1]['text']
                passed.extend(['stalled stream preserves partial text and clears loading', 'failed retry preserves original history', 'retry recovers after provider failure'])
                page.get_by_role("button", name="Toggle studio", exact=True).click()
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
            assert 'parent element this slot belongs to has been deleted' not in (output / 'server.log').read_text()
            print(json.dumps({"passed": passed, "javascript_errors": errors}, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=15)
            provider.shutdown()
            provider.server_close()


if __name__ == "__main__":
    main()
