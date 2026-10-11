"""Exercise deep maps and streamed Studio previews against a deterministic local provider."""
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
from playwright.sync_api import expect, sync_playwright


def fixture():
    branches = ["Supervised learning", "Unsupervised learning", "Feature engineering", "Model evaluation"]
    topics = [["Linear models", "Decision trees", "Neural networks"],
              ["Clustering", "Dimensionality reduction", "Density estimation"],
              ["Numerical features", "Categorical features", "Text representations"],
              ["Validation strategies", "Performance metrics", "Generalization"]]
    return {"title": "Machine learning, connected", "root": {
        "name": "Machine learning", "description": "Explore learning methods, useful representations, and reliable evaluation.",
        "children": [{"name": branch, "description": "Follow the subtopics to understand the methods and when they apply.",
                      "children": [{"name": topic, "description": "Connect the central idea to a practical example and its limitations.",
                                    "children": [{"name": f"{topic}: example", "description": "Use source-backed examples to test your understanding.", "citations": [1]},
                                                 {"name": f"{topic}: limitations", "description": "Check assumptions before applying the method to a new dataset.", "citations": [1]}]}
                                   for topic in topics[i]]}
                     for i, branch in enumerate(branches)]}}


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(payload)
        prompt = payload['messages'][-1]['content']
        if 'source-grounded quiz' in prompt:
            result = {"title": "Learning check", "questions": [{"question": "What does validation measure?",
                      "options": ["Generalization", "File size"], "answer": 0,
                      "explanation": "Validation estimates generalization.", "citations": [1]}]}
        else:
            result = fixture()
        content = json.dumps(result)
        kind = 'quiz' if 'questions' in result else 'mindmap'
        # Reproduce the actual failure once for each generator: an unfinished
        # JSON string followed by the provider's token-limit finish event.
        seen = getattr(self.server, 'attempts', {})
        self.server.attempts = seen
        seen[kind] = seen.get(kind, 0) + 1
        truncated = seen[kind] == 1
        if truncated:
            content = content[:len(content) // 2]
        # Send a useful first field, pause, then finish the structured document.
        split = content.index('description') if 'root' in result else content.index('options')
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        try:
            for i, part in enumerate([content[:split], content[split:]]):
                time.sleep(.2 if i == 0 else 1.8)
                if i == 0:
                    self.server.first_sent = time.perf_counter()
                event = {"choices": [{"delta": {"content": part}}]}
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                self.wfile.flush()
            self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'length' if truncated else 'stop'}]}) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def canvas_gestures(page, checks, output):
    viewport = page.locator('.map-viewport')
    root = page.locator('.map-node[data-node-id="0"]')
    world = page.locator('.map-world')

    def drag(x, y, dx, dy):
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + dx, y + dy, steps=12)
        page.mouse.up()

    def at(selector, x, y):
        page.wait_for_function('''({selector,x,y}) => {
            const r = document.querySelector(selector).getBoundingClientRect();
            return Math.abs(r.x-x)<3 && Math.abs(r.y-y)<3;
        }''', arg={'selector': selector, 'x': x, 'y': y})

    page.get_by_role('button', name='Collapse all', exact=True).click()
    expect(page.locator('.map-node')).to_have_count(1)
    box, before = viewport.bounding_box(), root.bounding_box()
    drag(box['x'] + 45, box['y'] + 45, 130, 90)
    at('.map-node[data-node-id="0"]', before['x'] + 130, before['y'] + 90)
    assert viewport.evaluate('el => el.scrollLeft === 0 && el.scrollTop === 0')
    checks.append('collapsed single-topic map pans freely without scrollbars')

    page.get_by_role('button', name='Fit map', exact=True).click()
    before = root.bounding_box()
    camera = world.evaluate('el => getComputedStyle(el).transform')
    drag(before['x'] + 60, before['y'] + 30, -150, -85)
    at('.map-node[data-node-id="0"]', before['x'] - 150, before['y'] - 85)
    assert world.evaluate('el => getComputedStyle(el).transform') == camera
    expect(page.locator('.map-detail')).to_have_count(0)
    checks.append('topic dragging moves the card independently without opening details')

    page.get_by_role('button', name='Reset layout', exact=True).click()
    page.get_by_role('button', name='Expand Machine learning', exact=True).click()
    page.get_by_role('button', name='Fit map', exact=True).click()
    branch = page.locator('.map-node[data-node-id="0.0"]')
    before = branch.bounding_box()
    root_before = root.bounding_box()
    path = page.locator('.map-world > path').first.get_attribute('d')
    drag(before['x'] + 60, before['y'] + 25, 95, -20)
    at('.map-node[data-node-id="0.0"]', before['x'] + 95, before['y'] - 20)
    at('.map-node[data-node-id="0"]', root_before['x'], root_before['y'])
    expect(page.locator('.map-world > path').first).not_to_have_attribute('d', path)
    checks.append('dragged topic connections follow their endpoint and other topics stay put')

    # The world point under the mouse stays fixed while the wheel zooms.
    before, box = root.bounding_box(), viewport.bounding_box()
    old_zoom = int(page.locator('.map-zoom').inner_text().rstrip('%')) / 100
    x, y = before['x'] + 60, before['y'] + 30
    page.mouse.move(x, y)
    page.mouse.wheel(0, -150)
    expect(page.locator('.map-zoom')).not_to_have_text(f'{old_zoom * 100:.0f}%')
    after = root.bounding_box()
    ratio = after['width'] / before['width']
    assert abs((x - after['x']) / ratio - (x - before['x'])) < 2
    assert abs((y - after['y']) / ratio - (y - before['y'])) < 2
    checks.append('wheel zoom stays anchored under the pointer')

    page.get_by_role('button', name='Fit map', exact=True).click()
    before = branch.bounding_box()
    page.get_by_role('button', name='Inspect topic Supervised learning', exact=True).focus()
    page.keyboard.press('Shift+ArrowRight')
    at('.map-node[data-node-id="0.0"]', before['x'] + 32, before['y'])
    viewport.focus()
    before = root.bounding_box()
    page.keyboard.press('ArrowLeft')
    at('.map-node[data-node-id="0"]', before['x'] - 32, before['y'])
    checks.append('keyboard panning and individual topic nudging')

    # Resizing preserves the user's view rather than snapping it back to a corner.
    before, box = root.bounding_box(), viewport.bounding_box()
    offset = before['x'] - (box['x'] + box['width'] / 2)
    page.set_viewport_size({'width': 1124, 'height': 623})
    page.wait_for_function('''offset => {
        const r=document.querySelector('.map-node[data-node-id="0"]').getBoundingClientRect();
        const v=document.querySelector('.map-viewport').getBoundingClientRect();
        return Math.abs(r.x-(v.x+v.width/2)-offset)<3;
    }''', arg=offset)
    checks.append('viewport resizing preserves the panned view')

    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('button', name='Collapse all', exact=True).click()
    page.get_by_role('button', name='Reset layout', exact=True).click()
    touch = page.context.new_cdp_session(page)
    touch.send('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 2})
    box, before = viewport.bounding_box(), root.bounding_box()
    x, y = box['x'] + 45, box['y'] + 70
    touch.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y, 'id': 1}]})
    touch.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': x + 65, 'y': y + 55, 'id': 1}]})
    touch.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    at('.map-node[data-node-id="0"]', before['x'] + 65, before['y'] + 55)
    page.get_by_role('button', name='Fit map', exact=True).click()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    before = root.bounding_box()
    touch.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [
        {'x': x - 45, 'y': y, 'id': 1}, {'x': x + 45, 'y': y, 'id': 2}]})
    touch.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [
        {'x': x - 75, 'y': y, 'id': 1}, {'x': x + 75, 'y': y, 'id': 2}]})
    touch.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    expect(page.locator('.map-zoom')).to_have_text('167%')
    after = root.bounding_box()
    assert abs((x - after['x']) / (after['width'] / before['width']) - (x - before['x'])) < 3
    expect(page.locator('.map-detail')).to_have_count(0)
    assert viewport.evaluate('el => getComputedStyle(el).touchAction') == 'none'
    checks.append('mobile single-finger pan and two-finger pinch zoom')
    page.screenshot(path=str(output / 'mobile-free-canvas.png'))
    touch.send('Emulation.setTouchEmulationEnabled', {'enabled': False})
    touch.detach()
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.get_by_role('button', name='Reset layout', exact=True).click()
    page.get_by_role('button', name='Expand Machine learning', exact=True).click()
    expect(page.locator('.map-node')).to_have_count(5)
    page.get_by_role('button', name='Fit map', exact=True).click()
    page.screenshot(path=str(output / 'free-canvas.png'))


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'test-results' / 'mindmap'
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(NOTEBOOK_DATA_DIR=str(output / f'data-{time.time_ns()}'), NOTEBOOK_NO_SAMPLE='1',
                      NOTEBOOK_OFFLINE='0', NOTEBOOK_PORT='8084',
                      GEMINI_API_KEY='', NOTEBOOK_API_KEY='')
    from local_notebook import storage as db
    from local_notebook.ingestion import jobs
    db.initialize()
    provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    provider.requests, provider.first_sent = [], None
    Thread(target=provider.serve_forever, daemon=True).start()
    db.save_settings({'provider': 'Local / compatible', 'endpoint': f'http://127.0.0.1:{provider.server_port}/v1',
                      'model': 'local-fixture', 'fast_model': 'local-fixture', 'semantic': False})
    book = db.create_notebook('Machine learning')
    sid = jobs.add_file(book, 'Learning notes.txt', b'Machine learning includes supervised and unsupervised learning. Validation measures generalization. Feature engineering transforms data into useful representations.')
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (sid,)))
    source = db.one('SELECT * FROM chunks WHERE source_id=?', (sid,))
    citation = {'number': 1, 'id': source['id'], 'name': 'Learning notes.txt', 'locator': source['locator']}
    db.save_artifact(book, 'mindmap', fixture()['title'], json.dumps(fixture()), [citation])
    checks, errors, timings = [], [], []
    with (output / 'server.log').open('w', encoding='utf-8') as log:
        server = subprocess.Popen([sys.executable, '-m', 'local_notebook.main'], cwd=root, stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for _ in range(100):
                try:
                    if httpx.get('http://127.0.0.1:8084/health').is_success:
                        break
                except httpx.ConnectError:
                    time.sleep(.2)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:8084/notebook/{book}')
                page.wait_for_function('window.socket?.connected === true')
                page.wait_for_timeout(500)  # Let the persisted sidebar layout settle.
                page.get_by_role('button', name='Toggle studio', exact=True).click()
                page.get_by_role('button', name=fixture()['title'], exact=True).click()
                expect(page.locator('.map-node')).to_have_count(5)
                expect(page.locator('.map-detail')).to_have_count(0)
                page.get_by_role('button', name='Expand Supervised learning', exact=True).click()
                expect(page.locator('.map-node')).to_have_count(8)
                page.get_by_role('button', name='Expand Linear models', exact=True).click()
                expect(page.locator('.map-node')).to_have_count(10)
                page.get_by_role('button', name='Inspect topic Linear models: example', exact=True).click()
                expect(page.locator('.map-detail')).to_contain_text('Use source-backed examples')
                expect(page.locator('.map-evidence a')).to_have_attribute('href', '/evidence/' + source['id'])
                page.screenshot(path=str(output / 'branches.png'), animations='disabled')
                canvas_height = page.locator('.map-viewport').bounding_box()['height']
                page.get_by_role('button', name='Close topic details', exact=True).click()
                expect(page.locator('.map-detail')).to_have_count(0)
                assert page.locator('.map-viewport').bounding_box()['height'] == canvas_height
                page.get_by_role('button', name='Collapse Supervised learning', exact=True).click()
                expect(page.locator('.map-node')).to_have_count(5)
                page.get_by_role('button', name='Expand all', exact=True).click()
                expect(page.locator('.map-node')).to_have_count(41)
                assert page.locator('.map-node').evaluate_all('els => new Set(els.map(el=>getComputedStyle(el).borderLeftColor)).size') >= 5
                boxes = page.locator('.map-node').evaluate_all('els=>els.map(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})')
                for i, a in enumerate(boxes):
                    for b in boxes[i + 1:]:
                        assert a['x'] + a['w'] <= b['x'] or b['x'] + b['w'] <= a['x'] or a['y'] + a['h'] <= b['y'] or b['y'] + b['h'] <= a['y']
                checks.extend(['independent nested expand and collapse', 'expand all shows all 41 nodes', 'branch colours and no overlapping cards', 'selected topic shows full explanation and evidence'])
                page.get_by_role('button', name='Collapse all', exact=True).click()
                expect(page.locator('.map-node')).to_have_count(1)
                page.get_by_role('button', name='Expand Machine learning', exact=True).focus()
                page.keyboard.press('Enter')
                expect(page.locator('.map-node')).to_have_count(5)
                page.get_by_role('button', name='Zoom in', exact=True).click()
                expect(page.locator('.map-zoom')).to_have_text('115%')
                page.get_by_role('button', name='Fit map', exact=True).click()
                canvas_gestures(page, checks, output)
                for width, height in [(1440, 900), (1124, 623), (390, 844)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    page.get_by_role('button', name='Fit map', exact=True).click()
                    box = page.locator('.map-viewport').bounding_box()
                    assert box['height'] >= height * .8 and box['y'] + box['height'] < height
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'map-{width}.png'))
                checks.extend(['collapse all and keyboard re-expansion', 'zoom and fit map', 'canvas occupies at least 80% of desktop laptop and mobile screens', 'topic details close without resizing canvas'])
                page.get_by_role('button', name='Export mind map', exact=True).click()
                expect(page.get_by_role('menuitem', name='Export PDF', exact=True)).to_be_visible()
                expect(page.get_by_role('menuitem', name='Markdown', exact=True)).to_be_visible()
                expect(page.get_by_role('menuitem', name='JSON', exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                page.get_by_role('button', name='Close dialog', exact=True).click()
                page.set_viewport_size({'width': 1440, 'height': 900})
                for tile in ['Quiz', 'Mind map']:
                    page.locator('.studio-tile').filter(has_text=tile).click()
                    page.get_by_label('Focus on a topic (optional)', exact=True).fill('Validation')
                    page.get_by_role('button', name='Generate', exact=True).click()
                    expect(page.locator('.studio-preview')).to_be_visible()
                    lag = time.perf_counter() - provider.first_sent
                    assert lag < 1.5, lag
                    assert not page.get_by_role('button', name='Export PDF', exact=True).is_visible()
                    page.screenshot(path=str(output / f'{tile.lower().replace(" ", "-")}-stream.png'))
                    ready_button = 'Export mind map' if tile == 'Mind map' else 'Export PDF'
                    expect(page.get_by_role('button', name=ready_button, exact=True)).to_be_visible(timeout=10000)
                    assert 'Focus topic: Validation' in provider.requests[-1]['messages'][-1]['content']
                    timings.append({'kind': tile, 'first_chunk_to_preview_ms': round(lag * 1000)})
                    page.get_by_role('button', name='Close dialog', exact=True).click()
                checks.extend(['quiz preview before completion', 'map preview before completion', 'focus topic reaches model prompt'])
                assert provider.attempts == {'quiz': 2, 'mindmap': 2}, provider.attempts
                checks.append('incomplete quiz and mind map recover, save and open automatically')
                if '--live-results' in sys.argv:
                    for kind in ('mindmap', 'quiz'):
                        result = json.loads((root / 'test-results' / 'studio-live' / f'{kind}.json').read_text(encoding='utf-8'))
                        citations = result.pop('citations')
                        title = 'Live DeepSeek ' + kind
                        db.save_artifact(book, kind, title, json.dumps(result), citations)
                        page.get_by_role('button', name=title, exact=True).click(timeout=10000)
                        if kind == 'mindmap':
                            expect(page.get_by_role('button', name='Export mind map', exact=True)).to_be_visible()
                            page.get_by_role('button', name='Expand all', exact=True).click()
                            assert page.locator('.map-node').count() > 5
                        else:
                            expect(page.locator('.quiz-question')).to_have_count(len(result['questions']))
                        page.screenshot(path=str(output / f'live-{kind}.png'))
                        page.get_by_role('button', name='Close dialog', exact=True).click()
                    checks.append('real DeepSeek outputs saved and opened as interactive map and quiz')
                assert not errors, errors
                browser.close()
            result = {'passed': checks, 'timings': timings, 'javascript_errors': errors}
            (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=15)
            provider.shutdown()
            provider.server_close()


if __name__ == '__main__':
    main()
