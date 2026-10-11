"""Delete an actively indexing fixture through the UI; never touch the user's library."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'test-results' / f'responsiveness-{time.time_ns()}'
os.environ.update(NOTEBOOK_DATA_DIR=str(RUN), NOTEBOOK_MODEL_DIR=str(ROOT / '.data' / 'models'),
                  NOTEBOOK_PORT='8081', NOTEBOOK_NO_SAMPLE='1', NOTEBOOK_OFFLINE='1')

from local_notebook import storage as db  # noqa: E402
from local_notebook.config import DATA  # noqa: E402
from local_notebook.ingestion import jobs  # noqa: E402


def main():
    assert DATA == RUN.resolve(), 'Refusing to test against a different library'
    db.initialize()
    db.save_settings({'semantic': True})
    book = db.create_notebook('Active import deletion fixture')
    content = '\n\n'.join(f'Lesson {n}. ' + (
        'Database transactions preserve consistency. Commit publishes a change and rollback discards it. '
        'Indexes locate records efficiently. Queries filter and join related tables. ' * 12)
        for n in range(150))
    source = jobs.add_file(book, 'large-fixture.txt', content.encode())
    original = Path(db.one('SELECT path FROM sources WHERE id=?', (source,))['path'])
    errors = []
    with (RUN / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'local_notebook.main'], cwd=ROOT,
                                  stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            with httpx.Client(base_url='http://127.0.0.1:8081', timeout=3) as client:
                for _ in range(100):
                    try:
                        if client.get('/health').is_success:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.2)
                else:
                    raise AssertionError('Fixture server did not start')
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel='msedge', headless=True)
                    page = browser.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:8081/notebook/{book}')
                    expect(page.locator('.composer')).to_be_visible()
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        state = db.one('SELECT status FROM sources WHERE id=?', (source,))['status']
                        if state == 'indexing':
                            break
                        assert state not in {'error', 'ready'}, state
                        time.sleep(.1)
                    assert state == 'indexing'
                    latencies = []
                    for _ in range(5):
                        start = time.perf_counter()
                        assert client.get('/health').is_success
                        latencies.append(round(1000 * (time.perf_counter() - start), 1))
                    page.get_by_role('button', name='Notebook options', exact=True).click()
                    page.get_by_role('menuitem', name='Delete notebook', exact=True).click()
                    start = time.perf_counter()
                    page.get_by_role('button', name='Delete notebook', exact=True).click()
                    page.wait_for_url('http://127.0.0.1:8081/', timeout=5000)
                    deletion_ms = round(1000 * (time.perf_counter() - start), 1)
                    assert not db.sources(book)
                    assert not db.one('SELECT id FROM notebooks WHERE id=?', (book,))
                    deadline = time.monotonic() + 30
                    while db.rows('SELECT * FROM source_cleanup') and time.monotonic() < deadline:
                        time.sleep(.1)
                    assert not original.exists()
                    assert not db.rows('SELECT * FROM source_cleanup')
                    assert not errors, errors
                    browser.close()
                result = {'deleted_while_indexing': True, 'delete_and_navigate_ms': deletion_ms,
                          'health_during_indexing_ms': latencies, 'cleanup_complete': True,
                          'javascript_errors': errors}
                (RUN / 'result.json').write_text(json.dumps(result, indent=2))
                print(json.dumps(result, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == '__main__':
    main()
