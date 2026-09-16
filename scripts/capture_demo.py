"""Capture already-generated test artifacts without further model calls."""
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
data = sorted((root / "test-results" / "browser-live").glob("data-*"))[-1]
output = root / "docs" / "images"
output.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(data / "notebook.db") as connection:
    notebook = connection.execute("SELECT id FROM notebooks WHERE title='Browser verification'").fetchone()[0]
    artifacts = connection.execute("SELECT kind,title FROM artifacts WHERE notebook_id=? AND kind!='note'", (notebook,)).fetchall()
env = {**os.environ, "NOTEBOOK_DATA_DIR": str(data), "NOTEBOOK_MODEL_DIR": str(root / ".data" / "models"),
       "NOTEBOOK_PORT": "8082", "NOTEBOOK_OFFLINE": "1"}
with (root / "test-results" / "capture.log").open("w") as log:
    server = subprocess.Popen([sys.executable, "-m", "local_notebook.main"], env=env, stdout=log, stderr=log,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(80):
            try:
                if httpx.get("http://127.0.0.1:8082/health").status_code == 200:
                    break
            except httpx.ConnectError:
                time.sleep(.25)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.emulate_media(reduced_motion="reduce")
            page.on("pageerror", lambda error: print("Browser error:", error))
            page.goto(f"http://127.0.0.1:8082/notebook/{notebook}")
            page.wait_for_function("window.socket?.connected === true")
            expect(page.locator(".artifact-row")).to_have_count(4)
            for kind, title in artifacts:
                print("Opening", kind, title, flush=True)
                page.get_by_role("button", name=title, exact=True).click()
                expect(page.get_by_role("button", name="Export PDF", exact=True)).to_be_visible(timeout=15000)
                page.locator(".artifact-dialog").screenshot(path=str(output / f"{kind}.png"), animations="disabled")
                page.keyboard.press("Escape")
                expect(page.get_by_role("button", name="Export PDF", exact=True)).not_to_be_visible()
            sample = page.url
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(output / "mobile.png"), full_page=True, animations="disabled")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=15)
print("Captured existing generated artifacts without model calls")
