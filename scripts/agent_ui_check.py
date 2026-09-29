"""Offline end-to-end agent UI smoke test using deterministic model/search fixtures."""
import os
import subprocess
import sys
import time
from pathlib import Path


def serve():
    import asyncio
    import json
    from local_notebook import providers, research
    from local_notebook.main import main
    from local_notebook.retrieval.search import Evidence

    async def complete(system, prompt, **kwargs):
        if 'You plan tool use' in system:
            await asyncio.sleep(2)
            return json.dumps({'tools': ['analytics', 'spreadsheet'], 'queries': ['Avatar cast', 'Avatar revenue']})
        if 'declarative data recipe' in system:
            return json.dumps({'title': 'Sales by region', 'table': 0, 'group_by': 'Region', 'value': 'Sales',
                               'operation': 'sum', 'chart': 'bar'})
        await asyncio.sleep(2)
        return '# Research report\n\nThe fixture provides sales and production evidence. [1]'

    async def stream(*args, **kwargs):
        yield 'The sales data shows East at 40 and West at 20. The chart and spreadsheet are below. [1]'

    async def search(*args, **kwargs):
        return Evidence([{'id': 'fixture-web', 'kind': 'web', 'name': 'Fixture source', 'locator': 'https://example.org',
                          'url': 'https://example.org', 'text': 'Sales: East 40, West 20. Avatar production details.'}], 'Agent', 1)

    providers.complete = complete
    providers.stream = stream
    providers.configured = lambda: True
    research.research = search
    main()


def check():
    import httpx
    from playwright.sync_api import expect, sync_playwright
    root = Path(__file__).resolve().parents[1]
    output = root / 'test-results' / 'agent-ui'
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(NOTEBOOK_DATA_DIR=str(output / f'data-{time.time_ns()}'), NOTEBOOK_PORT='8087',
                      NOTEBOOK_NO_SAMPLE='1', NOTEBOOK_OFFLINE='1')
    from local_notebook import storage as db
    from local_notebook.ingestion import jobs
    db.initialize()
    db.save_settings({'semantic': False, 'rerank': False})
    book = db.create_notebook('Agent Studio checks')
    source = jobs.add_file(book, 'sales.csv', b'Region,Sales\nEast,10\nWest,20\nEast,30\n')
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    with (output / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, __file__, '--serve'], cwd=root,
                                  stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                try:
                    if httpx.get('http://127.0.0.1:8087/health').is_success:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(.2)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:8087/notebook/{book}')
                page.wait_for_function('window.socket?.connected === true')
                page.wait_for_timeout(500)
                page.get_by_role('button', name='Toggle studio', exact=True).click()
                for name in ('Data Analytics', 'Spreadsheet', 'Deep Research'):
                    expect(page.get_by_role('button', name=name, exact=True)).to_be_visible()
                for name in ('Mind map', 'Quiz', 'Reports', 'Notes', 'Data Analytics', 'Spreadsheet', 'Deep Research'):
                    page.get_by_role('button', name=name, exact=True).click()
                    page.get_by_role('button', name='Minimize tool', exact=True).click()
                    expect(page.get_by_role('dialog')).not_to_be_visible()
                    page.get_by_role('button', name=f'Restore {name}', exact=True).click()
                    expect(page.get_by_role('dialog')).to_be_visible()
                    page.get_by_role('dialog').get_by_role('button', name='Close dialog' if name == 'Notes' else 'Cancel', exact=True).click()
                page.get_by_role('textbox', name='Ask about your sources').fill(
                    'Quick search Avatar cast and production details, chart sales and create a spreadsheet')
                page.get_by_role('button', name='Send question', exact=True).click()
                expect(page.locator('.assistant-message .nicegui-echart')).to_have_count(1, timeout=30000)
                expect(page.get_by_text('You can reopen these results', exact=False)).to_be_visible()
                with page.expect_download() as downloaded:
                    page.get_by_role('button', name='Download Excel', exact=True).first.click()
                downloaded.value.save_as(output / 'sales.xlsx')
                page.reload()
                page.wait_for_function('window.socket?.connected === true')
                expect(page.locator('.assistant-message .nicegui-echart')).to_have_count(1)
                expect(page.locator('.nicegui-echart svg path[fill="#6c9fe8"]')).to_have_count(2)
                page.wait_for_timeout(300)
                page.locator('.nicegui-echart').scroll_into_view_if_needed()
                page.screenshot(path=str(output / 'desktop.png'), full_page=True)
                page.get_by_role('button', name='Deep Research', exact=True).click()
                page.get_by_role('textbox', name='What should the agent do?').fill('Deep research Avatar production')
                page.get_by_role('button', name='Run agent', exact=True).click()
                page.get_by_role('button', name='Minimize tool', exact=True).click()
                expect(page.get_by_role('dialog')).not_to_be_visible()
                # Start another Studio job while research continues in the background.
                page.get_by_role('button', name='Reports', exact=True).click()
                page.get_by_role('button', name='Generate', exact=True).click()
                page.get_by_role('button', name='Minimize tool', exact=True).click()
                expect(page.get_by_text('Complete · click to open', exact=True)).to_have_count(2, timeout=30000)
                expect(page.get_by_role('dialog')).not_to_be_visible()
                page.get_by_role('button', name='Restore Deep Research', exact=True).click()
                expect(page.get_by_role('button', name='Close dialog', exact=True)).to_be_visible()
                page.get_by_role('button', name='Close dialog', exact=True).click()
                assert db.one("SELECT id FROM artifacts WHERE kind='deep_research'")
                assert db.one("SELECT id FROM artifacts WHERE kind='report'")
                page.get_by_role('button', name='Restore Reports', exact=True).click()
                page.get_by_role('button', name='Close dialog', exact=True).click()
                # Cancelling a minimized run must not save an artifact.
                before = len(db.rows('SELECT id FROM artifacts'))
                page.get_by_role('button', name='Spreadsheet', exact=True).click()
                page.get_by_role('textbox', name='What should the agent do?').fill('Create a spreadsheet')
                page.get_by_role('button', name='Run agent', exact=True).click()
                page.get_by_role('button', name='Minimize tool', exact=True).click()
                page.get_by_role('button', name='Cancel minimized tool', exact=True).click()
                page.wait_for_timeout(2500)
                assert len(db.rows('SELECT id FROM artifacts')) == before
                page.set_viewport_size({'width': 390, 'height': 844})
                page.get_by_role('button', name='Show chat', exact=True).click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / 'mobile.png'), full_page=True)
                assert not errors, errors
                browser.close()
            print('Passed: agent chat, inline chart, spreadsheet download, reload persistence, Studio deep report, mobile layout.')
        finally:
            subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'], capture_output=True)
            server.wait(timeout=15)


if __name__ == '__main__':
    serve() if '--serve' in sys.argv else check()
