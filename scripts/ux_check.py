"""Isolated UX checks: responsive panels, source selection, real indexing progress, and motion."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
from fpdf import FPDF
from playwright.sync_api import expect, sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'test-results' / 'ux-refresh'
    output.mkdir(exist_ok=True)
    os.environ.update(NOTEBOOK_DATA_DIR=str(output / f'data-{time.time_ns()}'),
                      NOTEBOOK_MODEL_DIR=str(root / '.data' / 'models'), NOTEBOOK_PORT='8082',
                      NOTEBOOK_OFFLINE='1', NOTEBOOK_NO_SAMPLE='1')
    from local_notebook import storage as db
    db.initialize()
    book = db.create_notebook('A clearer way to learn', 'Explore your reading, follow the evidence, and make the ideas your own.')
    document = FPDF()
    document.set_font('Helvetica', size=11)
    for n in range(140):
        document.add_page()
        document.multi_cell(0, 6, f'Study record {n + 1}. Retrieval practice strengthens learning by recalling information. '
                            'Spaced practice distributes study over time. Feedback helps correct misconceptions. '
                            'These techniques can work together in a weekly study plan.')
    pdf = bytes(document.output())
    errors, passed, progress_values = [], [], []
    with (output / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'local_notebook.main'], cwd=root, stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for _ in range(100):
                try:
                    if httpx.get('http://127.0.0.1:8082/health').is_success:
                        break
                except httpx.ConnectError:
                    time.sleep(.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1336, 'height': 768})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:8082/notebook/{book}')
                page.wait_for_function('window.socket?.connected === true')
                page.get_by_role('button', name='Toggle sources', exact=True).click()
                page.get_by_role('button', name='Toggle studio', exact=True).click()
                expect(page.get_by_text('A little knowledge goes a long way.', exact=False)).not_to_be_visible()
                expect(page.get_by_role('button', name='Add your first source')).to_be_visible()
                expect(page.locator('.send-btn')).to_be_disabled()
                passed.append('empty notebook and disabled composer')
                page.locator('.source-panel').get_by_role('button', name='Add sources', exact=True).click()
                page.locator('input[type=file]').set_input_files({'name': 'Indexing sample.pdf', 'mimeType': 'application/pdf', 'buffer': pdf})
                expect(page.get_by_text('Added Indexing sample.pdf. Indexing in the background.', exact=True)).to_be_visible(timeout=15000)
                page.get_by_role('button', name='Done', exact=True).click()
                expect(page.get_by_role('button', name='Done', exact=True)).not_to_be_visible()
                expect(page.locator('.source-item .q-linear-progress')).to_be_visible(timeout=15000)
                expect(page.locator('.import-summary')).to_have_count(0)
                page.screenshot(path=str(output / 'indexing.png'), animations='disabled')
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    row = db.sources(book)[0]
                    progress_values.append(row['progress'])
                    if row['status'] == 'ready':
                        break
                    assert row['status'] != 'error', row['error']
                    page.wait_for_timeout(200)
                assert row['status'] == 'ready' and row['chunks'] == 140
                assert progress_values == sorted(progress_values)
                assert any(0 < value < 100 for value in progress_values)
                expect(page.get_by_text('140 passages · indexed', exact=True)).to_be_visible()
                expect(page.locator('.source-item .q-linear-progress')).not_to_be_visible()
                passed.extend(['real PDF indexing progress', 'ready state and complete count'])
                page.get_by_label('Find a source').fill('does-not-exist')
                expect(page.get_by_text('No matching sources', exact=True)).to_be_visible()
                page.get_by_label('Find a source').fill('')
                expect(page.get_by_role('button', name='Indexing sample', exact=True)).to_be_visible()
                passed.append('source filtering')
                page.get_by_label('Ask about your sources').fill('Explain retrieval practice')
                expect(page.locator('.send-btn')).to_be_enabled()
                page.get_by_role('checkbox', name='Use this source', exact=True).click()
                expect(page.locator('.send-btn')).to_be_disabled()
                page.get_by_role('checkbox', name='Use this source', exact=True).click()
                expect(page.locator('.send-btn')).to_be_enabled()
                page.get_by_label('Ask about your sources').fill('')
                passed.append('composer follows selected sources')
                initial = page.locator('.chat-panel').bounding_box()['width']
                page.get_by_role('button', name='Collapse sources', exact=True).click()
                page.get_by_role('button', name='Collapse studio', exact=True).click()
                expect(page.locator('.workspace')).to_have_class(re.compile('sources-collapsed.*studio-collapsed'))
                page.wait_for_timeout(300)
                assert page.locator('.chat-panel').bounding_box()['width'] > initial + 350
                page.screenshot(path=str(output / 'focus.png'))
                page.reload()
                page.wait_for_function('window.socket?.connected === true')
                expect(page.locator('.workspace')).to_have_class(re.compile('sources-collapsed.*studio-collapsed'))
                page.get_by_role('button', name='Toggle sources', exact=True).click()
                page.get_by_role('button', name='Toggle studio', exact=True).click()
                passed.extend(['sidebar collapse expands reading space', 'sidebar preference survives reload'])
                for width, height in [(1336, 768), (1366, 629), (1024, 768), (768, 1024), (390, 844), (320, 640)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    page.wait_for_timeout(300)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'horizontal overflow at {width}'
                    bounds = page.locator('.composer').bounding_box()
                    assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= height, f'composer clipped at {width}'
                    if not page.evaluate('document.documentElement.scrollHeight <= innerHeight + 2'):
                        page.screenshot(path=str(output / f'overflow-{width}.png'), full_page=True)
                        print(page.evaluate("Array.from(document.querySelectorAll('.nicegui-content > *')).map(el=>({cls:el.className, top:el.getBoundingClientRect().top, height:el.getBoundingClientRect().height, scroll:el.scrollHeight}))"))
                        raise AssertionError(f'page scroll at {width}')
                    if width <= 1000:
                        for panel in ['sources', 'studio', 'chat']:
                            page.get_by_role('button', name=f'Show {panel}', exact=True).click()
                            expect(page.locator('.source-panel' if panel == 'sources' else f'.{panel}-panel')).to_be_visible()
                        page.wait_for_timeout(400)
                        page.screenshot(path=str(output / f'mobile-{width}.png'), animations='disabled')
                    else:
                        page.screenshot(path=str(output / f'workspace-{width}.png'))
                passed.extend(['six viewport sizes without overflow', 'composer stays in view', 'mobile Sources Chat Studio navigation'])
                page.emulate_media(reduced_motion='reduce')
                assert page.locator('.chat-welcome').evaluate("el => getComputedStyle(el).animationName") == 'none'
                passed.append('reduced-motion preference')
                page.set_viewport_size({'width': 1336, 'height': 768})
                page.get_by_role('button', name='Indexing sample', exact=True).click()
                expect(page.get_by_text('Page 1', exact=True)).to_be_visible()
                expect(page.get_by_role('link', name='Open original file', exact=True)).to_be_visible()
                page.screenshot(path=str(output / 'source-preview.png'))
                page.get_by_role('button', name='Close dialog', exact=True).click()
                passed.append('source preview and original link')
                citation = {"number": 1, "id": row["id"] + "_0", "name": "Indexing sample.pdf", "locator": "Page 1"}
                db.save_artifact(book, "mindmap", "Interactive study map", json.dumps({"root": {
                    "name": "Study strategies", "citations": [], "children": [
                        {"name": "Retrieval practice", "citations": [1]},
                        {"name": "Spaced practice", "citations": [1]}]}}), [citation])
                page.reload()
                page.wait_for_function('window.socket?.connected === true')
                page.get_by_role('button', name='Interactive study map', exact=True).click(timeout=10000)
                expect(page.locator('.map-svg')).to_be_visible()
                page.get_by_role('button', name='Inspect topic Retrieval practice', exact=True).click()
                expect(page.locator('.map-evidence a')).to_contain_text('[1]')
                page.screenshot(path=str(output / 'mindmap.png'), animations='disabled')
                page.get_by_role('button', name='Close dialog', exact=True).click()
                passed.append('mind-map node click reveals citation without a numeric value')
                browser.close()
            assert not errors, errors
            result = {'passed': passed, 'javascript_errors': errors, 'indexing_progress': sorted(set(progress_values))}
            (output / 'result.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == '__main__':
    main()
