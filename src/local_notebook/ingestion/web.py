import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


def public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("Enter a public http:// or https:// URL.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    if any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Only public internet addresses can be imported.")
    return url


def fetch(url: str) -> tuple[str, bytes, str]:
    with httpx.Client(timeout=25, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            public_url(url)
            with client.stream("GET", url, headers={"User-Agent": "LocalNotebook/0.1"}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                data = bytearray()
                for piece in response.iter_bytes():
                    data.extend(piece)
                    if len(data) > 25 * 1024 * 1024:
                        raise ValueError("Web source exceeds the 25 MB download limit.")
                if data.startswith(b"%PDF"):
                    return "Web document.pdf", bytes(data), url
                soup = BeautifulSoup(bytes(data), "html.parser")
                title = soup.title.get_text(strip=True) if soup.title else urlparse(url).hostname
                for item in soup(["script", "style", "nav", "footer", "header"]):
                    item.decompose()
                text = soup.get_text("\n", strip=True)
                if len(text) < 80:
                    raise ValueError("This page has no readable article. Try a public export or paste its text.")
                safe_title = "".join(char for char in title[:100] if char.isalnum() or char in " -_")
                return (safe_title or "Web article") + ".txt", text.encode(), url
    raise ValueError("This URL redirects too many times.")
