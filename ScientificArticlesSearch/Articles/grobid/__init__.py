"""PDF -> structured article extraction, backed by a GROBID server.

    client.GrobidClient       talks to the GROBID REST API (retries, timeouts, concurrency)
    tei_parser.parse_tei      turns GROBID's TEI XML into the ArticleSerializer payload
    ingestion.ArticleIngestor glues both together and persists Article rows
"""
from .client import GrobidClient, GrobidError, GrobidUnavailable
from .ingestion import ArticleIngestor, IngestionReport
from .tei_parser import parse_tei

__all__ = [
    "ArticleIngestor",
    "GrobidClient",
    "GrobidError",
    "GrobidUnavailable",
    "IngestionReport",
    "parse_tei",
]
