"""Browser regression: tool loop, streaming, external citations, cancellation, no indexing."""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def fixture_server():
    from local_notebook import providers, research
    from local_notebook.main import main

    async def decide(state):
        await asyncio.sleep(.15)
        if not state['searches']:
            return {'action': 'search', 'query': state['question']}
        if not state['read_pages']:
            return {'action': 'read', 'ids': [1]}
        return {'action': 'answer', 'coverage': ''}

    async def search(query, progress):
        progress('Searching DuckDuckGo: ' + query)
        await asyncio.sleep(6 if 'cancel' in query else .3)
        return [{'url': 'https://physics.example/resonance', 'title': 'Resonance physics'}], []

    async def read(url):
        await asyncio.sleep(.2)
        return {'url': url, 'title': 'Resonance physics', 'text':
                'The resonance width is inversely related to particle lifetime. ' * 12, 'links': []}

    async def stream(system, prompt, **kwargs):
        assert 'resonance width' in prompt
        if 'compare with our text' in prompt:
            assert 'NOTEBOOK DOCUMENT' in prompt and 'WEBSITE' in prompt
            yield '| Aspect | Our document | Web findings |\n|---|---|---|\n'
            yield '| Methodology | Our text relates resonance width to lifetime [1]. | The website agrees with this relation [2]. |\n'
            yield '| Ethical Stance | Document context [1]. | Web context [2]. |\n'
            return
        yield 'Short-lived particles produce broad resonances [1]. '
        await asyncio.sleep(.4)
        yield 'The width is inversely related to lifetime [1].'

    research.decide, research.search_web, research.read_page = decide, search, read
    providers.stream = stream
    providers.configured = lambda: True
    main()


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'test-results' / 'web-agent'
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(NOTEBOOK_DATA_DIR=str(output / f'data-{time.time_ns()}'), NOTEBOOK_PORT='8084',
                      NOTEBOOK_NO_SAMPLE='1', NOTEBOOK_OFFLINE='1')
    from local_notebook import storage as db
    db.initialize()
    db.save_settings({'theme': 'light', 'semantic': False, 'rerank': False})
    book = db.create_notebook('Web research test')
    errors = []
    with (output / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, __file__, '--fixture-server'], cwd=root,
                                  stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                try:
                    if httpx.get('http://127.0.0.1:8084/health').is_success:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1366, 'height': 900})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:8084/notebook/{book}')
                page.wait_for_function('window.socket?.connected === true')
                page.locator('.research-mode').click()
                page.get_by_role('option', name='Agent', exact=True).click()
                question = page.get_by_role('textbox', name='Ask about your sources')
                question.fill('Explain particle resonance widths')
                expect(page.locator('.send-btn')).to_be_enabled()
                page.locator('.send-btn').click()
                expect(page.get_by_text('Agent activity', exact=True)).to_be_visible()
                expect(page.locator('.research-activity')).to_contain_text('Searching DuckDuckGo')
                page.screenshot(path=str(output / 'agent-working.png'), animations='disabled')
                expect(page.get_by_role('button', name='Stop generation', exact=True)).not_to_be_visible(timeout=20000)
                expect(page.locator('.assistant-message')).to_contain_text('inversely related to lifetime')
                expect(page.locator('.citation-chip')).to_have_attribute('href', 'https://physics.example/resonance')
                assert len(db.messages(book)) == 2
                references = json.loads(db.messages(book)[-1]['citations'])
                assert references[0]['kind'] == 'web' and 'text' not in references[0]
                assert not db.sources(book) and not db.rows('SELECT * FROM chunks')
                page.reload()
                page.wait_for_function('window.socket?.connected === true')
                expect(page.locator('.citation-chip')).to_have_attribute('href', 'https://physics.example/resonance')
                expect(page.locator('.research-mode')).to_contain_text('Agent')
                page.get_by_role('button', name='Retry answer', exact=True).click()
                expect(page.get_by_text('Agent activity', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Stop generation', exact=True)).not_to_be_visible(timeout=20000)
                assert len(db.messages(book)) == 2
                page.set_viewport_size({'width': 390, 'height': 844})
                question.fill('Search online cancel test')
                page.locator('.send-btn').click()
                expect(page.locator('.research-activity')).to_contain_text('Searching DuckDuckGo')
                page.get_by_role('button', name='Stop generation', exact=True).click()
                expect(page.locator('.retrieval-status')).to_contain_text('Generation stopped')
                expect(page.locator('.research-mode')).to_be_enabled()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / 'agent-mobile.png'), animations='disabled')
                assert not db.sources(book) and not db.rows('SELECT * FROM chunks')
                assert not errors, errors
                from local_notebook.ingestion import jobs
                sid = jobs.add_file(book, 'Course notes.txt', b'The resonance width is inversely related to the lifetime of a particle. Narrow resonances have longer lifetimes.')
                jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (sid,)))
                source_count = len(db.sources(book))
                question.fill('Search online about resonance width and compare with our text')
                page.locator('.send-btn').click()
                expect(page.locator('.research-activity')).to_contain_text('Searching notebook documents')
                expect(page.get_by_role('button', name='Stop generation', exact=True)).not_to_be_visible(timeout=20000)
                table = page.locator('.assistant-message table').last
                expect(table).to_be_visible()
                latest = json.loads(db.messages(book)[-1]['citations'])
                assert {item.get('kind') for item in latest} == {'document', 'web'}
                assert len(db.sources(book)) == source_count
                assert page.locator('.citation-chip[href^="/evidence/"]').count() == 1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert table.evaluate('(el) => el.scrollWidth > el.clientWidth')
                cell = table.get_by_role('cell', name='Methodology', exact=True)
                assert cell.evaluate('(el) => getComputedStyle(el).overflowWrap') == 'normal'
                assert cell.bounding_box()['width'] >= 150
                page.screenshot(path=str(output / 'comparison-mobile.png'), animations='disabled')
                page.set_viewport_size({'width': 1366, 'height': 900})
                page.wait_for_timeout(350)
                assert cell.bounding_box()['width'] >= 150
                page.screenshot(path=str(output / 'comparison-desktop.png'), animations='disabled')
                browser.close()
            print('Passed: agent mode, document/web retrieval, mixed citations, Stop, no web indexing, readable desktop/mobile comparison tables.')
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == '__main__':
    fixture_server() if '--fixture-server' in sys.argv else main()
