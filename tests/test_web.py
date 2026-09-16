import pytest

from local_notebook.ingestion.web import public_url


@pytest.mark.parametrize("url", ["file:///C:/secret", "http://127.0.0.1", "http://localhost", "http://169.254.169.254"])
def test_private_urls_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)
