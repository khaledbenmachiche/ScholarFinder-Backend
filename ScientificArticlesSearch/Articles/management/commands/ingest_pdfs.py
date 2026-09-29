from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from Articles.grobid import ArticleIngestor, GrobidClient


class Command(BaseCommand):
    help = "Extract articles from local PDF files (or directories of PDFs) with GROBID."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", type=Path, help="PDF files or directories containing PDFs")
        parser.add_argument(
            "--url-prefix",
            default="",
            help="Public URL prefix under which the PDFs are served; the file name is appended",
        )
        parser.add_argument("--workers", type=int, default=settings.GROBID_MAX_WORKERS)

    def handle(self, *args, paths, url_prefix, workers, **options):
        pdfs = []
        for path in paths:
            if path.is_dir():
                pdfs.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() == ".pdf"))
            elif path.is_file():
                pdfs.append(path)
            else:
                raise CommandError(f"{path} does not exist")
        if not pdfs:
            raise CommandError("No PDF found")

        client = GrobidClient.from_settings()
        if not client.is_alive():
            raise CommandError(f"GROBID is not reachable at {client.base_url}")

        self.stdout.write(f"Processing {len(pdfs)} PDF(s) with GROBID at {client.base_url} ...")
        documents = [(pdf, url_prefix + pdf.name if url_prefix else str(pdf.resolve())) for pdf in pdfs]
        report = ArticleIngestor(client, tei_dir=settings.GROBID_TEI_DIR, max_workers=workers).ingest(documents)

        for article in report.created:
            self.stdout.write(self.style.SUCCESS(f"  created #{article.id}: {article.titre[:90]}"))
        for name, reason in report.failed.items():
            self.stdout.write(self.style.ERROR(f"  failed {name}: {reason}"))
        self.stdout.write(f"{len(report.created)} created, {len(report.failed)} failed")
