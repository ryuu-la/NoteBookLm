"""Read public web pages into memory for chat; never persist or index them."""
import asyncio
from io import BytesIO
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .web import public_url

MAX_BYTES = 8 * 1024 * 1024
MAX_TEXT = 100_000


def normalize_url(url: str) -> str:
    url = urldefrag(url.strip())[0]
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only public HTTP or HTTPS pages can be read.')
    return url


def extract(data: bytes, url: str, content_type: str) -> dict:
    if data.startswith(b'%PDF'):
        reader = PdfReader(BytesIO(data))
        texts, size = [], 0
        for number, page in enumerate(reader.pages):
            if number >= 30 or size >= MAX_TEXT:
                break
            text = f'Page {number + 1}\n{page.extract_text() or ""}'
            texts.append(text)
            size += len(text)
        return {'url': url, 'title': urlparse(url).path.rsplit('/', 1)[-1] or 'Web PDF',
                'text': '\n\n'.join(texts)[:MAX_TEXT], 'links': []}
    if not any(kind in content_type for kind in ('html', 'text/plain', 'xml', 'xhtml')):
        raise ValueError('This link is not a readable web page or PDF.')
    soup = BeautifulSoup(data, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else urlparse(url).hostname
    for element in soup(['script', 'style', 'nav', 'header', 'footer', 'form', 'noscript', 'svg']):
        element.decompose()
    article = soup.find('main') or soup.find('article') or soup.body or soup
    links, seen = [], set()
    for anchor in article.find_all('a', href=True):
        try:
            target = normalize_url(urljoin(url, anchor['href']))
        except ValueError:
            continue
        label = anchor.get_text(' ', strip=True)
        if target != url and target not in seen and label and len(links) < 45:
            seen.add(target)
            links.append({'url': target, 'title': label[:180], 'description': 'Linked from ' + title[:120]})
    text = article.get_text('\n', strip=True)[:MAX_TEXT]
    if len(text) < 100:
        raise ValueError('This page has too little readable text.')
    return {'url': url, 'title': title[:200], 'text': text, 'links': links}


async def read_page(url: str) -> dict:
    url = normalize_url(url)
    async with httpx.AsyncClient(timeout=18, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            await asyncio.to_thread(public_url, url)
            async with client.stream('GET', url, headers={'User-Agent': 'FolioResearch/1.0 (personal study assistant)'}) as response:
                if response.is_redirect:
                    url = normalize_url(urljoin(url, response.headers['location']))
                    continue
                response.raise_for_status()
                data = bytearray()
                async for piece in response.aiter_bytes():
                    data.extend(piece)
                    if len(data) > MAX_BYTES:
                        raise ValueError('This page exceeds the research download limit.')
                page = await asyncio.to_thread(extract, bytes(data), url, response.headers.get('content-type', ''))
                if len(page['text'].strip()) < 100:
                    raise ValueError('This page has no readable text.')
                return page
    raise ValueError('This page redirects too many times.')
