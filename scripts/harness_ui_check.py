"""Verify source-first guide routing and compact streaming progress offline."""
import os
from pathlib import Path
import subprocess
import sys
import time


def serve():
    import asyncio
    from local_notebook import providers, research
    from local_notebook.main import main
    async def stream(system, prompt, **kwargs):
        assert 'FastAPI' in prompt
        for part in ['## FastAPI learning guide\n\n', 'Start with routing and validation. [1]\n\n',
                     'Then practise dependency injection and testing. [1]']:
            await asyncio.sleep(.25)
            yield part
    async def forbidden(*args, **kwargs):
        raise AssertionError('A source guide must not invoke web research or a planner')
    providers.stream = stream
    providers.complete = forbidden
    providers.configured = lambda: True
    research.research = forbidden
    main()


def check():
    import httpx
    from playwright.sync_api import expect, sync_playwright
    root = Path(__file__).resolve().parents[1]
    output = root / 'test-results' / 'harness-ui'
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(NOTEBOOK_DATA_DIR=str(output / f'data-{time.time_ns()}'), NOTEBOOK_PORT='8089',
                      NOTEBOOK_NO_SAMPLE='1', NOTEBOOK_OFFLINE='1')
    from local_notebook import storage as db
    from local_notebook.ingestion import jobs
    db.initialize()
    db.save_settings({'semantic': False, 'research_mode': 'web'})
    book = db.create_notebook('FastAPI')
    sid = jobs.add_file(book, 'Mastering FastAPI.txt', b'FastAPI teaches routing, validation, dependency injection, and testing. ' * 20)
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (sid,)))
    errors = []
    with (output / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, __file__, '--serve'], cwd=root, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                try:
                    if httpx.get('http://127.0.0.1:8089/health').is_success:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(.2)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1366, 'height': 900})
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.goto(f'http://127.0.0.1:8089/notebook/{book}')
                page.wait_for_function('window.socket?.connected === true')
                page.get_by_role('textbox', name='Ask about your sources').fill('can u create a proper learning guide here')
                page.get_by_role('button', name='Send question', exact=True).click()
                expect(page.locator('.run-progress')).to_have_count(1)
                expect(page.get_by_role('heading', name='FastAPI learning guide')).to_be_visible(timeout=10000)
                expect(page.get_by_text('Then practise dependency injection and testing.', exact=False)).to_be_visible()
                expect(page.locator('.live-answer')).to_be_empty(timeout=10000)
                expect(page.locator('.run-progress .q-expansion-item__content')).not_to_be_visible()
                assert 'couldn’t find evidence' not in page.locator('.conversation').inner_text()
                assert not page.locator('.research-activity').count()
                expect(page.locator('.citation-chips')).not_to_be_visible()
                page.locator('.citation-toggle .q-item').click()
                expect(page.locator('.citation-chip').first).to_be_visible()
                page.locator('.citation-toggle .q-item').click()
                expect(page.locator('.citation-chips')).not_to_be_visible()
                page.screenshot(path=str(output / 'completed-dark.png'), full_page=True)
                page.locator('.run-progress .q-item').click()
                expect(page.get_by_text('Reading your selected sources', exact=True)).to_be_visible()
                page.get_by_role('button', name='Toggle light theme', exact=True).click()
                page.wait_for_function("document.body.classList.contains('body--light')")
                page.wait_for_timeout(300)
                page.screenshot(path=str(output / 'progress-light.png'), full_page=True)
                page.reload()
                expect(page.get_by_role('heading', name='FastAPI learning guide')).to_be_visible()
                expect(page.locator('.run-progress .q-expansion-item__content')).not_to_be_visible()
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors, errors
                browser.close()
            print('Passed: source guide in Agent mode, zero web/planner calls, streaming, collapsed progress, reload, mobile.')
        finally:
            subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'], capture_output=True)
            server.wait(timeout=15)


if __name__ == '__main__':
    serve() if '--serve' in sys.argv else check()
