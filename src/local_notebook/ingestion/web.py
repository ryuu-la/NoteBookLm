import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
USER_AGENT = 'FolioLocalNotebook/0.2 (local user-requested document imports)'
logger = logging.getLogger(__name__)


class WebImportError(ValueError):
    """A website failure with safe, source-specific guidance for the UI."""


def public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("Enter a public http:// or https:// URL.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    if any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Only public internet addresses can be imported.")
    return url


def fetch(url: str) -> tuple[str, bytes, str]:
    try:
        return _fetch(url.strip())
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning('Website import failed: HTTP %s', status)
        if status in {401, 403}:
            message = ('This website blocked automatic access (HTTP ' + str(status)
                       + '). Open the article in your browser, then use Paste text to add its contents.')
        elif status == 404:
            message = 'This web page was not found (HTTP 404). Check the article URL.'
        elif status == 429:
            message = 'This website received too many requests (HTTP 429). Wait before trying again, or use Paste text.'
        elif status >= 500:
            message = f'This website is temporarily unavailable (HTTP {status}). Try again later or use Paste text.'
        else:
            message = f'This website could not be imported (HTTP {status}). Try its public article URL or use Paste text.'
        raise WebImportError(message) from exc
    except httpx.TimeoutException as exc:
        logger.warning('Website import timed out')
        raise WebImportError('The website timed out. Try again later or use Paste text to add the article.') from exc
    except socket.gaierror as exc:
        logger.warning('Website import DNS lookup failed')
        raise WebImportError('Could not resolve this website address. Check the URL and your internet connection.') from exc
    except httpx.RequestError as exc:
        logger.warning('Website import connection failed: %s', type(exc).__name__)
        raise WebImportError('Could not connect to this website. Check your internet connection or use Paste text.') from exc


def _fetch(url: str) -> tuple[str, bytes, str]:
    with httpx.Client(timeout=25, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            public_url(url)
            with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as response:
                if response.is_redirect:
                    location = response.headers.get('location')
                    if not location:
                        raise WebImportError('This website sent an invalid redirect. Try its final article URL.')
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                data = bytearray()
                for piece in response.iter_bytes():
                    data.extend(piece)
                    if len(data) > MAX_DOWNLOAD_BYTES:
                        raise ValueError("Web source exceeds the 25 MB download limit.")
                if data.startswith(b"%PDF"):
                    return "Web document.pdf", bytes(data), url
                soup = BeautifulSoup(bytes(data), "html.parser")
                title = soup.title.get_text(strip=True) if soup.title else urlparse(url).hostname
                for item in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "svg"]):
                    item.decompose()
                article = soup.find('main') or soup.find('article') or soup.body or soup
                text = article.get_text("\n", strip=True)
                if len(text) < 80:
                    raise ValueError("This page has no readable article. Try a public export or paste its text.")
                safe_title = "".join(char for char in title[:100] if char.isalnum() or char in " -_")
                return (safe_title or "Web article") + ".txt", text.encode(), url
    raise ValueError("This URL redirects too many times.")
