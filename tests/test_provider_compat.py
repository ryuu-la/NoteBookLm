import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from local_notebook import providers, storage as db


def test_openai_compatible_stream_parses_sse(library):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for token in ["Grounded ", "answer [1]."]:
                value = {"choices": [{"delta": {"content": token}}]}
                self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        db.save_settings({"provider": "Local / compatible", "model": "test-model",
                          "endpoint": f"http://127.0.0.1:{server.server_port}/v1"})
        result = asyncio.run(providers.complete("Use evidence", "A question"))
        assert result == "Grounded answer [1]."
        assert seen["model"] == "test-model" and seen["stream"] is True
    finally:
        server.shutdown()
        server.server_close()
