"""Verify theme, research entry and notebook deletion against an isolated library."""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'test-results' / 'research-ui'
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(NOTEBOOK_DATA_DIR=str(output / f'data-{time.time_ns()}'),
                      NOTEBOOK_PORT='8083', NOTEBOOK_NO_SAMPLE='1', NOTEBOOK_OFFLINE='1')
    from local_notebook import storage as db
    db.initialize()
    book = db.create_notebook('Physics research', 'Explore particle physics and new sources.')
    errors = []
    with (output / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'local_notebook.main'], cwd=root,
                                  stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                try:
                    if httpx.get('http://127.0.0.1:8083/health').is_success:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1366, 'height': 900})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('http://127.0.0.1:8083')
                page.wait_for_function('window.socket?.connected === true')
                page.get_by_role('button', name='Toggle light theme', exact=True).click()
                expect(page.locator('body')).to_have_class(re.compile(r'\bbody--light\b'))
                page.wait_for_timeout(400)
                page.screenshot(path=str(output / 'home-light.png'), full_page=True)
                page.get_by_role('button', name='Delete notebook', exact=True).click()
                expect(page.get_by_text('Delete “Physics research”?')).to_be_visible()
                assert page.url.endswith(':8083/')
                page.get_by_role('button', name='Cancel', exact=True).click()
                page.get_by_text('Physics research', exact=True).click()
                page.wait_for_url(f'**/notebook/{book}')
                page.wait_for_function('window.socket?.connected === true')
                expect(page.locator('body')).to_have_class(re.compile(r'\bbody--light\b'))
                page.wait_for_timeout(500)
                page.get_by_role('button', name='Toggle sources', exact=True).click()
                page.get_by_role('button', name='Toggle studio', exact=True).click()
                question = page.get_by_role('textbox', name='Ask about your sources')
                question.fill('Explain my uploaded chapter')
                expect(page.locator('.send-btn')).to_be_disabled()
                question.fill('Search online for particle physics sources')
                expect(page.locator('.send-btn')).to_be_enabled()
                page.wait_for_timeout(500)
                page.screenshot(path=str(output / 'workspace-light.png'), full_page=True)
                page.get_by_role('button', name='Settings', exact=True).click()
                page.get_by_role('combobox', name='Model provider').click()
                page.get_by_role('option', name='RunInfra', exact=True).click()
                expect(page.get_by_role('combobox', name='RunInfra model', exact=True)).to_be_visible()
                expect(page.get_by_text('Use the fast model for Studio', exact=True)).not_to_be_visible()
                expect(page.get_by_role('textbox', name='Compatible API base URL')).not_to_be_visible()
                page.screenshot(path=str(output / 'settings-runinfra.png'), full_page=True)
                page.get_by_role('button', name='Save settings', exact=True).click()
                assert db.settings()['provider'] == 'RunInfra'
                assert db.settings()['model'] == 'glm-5-3-flash'
                answer_model = page.get_by_role('combobox', name='Answer model', exact=True)
                expect(answer_model).to_have_value('GLM 5.3 Flash', timeout=5000)
                for label, model_id in [('Qwen 3.8 27B', 'Qwen/Qwen3.8-27B'),
                                        ('DeepSeek V4.1 Flash', 'deepseek-ai/DeepSeek-V4.1-Flash')]:
                    answer_model.click()
                    page.get_by_role('option', name=label, exact=True).click()
                    expect(answer_model).to_have_value(label)
                    assert db.settings()['model'] == db.settings()['fast_model'] == model_id
                page.get_by_role('button', name='Toggle light theme', exact=True).click()
                page.wait_for_timeout(350)
                page.screenshot(path=str(output / 'workspace-dark.png'), full_page=True)
                page.emulate_media(reduced_motion='reduce')
                assert page.locator('.studio-tile').first.evaluate("el => getComputedStyle(el).animationName") == 'none'
                page.get_by_role('button', name='Toggle light theme', exact=True).click()
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / 'mobile-light.png'), full_page=True)
                page.get_by_role('button', name='Toggle light theme', exact=True).click()
                expect(page.locator('body')).to_have_class(re.compile(r'\bbody--dark\b'))
                page.goto('http://127.0.0.1:8083')
                page.wait_for_function('window.socket?.connected === true')
                expect(page.locator('body')).to_have_class(re.compile(r'\bbody--dark\b'))
                page.get_by_role('button', name='Delete notebook', exact=True).click()
                page.get_by_role('dialog').get_by_role('button', name='Delete notebook', exact=True).click()
                expect(page.get_by_text('Physics research', exact=True)).to_have_count(0)
                assert not db.one('SELECT id FROM notebooks WHERE id=?', (book,))
                assert not errors, errors
                browser.close()
            print('Passed: light/dark persistence, deletion cancel/confirm, empty-notebook web request, responsive layout.')
        finally:
            subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'], capture_output=True)
            server.wait(timeout=15)


if __name__ == '__main__':
    main()
