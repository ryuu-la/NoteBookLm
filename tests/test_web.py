import ipaddress
import socket

import httpx
import pytest

from local_notebook.ingestion import web
from local_notebook.ui.common import error_text


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Keep every website test offline, including URL safety validation."""
    def addresses(host, port, *args, **kwargs):
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            address = "127.0.0.1" if host == "localhost" else "93.184.216.34"
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

    monkeypatch.setattr(web.socket, "getaddrinfo", addresses)


@pytest.fixture
def mock_http(monkeypatch):
    client_class = httpx.Client

    def install(handler):
        requests = []

        def respond(request):
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(web.httpx, "Client", lambda *args, **kwargs: client_class(
            *args, transport=httpx.MockTransport(respond), **kwargs))
        return requests

    return install


@pytest.mark.parametrize("url", [
    "file:///C:/secret", "http://127.0.0.1", "http://localhost",
    "http://169.254.169.254", "http://[::1]/", "http://192.168.1.10/",
])
def test_private_urls_rejected(url):
    with pytest.raises(ValueError):
        web.public_url(url)


@pytest.mark.parametrize("article_tag", ["main", "article", "body"])
def test_fetch_extracts_readable_article(mock_http, article_tag):
    article = "Palau fruit doves eat fruit and live in forests on the islands of Palau. " * 3
    unwanted = "".join(f"<{tag}>unwanted-{tag}</{tag}>" for tag in (
        "script", "style", "nav", "footer", "header", "form", "noscript", "svg"))
    body = f"{unwanted}<p>{article}</p>"
    if article_tag != "body":
        body = f"<aside>outside-the-article</aside><{article_tag}>{body}</{article_tag}>"
    html = f"<html><head><title>Palau fruit dove</title></head><body>{body}</body></html>"
    mock_http(lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html"}))

    name, data, final_url = web.fetch("https://example.org/bird")

    assert name == "Palau fruit dove.txt"
    assert final_url == "https://example.org/bird"
    assert article.strip() in data.decode()
    assert "unwanted-" not in data.decode()
    assert "outside-the-article" not in data.decode()


def test_fetch_preserves_pdf_bytes(mock_http):
    pdf = b"%PDF-1.7\nfixture document bytes\n%%EOF"
    mock_http(lambda request: httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"}))

    assert web.fetch("https://example.org/document.pdf") == (
        "Web document.pdf", pdf, "https://example.org/document.pdf")


def test_fetch_follows_public_redirect_and_keeps_final_url(mock_http):
    def respond(request):
        if request.url.path == "/original":
            return httpx.Response(302, headers={"location": "/article"})
        return httpx.Response(200, text="<title>Bird</title><main>" + "Readable bird article. " * 10 + "</main>")

    requests = mock_http(respond)
    name, data, final_url = web.fetch("https://example.org/original")

    assert name == "Bird.txt"
    assert b"Readable bird article" in data
    assert final_url == "https://example.org/article"
    assert [request.url.path for request in requests] == ["/original", "/article"]


@pytest.mark.parametrize("target", ["http://127.0.0.1/private", "http://169.254.169.254/latest/meta-data/"])
def test_fetch_rejects_private_redirect_before_request(mock_http, target):
    requests = mock_http(lambda request: httpx.Response(302, headers={"location": target}))

    with pytest.raises(ValueError, match="public"):
        web.fetch("https://example.org/article")

    assert len(requests) == 1


@pytest.mark.parametrize("status,reason", [
    (401, "automatic"), (403, "automatic"), (404, "not found"), (429, "wait"),
    (500, "unavailable"), (502, "unavailable"), (503, "unavailable"), (504, "unavailable"),
])
def test_fetch_http_errors_explain_website_failure(mock_http, status, reason):
    mock_http(lambda request: httpx.Response(status, text="private response details"))

    with pytest.raises(web.WebImportError) as raised:
        web.fetch("https://example.org/article?token=sensitive-token")

    message = error_text(raised.value).lower()
    assert reason in message
    assert "sensitive-token" not in message
    assert "private response details" not in message
    assert "model" not in message and "api key" not in message
    if status in {401, 403}:
        assert "paste" in message


@pytest.mark.parametrize("exception_type,reason", [
    (httpx.ConnectError, "connection"),
    (httpx.ReadTimeout, "timed out"),
    (httpx.ConnectTimeout, "timed out"),
])
def test_fetch_network_errors_are_safe_and_actionable(mock_http, exception_type, reason):
    def fail(request):
        raise exception_type("sensitive-token diagnostic", request=request)

    mock_http(fail)
    with pytest.raises(web.WebImportError) as raised:
        web.fetch("https://example.org/article?token=sensitive-token")

    message = error_text(raised.value).lower()
    assert reason in message
    assert "sensitive-token" not in message
    assert "model" not in message


def test_fetch_dns_failure_is_safe_and_does_not_send_request(mock_http, monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("sensitive-token diagnostic")

    monkeypatch.setattr(web.socket, "getaddrinfo", fail)
    requests = mock_http(lambda request: pytest.fail("DNS failure must stop the request"))

    with pytest.raises(web.WebImportError) as raised:
        web.fetch("https://example.org/article?token=sensitive-token")

    message = error_text(raised.value).lower()
    assert "resolve" in message
    assert "sensitive-token" not in message
    assert not requests


def test_fetch_rejects_redirect_without_location(mock_http):
    mock_http(lambda request: httpx.Response(302))

    with pytest.raises(ValueError, match="(?i)redirect"):
        web.fetch("https://example.org/article")


def test_fetch_redirect_limit_is_preserved(mock_http):
    requests = mock_http(lambda request: httpx.Response(302, headers={"location": "/again"}))

    with pytest.raises(ValueError, match="redirects too many"):
        web.fetch("https://example.org/article")

    assert len(requests) == 6


def test_fetch_download_limit_is_preserved(mock_http):
    class OversizedPage(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(26):
                yield b"x" * (1024 * 1024)

    mock_http(lambda request: httpx.Response(200, stream=OversizedPage()))

    with pytest.raises(ValueError, match="25 MB"):
        web.fetch("https://example.org/article")
