"""Check long conversations and composer sizing in an isolated local notebook."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "test-results" / "chat-layout"
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        NOTEBOOK_DATA_DIR=str(output / f"data-{time.time_ns()}"),
        NOTEBOOK_PORT="8083", NOTEBOOK_OFFLINE="1", NOTEBOOK_NO_SAMPLE="1",
    )
    from local_notebook import storage as db
    db.initialize()
    book = db.create_notebook("Machine Learning", "A notebook for understanding deep learning.")
    answer = """## How deep learning represents ideas

Deep learning builds increasingly useful representations from data. Each layer combines simpler patterns into richer concepts.

- **Feedforward networks and scaling:** A network transforms its input through successive layers. Convolutional networks can capture local image patterns, while recurrent networks model sequences.
- **Latent variables:** Training discovers useful internal features without requiring a person to name every concept in advance.
- **Regularization:** Constraints and examples help the model generalize beyond the training set.

### Connect the concepts

Representations, optimization, and generalization work together. A useful representation makes a task easier, while feedback guides how that representation changes.

| Concept | What to look for |
| --- | --- |
| Representation | Features that preserve useful information |
| Optimization | Feedback that improves predictions |
| Generalization | Performance on examples outside training |

Follow the citations to compare these ideas with the original sources. [1]

### Try the idea

Use a small example to inspect the output:

```python
prediction = model.predict(example)
print(prediction)
```

---

Compare the prediction with the original example, then revisit the features that mattered.
"""
    citations = [{"number": n, "id": f"fixture-{n}", "name": "Deep Learning — Ian Goodfellow, Yoshua Bengio and Aaron Courville"}
                 for n in range(1, 5)]
    for _ in range(3):
        db.add_message(book, "user", "Explain the key ideas in deep learning and how they connect.")
        db.add_message(book, "assistant", answer, citations)
    errors, checks = [], []
    with (output / "server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "local_notebook.main"], cwd=root, stdout=log, stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            for _ in range(100):
                try:
                    if httpx.get("http://127.0.0.1:8083/health").is_success:
                        break
                except httpx.ConnectError:
                    time.sleep(.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1350, "height": 640})
                page.emulate_media(reduced_motion="reduce")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:8083/notebook/{book}")
                page.wait_for_function("window.socket?.connected === true")
                expect(page.locator(".assistant-message")).to_have_count(3)
                page.wait_for_timeout(400)
                expect(page.locator('.source-panel')).not_to_be_visible()
                expect(page.locator('.studio-panel')).not_to_be_visible()
                page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
                page.get_by_role('button', name='Copy code', exact=True).last.click()
                page.wait_for_function("async () => (await navigator.clipboard.readText()) === 'prediction = model.predict(example)\\nprint(prediction)\\n'")
                page.get_by_role('button', name='Copy answer', exact=True).last.click()
                page.wait_for_function("async () => (await navigator.clipboard.readText()).includes('How deep learning represents ideas')")
                page.locator('.model-select').click()
                page.get_by_role('option', name='Main', exact=True).click()
                expect(page.locator('.model-select')).to_contain_text('Main')
                page.get_by_role('button', name='Add sources', exact=True).click()
                expect(page.locator('input[type=file]')).to_be_attached()
                page.get_by_role('button', name='Done', exact=True).click()

                def verify(label):
                    dimensions = page.evaluate("""() => {
                        const rect = selector => {
                            const r = document.querySelector(selector).getBoundingClientRect();
                            return {x:r.x, y:r.y, width:r.width, height:r.height, bottom:r.bottom};
                        };
                        return {pageWidth:document.documentElement.scrollWidth,
                            pageHeight:document.documentElement.scrollHeight,
                            viewportWidth:innerWidth, viewportHeight:innerHeight,
                            conversation:rect('.conversation'), reading:rect('.conversation-inner'),
                            composer:rect('.composer')};
                    }""")
                    assert dimensions["pageWidth"] <= dimensions["viewportWidth"], (label, dimensions)
                    assert dimensions["pageHeight"] <= dimensions["viewportHeight"] + 2, (label, dimensions)
                    assert dimensions["composer"]["bottom"] <= dimensions["viewportHeight"], (label, dimensions)
                    assert dimensions["conversation"]["bottom"] <= dimensions["composer"]["y"], (label, dimensions)
                    assert dimensions["conversation"]["height"] >= 200, (label, dimensions)
                    assert abs(dimensions["reading"]["width"] - dimensions["composer"]["width"]) <= 32, (label, dimensions)
                    checks.append({"layout": label, **dimensions})

                for sources, studio in [(False, False), (True, False), (True, True), (False, True)]:
                    for side, collapsed in [("sources", sources), ("studio", studio)]:
                        button = page.get_by_role("button", name=f"Toggle {side}", exact=True)
                        if (button.get_attribute("aria-expanded") == "false") != collapsed:
                            button.click()
                            expect(button).to_have_attribute("aria-expanded", str(not collapsed).lower())
                    page.wait_for_timeout(100)
                    label = f"desktop-sources-{sources}-studio-{studio}"
                    verify(label)
                    if sources and studio:
                        assert 760 <= checks[-1]["reading"]["width"] <= 780, checks[-1]
                        assert checks[-1]["composer"]["height"] <= 64, checks[-1]
                        assert abs(checks[-1]["reading"]["x"] - (1350 - 768) / 2) <= 2
                        expect(page.locator('.source-panel')).not_to_be_visible()
                        expect(page.locator('.studio-panel')).not_to_be_visible()
                        page.screenshot(path=str(output / "desktop-focus.png"))
                        page.locator(".conversation").evaluate("el => el.scrollTop = 0")
                        page.screenshot(path=str(output / "desktop-answer.png"))
                    if not sources and not studio:
                        page.screenshot(path=str(output / "desktop-panels.png"))

                for width, height in [(1182, 629), (1124, 623), (1024, 768), (768, 1024), (390, 844), (320, 640), (1350, 640), (1920, 1080)]:
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(150)
                    verify(f"{width}x{height}")
                    if width <= 1000:
                        for side in ["sources", "studio", "chat"]:
                            page.get_by_role("button", name=f"Show {side}", exact=True).click()
                            expect(page.locator(f".{side if side != 'sources' else 'source'}-panel")).to_be_visible()
                    question = page.get_by_label("Ask about your sources", exact=True)
                    question.fill("\n".join(["A longer question with several details."] * 12))
                    verify(f"{width}x{height}-multiline")
                    question.fill("")
                    if width == 390:
                        page.screenshot(path=str(output / "mobile-chat.png"))
                page.get_by_role('button', name='Notebook options', exact=True).click()
                page.get_by_role('menuitem', name='Clear conversation', exact=True).click()
                page.get_by_role('button', name='Clear chat', exact=True).click()
                expect(page.locator('.assistant-message')).to_have_count(0)
                expect(page.get_by_role('button', name='Add your first source', exact=True)).to_be_visible()
                browser.close()
            assert not errors, errors
            (output / "result.json").write_text(json.dumps({"checks": checks, "errors": errors}, indent=2), encoding="utf-8")
            print(f"Passed {len(checks)} chat layout checks; no JavaScript errors. Screenshots: {output}")
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    main()
