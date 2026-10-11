"""Check website-error recovery in a browser, with an isolated offline library."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def check():
    root = Path(__file__).resolve().parents[1]
    output = root / 'test-results' / 'website-import'
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'NOTEBOOK_DATA_DIR': str(output / f'data-{time.time_ns()}'),
           'NOTEBOOK_MODEL_DIR': str(root / '.data' / 'models'),
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
           'NOTEBOOK_PORT': '8082', 'NOTEBOOK_OFFLINE': '1'}
    # Exercise the real HTTP-error adapter without external requests.
    boot = '''
import httpx
from local_notebook.ingestion import web
def blocked(url):
    response = httpx.Response(403, request=httpx.Request('GET', url))
    response.raise_for_status()
web._fetch = blocked
from local_notebook.main import main
main()
'''
    errors = []
    with (output / 'server.log').open('w', encoding='utf-8') as log:
        server = subprocess.Popen([sys.executable, '-c', boot], env=env, cwd=root,
                                  stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Test server exited; see test-results/website-import/server.log')
                try:
                    if httpx.get('http://127.0.0.1:8082/health', timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.25)
            else:
                raise RuntimeError('Test server did not become healthy')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('http://127.0.0.1:8082')
                page.wait_for_function('window.socket?.connected === true')
                page.get_by_role('button', name='Create notebook', exact=True).click()
                page.get_by_label('Notebook name').fill('Website import verification')
                page.get_by_role('button', name='Create notebook', exact=True).last.click()
                expect(page.locator('.composer')).to_be_visible()
                page.get_by_role('button', name='Toggle sources', exact=True).click()
                page.locator('.source-panel').get_by_role('button', name='Add sources', exact=True).click()
                page.get_by_role('tab', name='Website', exact=True).click()
                page.get_by_label('Public website URL').fill('https://en.wikipedia.org/wiki/Palau_fruit_dove')
                page.get_by_role('button', name='Add website', exact=True).click()
                dialog = page.get_by_role('dialog')
                expect(dialog).to_contain_text('This website blocked automatic access (HTTP 403)')
                expect(dialog).not_to_contain_text('model settings')
                expect(dialog.get_by_role('button', name='Add website', exact=True)).to_be_enabled()
                page.screenshot(path=str(output / 'blocked-website.png'), full_page=True)
                dialog.get_by_role('button', name='Paste article text', exact=True).click()
                expect(dialog.get_by_label('Your text', exact=True)).to_be_visible()
                dialog.get_by_label('Source title', exact=True).fill('Imported article text')
                dialog.get_by_label('Your text', exact=True).fill(
                    'This is an offline article fixture. It verifies that pasted website text becomes a '
                    'usable source after an automatic website import is blocked. Sources can be selected '
                    'in the notebook and used as evidence for questions about the original article.')
                dialog.get_by_role('button', name='Add text', exact=True).click()
                expect(page.locator('.source-item').get_by_text('Ready', exact=True)).to_be_visible(timeout=60000)
                expect(page.locator('.source-item')).to_contain_text('Imported article text')
                page.screenshot(path=str(output / 'pasted-source.png'), full_page=True)
                browser.close()
            assert not errors, errors
            result = {'passed': ['HTTP 403 website error', 'retry enabled', 'paste action switches tab',
                                 'pasted text indexes successfully'], 'javascript_errors': errors}
            (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == '__main__':
    check()
