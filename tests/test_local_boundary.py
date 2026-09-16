import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from local_notebook.main import LocalOnlyMiddleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(LocalOnlyMiddleware)

    @app.get("/")
    def home():
        return {"ok": True}

    @app.websocket("/ws")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("ok")
        await websocket.close()

    return TestClient(app)


def test_same_origin_local_request_allowed(client):
    assert client.get("/", headers={"Origin": "http://testserver"}).status_code == 200


def test_external_origin_cannot_read_local_api(client):
    assert client.get("/", headers={"Origin": "https://untrusted.example"}).status_code == 403


def test_host_rebinding_is_rejected(client):
    assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 403


def test_external_websocket_origin_is_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"Origin": "https://untrusted.example"}):
            pass


def test_local_websocket_is_allowed(client):
    with client.websocket_connect("/ws", headers={"Origin": "http://testserver"}) as websocket:
        assert websocket.receive_text() == "ok"
