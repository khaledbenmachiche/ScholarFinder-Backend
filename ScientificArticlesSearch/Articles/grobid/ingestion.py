"""PDF -> GROBID -> TEI -> `Article` rows."""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

from ..models import Article
from ..serializers import ArticleSerializer
from .client import GrobidClient, StrPath
from .tei_parser import parse_tei

logger = logging.getLogger(__name__)


@dataclass
class IngestionReport:
    created: List[Article] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)  # file name -> reason

    def as_dict(self) -> dict:
        return {
            "created": [{"id": a.id, "titre": a.titre} for a in self.created],
            "failed": self.failed,
        }


def _clamp(value: str, field_name: str) -> str:
    max_length = Article._meta.get_field(field_name).max_length
    if max_length and len(value) > max_length:
        return value[: max_length - 1].rstrip() + "…"
    return value


class ArticleIngestor:
    """Extracts articles from PDFs with GROBID and stores them for moderation.

    New articles are created with `is_validated=False`; a moderator reviews and
    corrects the extracted fields before they become visible in search.
    """

    def __init__(
        self,
        client: Optional[GrobidClient] = None,
        tei_dir: Optional[StrPath] = None,
        max_workers: Optional[int] = None,
    ):
        self.client = client or GrobidClient.from_settings()
        self.tei_dir = Path(tei_dir) if tei_dir else None
        self.max_workers = max_workers or settings.GROBID_MAX_WORKERS

    def ingest(self, documents: Iterable[Tuple[StrPath, str]]) -> IngestionReport:
        """Ingest `(pdf_path, public_url)` pairs; one failure never aborts the batch.

        Raises `GrobidUnavailable` if the server cannot be reached at all.
        """
        urls = {Path(path): url for path, url in documents}
        report = IngestionReport()
        # GROBID calls run in worker threads; parsing and DB writes stay on this thread.
        for path, tei_xml, error in self.client.process_many(urls, max_workers=self.max_workers):
            if error is None:
                try:
                    self._keep_tei(path, tei_xml)
                    report.created.append(self.save_tei(tei_xml, urls[path], fallback_title=path.stem))
                    logger.info("Ingested %s", path.name)
                    continue
                except ValidationError as exc:
                    error = f"invalid extracted data: {exc.detail}"
                except Exception as exc:
                    error = exc
            logger.warning("Failed to ingest %s: %s", path.name, error)
            report.failed[path.name] = str(error)
        return report

    def save_tei(self, tei_xml: str, url: str, fallback_title: str = "") -> Article:
        payload = parse_tei(tei_xml, url=url)
        # A missing title must not lose the whole article: moderators can fix it.
        payload["titre"] = _clamp(payload["titre"] or fallback_title, "titre")
        payload["url"] = _clamp(payload["url"], "url")
        serializer = ArticleSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            return serializer.save()

    def _keep_tei(self, pdf_path: Path, tei_xml: str) -> None:
        """Keep GROBID's raw output so extraction can be re-run without GROBID."""
        if self.tei_dir is None:
            return
        self.tei_dir.mkdir(parents=True, exist_ok=True)
        (self.tei_dir / f"{pdf_path.stem}.tei.xml").write_text(tei_xml, encoding="utf-8")
