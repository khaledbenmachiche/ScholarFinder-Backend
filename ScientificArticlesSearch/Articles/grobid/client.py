"""Small, dependency-light client for the GROBID REST API.

Only the endpoints this project needs are implemented. See
https://grobid.readthedocs.io/en/latest/Grobid-service/ for the full API.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from os import PathLike
from pathlib import Path
from typing import Iterable, Iterator, Optional, Tuple, Union

import requests

logger = logging.getLogger(__name__)

StrPath = Union[str, PathLike]


class GrobidError(Exception):
    """GROBID could not turn a PDF into TEI."""


class GrobidUnavailable(GrobidError):
    """The GROBID server cannot be reached."""


class GrobidClient:
    """Thread-safe client for GROBID's `processFulltextDocument` service.

    GROBID answers 503 when all of its worker engines are busy; those requests
    are retried with linear backoff, so callers can safely submit more
    documents in parallel than the server has engines.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8070",
        *,
        timeout: float = 120,
        max_retries: int = 5,
        retry_backoff: float = 2.0,
        consolidate_header: bool = True,
        consolidate_citations: bool = False,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.consolidate_header = consolidate_header
        self.consolidate_citations = consolidate_citations
        self.session = session or requests.Session()

    @classmethod
    def from_settings(cls) -> "GrobidClient":
        from django.conf import settings

        return cls(
            settings.GROBID_URL,
            timeout=settings.GROBID_TIMEOUT,
            consolidate_header=settings.GROBID_CONSOLIDATE_HEADER,
            consolidate_citations=settings.GROBID_CONSOLIDATE_CITATIONS,
        )

    def _url(self, service: str) -> str:
        return f"{self.base_url}/api/{service}"

    def is_alive(self) -> bool:
        try:
            response = self.session.get(self._url("isalive"), timeout=5)
        except requests.RequestException:
            return False
        return response.ok

    def process_fulltext(self, pdf_path: StrPath) -> str:
        """Return the TEI XML GROBID extracts from the PDF at `pdf_path`."""
        pdf_path = Path(pdf_path)
        data = {
            "consolidateHeader": int(self.consolidate_header),
            "consolidateCitations": int(self.consolidate_citations),
            # Keep the raw reference string so unparseable citations are not lost.
            "includeRawCitations": 1,
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                with pdf_path.open("rb") as pdf:
                    response = self.session.post(
                        self._url("processFulltextDocument"),
                        files={"input": (pdf_path.name, pdf, "application/pdf")},
                        data=data,
                        headers={"Accept": "application/xml"},
                        timeout=self.timeout,
                    )
            except requests.ConnectionError as exc:
                raise GrobidUnavailable(f"cannot reach GROBID at {self.base_url}") from exc
            except requests.Timeout as exc:
                raise GrobidError(f"{pdf_path.name}: GROBID timed out after {self.timeout}s") from exc

            if response.status_code == 200:
                return response.text
            if response.status_code == 503:
                if attempt == self.max_retries:
                    break
                delay = self.retry_backoff * attempt
                logger.info("GROBID busy, retrying %s in %.1fs (attempt %d)", pdf_path.name, delay, attempt)
                time.sleep(delay)
                continue
            if response.status_code == 204:
                raise GrobidError(f"{pdf_path.name}: GROBID extracted no content (is it a scanned PDF?)")
            raise GrobidError(f"{pdf_path.name}: GROBID returned HTTP {response.status_code}: {response.text[:200]}")

        raise GrobidError(f"{pdf_path.name}: GROBID still busy after {self.max_retries} attempts")

    def process_many(
        self, pdf_paths: Iterable[StrPath], max_workers: int = 4
    ) -> Iterator[Tuple[Path, Optional[str], Optional[Exception]]]:
        """Process PDFs concurrently, yielding `(path, tei_xml, error)` as each finishes.

        Exactly one of `tei_xml` / `error` is set. A `GrobidUnavailable` error is
        re-raised immediately since every remaining document would fail too.
        """
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self.process_fulltext, path): Path(path) for path in pdf_paths}
            try:
                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        yield path, future.result(), None
                    except GrobidUnavailable:
                        raise
                    except Exception as exc:  # one bad PDF must not abort the batch
                        yield path, None, exc
            finally:
                for future in futures:
                    future.cancel()
