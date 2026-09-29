"""Exercise the app in an isolated test library and a headless Edge profile."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def check(live=False):
    root = Path(__file__).resolve().parents[1]
    output = root / "test-results" / ("browser-live" if live else "browser-offline")
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "NOTEBOOK_DATA_DIR": str(output / f"data-{int(time.time())}"),
           "NOTEBOOK_MODEL_DIR": str(root / ".data" / "models"), "NOTEBOOK_PORT": "8081",
           "NOTEBOOK_OFFLINE": "0" if live else "1"}
    if not live:
        env.update(GEMINI_API_KEY="", NOTEBOOK_API_KEY="")
    errors, passed, timings = [], [], {}
    with (output / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-m", "local_notebook.main"], env=env,
                                  stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for _ in range(80):
                try:
                    if httpx.get("http://127.0.0.1:8081/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    time.sleep(.25)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
                page.emulate_media(reduced_motion="reduce")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto("http://127.0.0.1:8081")
                page.wait_for_function("window.socket?.connected === true")
                expect(page.locator(".notebook-card").first).to_be_visible()
                page.screenshot(path=str(output / "home.png"), full_page=True)
                passed.append("home")
                page.get_by_role("button", name="Create notebook", exact=True).click()
                page.get_by_label("Notebook name").fill("Browser verification")
                expect(page.get_by_label("API key", exact=True)).to_have_count(0)
                passed.append("notebook creation has no API-key prompt")
                page.get_by_role("button", name="Create notebook", exact=True).last.click()
                expect(page.locator(".composer")).to_be_visible()
                page.get_by_role("button", name="Toggle sources", exact=True).click()
                passed.append("create notebook")
                page.locator('.source-panel').get_by_role("button", name="Add sources", exact=True).click()
                page.locator("input[type=file]").set_input_files({"name": "verification.txt", "mimeType": "text/plain",
                    "buffer": b"Retrieval practice means recalling an idea without looking at notes. Feedback corrects mistakes. Spaced practice distributes learning sessions across several days. Interleaving mixes related question types so a learner chooses an appropriate strategy. A study loop combines collecting reliable sources, explaining key ideas, testing recall, and reflecting on errors."})
                expect(page.get_by_text("Added verification.txt. Indexing in the background.")).to_be_visible(timeout=15000)
                page.keyboard.press("Escape")
                expect(page.get_by_text("1 passage · indexed", exact=True)).to_be_visible(timeout=60000)
                passed.extend(["file upload", "indexing"])
                page.get_by_label("Ask about your sources", exact=True).fill("What is retrieval practice?")
                started = time.perf_counter()
                page.locator(".send-btn").click()
                if live:
                    expect(page.locator(".conversation .markdown").first).to_contain_text(re.compile(r"\S"), timeout=120000)
                    timings["first_visible_answer_s"] = round(time.perf_counter() - started, 2)
                    expect(page.get_by_role("button", name="Save to notes", exact=True)).to_be_visible(timeout=120000)
                    timings["answer_complete_s"] = round(time.perf_counter() - started, 2)
                    expect(page.locator(".citation-chip").first).to_be_visible()
                    passed.extend(['live model chat', 'citations'])
                else:
                    expect(page.locator('.retrieval-status')).to_have_text('Set GEMINI_API_KEY in the project .env and restart the server to get a source-grounded answer.', timeout=30000)
                    expect(page.get_by_text('Source excerpts', exact=True)).to_have_count(0)
                    expect(page.locator('.assistant-message')).to_have_count(0)
                    passed.append('missing model never falls back to pasted source excerpts')
                page.screenshot(path=str(output / "chat.png"), full_page=True)
                if not page.locator('.studio-tile').filter(has_text='Notes').is_visible():
                    page.get_by_role('button', name='Toggle studio', exact=True).click()
                page.locator('.studio-tile').filter(has_text='Notes').click()
                page.get_by_label("Title", exact=True).fill("Browser-tested study note")
                page.get_by_label("Markdown notes").fill("# Retrieval practice\n\nRecall ideas, then check the evidence.\n\n- Use feedback.\n- Return after a delay.")
                with page.expect_download() as download:
                    page.get_by_role("button", name="Save as PDF", exact=True).click()
                download.value.save_as(str(output / "note.pdf"))
                page.get_by_role("button", name="Done", exact=True).click()
                expect(page.get_by_role("button", name="Browser-tested study note")).to_be_visible(timeout=10000)
                page.reload()
                expect(page.get_by_role("button", name="Browser-tested study note")).to_be_visible(timeout=10000)
                if live:
                    expect(page.get_by_role("button", name="Save to notes", exact=True)).to_be_visible()
                passed.extend(["note autosave", "PDF download", "reload persistence"])
                if live:
                    for tile, instructions in [("Mind map", "Make a concise map with 3 leaf nodes, each with citations."),
                                               ("Quiz", "Make exactly 2 multiple choice questions with 3 options each."),
                                               ("Reports", "Write a short study guide with source citations.")]:
                        page.locator(".studio-tile").filter(has_text=tile).click()
                        page.get_by_label("Instructions", exact=True).fill(instructions)
                        started = time.perf_counter()
                        page.get_by_role("button", name="Generate", exact=True).click()
                        ready_button = 'Export mind map' if tile == 'Mind map' else 'Export PDF'
                        expect(page.get_by_role("button", name=ready_button, exact=True)).to_be_visible(timeout=180000)
                        timings[tile.lower().replace(" ", "_") + "_s"] = round(time.perf_counter() - started, 2)
                        if tile == "Quiz":
                            for group in page.locator(".quiz-question").all():
                                group.get_by_role("radio").first.click()
                            page.get_by_role("button", name="Check answers", exact=True).click()
                            expect(page.get_by_text("/ 2 correct", exact=False)).to_be_visible()
                        page.screenshot(path=str(output / (tile.lower().replace(" ", "-") + ".png")), full_page=True)
                        passed.append("generated " + tile.lower())
                        page.keyboard.press("Escape")
                page.get_by_role("button", name="Settings", exact=True).click()
                expect(page.get_by_label("API key", exact=True)).to_have_count(0)
                expect(page.get_by_text("Fast: gemini-3.5-flash-lite", exact=True)).to_be_visible()
                expect(page.get_by_text("Main: gemini-3.8-flash", exact=True)).to_be_visible()
                passed.append("settings shows env models without key entry or backup")
                expect(page.get_by_text("Make yourself at home", exact=True)).to_be_visible()
                page.screenshot(path=str(output / "settings.png"), full_page=True)
                page.keyboard.press("Escape")
                expect(page.get_by_text("Make yourself at home", exact=True)).not_to_be_visible()
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(output / "mobile.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile overflow"
                passed.extend(["settings", "mobile width"])
                page.set_viewport_size({"width": 1440, "height": 1100})
                page.get_by_role("button", name="Notebook options", exact=True).click()
                page.get_by_role("menuitem", name="Retrieval benchmarks", exact=True).click()
                expect(page.get_by_text("Evidence before claims.", exact=True)).to_be_visible()
                expect(page.locator("canvas")).to_have_count(2)
                with page.expect_download() as download:
                    page.get_by_role("button", name="Download results and query judgments").click()
                download.value.save_as(str(output / "retrieval-benchmark.json"))
                assert json.loads((output / "retrieval-benchmark.json").read_text())["queries"] == 54
                page.screenshot(path=str(output / "benchmarks.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_function("document.documentElement.scrollWidth <= window.innerWidth", timeout=5000)
                page.screenshot(path=str(output / "benchmarks-mobile.png"), full_page=True)
                passed.extend(["benchmark charts", "benchmark JSON download", "benchmark mobile width"])
                browser.close()
            assert not errors, errors
            result = {"passed": passed, "javascript_errors": errors, "live_api": live, "timings": timings}
            (output / "result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use the configured real model; provider usage applies")
    check(parser.parse_args().live)
