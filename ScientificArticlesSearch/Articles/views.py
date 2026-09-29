import logging
import os
import tempfile
from zipfile import BadZipFile, ZipFile

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .CustomPermissions import IsAdmin, IsModerator
from .grobid import ArticleIngestor, GrobidUnavailable
from .models import Article
from .serializers import ArticleSerializer
from .utils import extract_drive_folder_id

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF"
UPLOAD_SUBDIR = "EchantillonsArticlesScrapping"


def _is_staff(user):
    return user.is_authenticated and getattr(user, "user_type", None) in ("Admin", "Mod")


def _file_schema(description):
    return openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={"file": openapi.Schema(type=openapi.TYPE_FILE, description=description)},
        required=["file"],
    )


def _url_schema(description):
    return openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={"url": openapi.Schema(type=openapi.TYPE_STRING, description=description)},
        required=["url"],
    )


_INGESTION_RESPONSES = {
    201: openapi.Response("At least one article was extracted and is awaiting moderation"),
    400: openapi.Response("Invalid input"),
    422: openapi.Response("No article could be extracted"),
    503: openapi.Response("GROBID server unavailable"),
}


class ArticleViewSet(ModelViewSet):
    """Articles extracted from PDFs by GROBID.

    Anonymous and regular users only see validated articles. Moderators and
    admins also see pending ones and can correct or delete them.
    """

    serializer_class = ArticleSerializer
    queryset = Article.objects.all()

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), (IsModerator | IsAdmin)()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = Article.objects.prefetch_related("mot_cles", "auteurs__institutions", "references_bibliographique")
        if self.action in ("list", "retrieve") and not _is_staff(self.request.user):
            queryset = queryset.filter(is_validated=True)
        return queryset.order_by("-created_at")

    @swagger_auto_schema(auto_schema=None)
    def create(self, request, *args, **kwargs):
        # Articles are only created through the ingestion endpoints below.
        raise MethodNotAllowed("POST")

    @action(detail=False, methods=["get"], url_path="validated", permission_classes=(IsAuthenticated,))
    def get_validated_articles(self, request, *args, **kwargs):
        articles = self.get_queryset().filter(is_validated=True)
        return Response(ArticleSerializer(articles, many=True).data)

    @action(detail=False, methods=["get"], url_path="not_validated", permission_classes=(IsAuthenticated, IsModerator))
    def get_not_validated_articles(self, request, *args, **kwargs):
        articles = self.get_queryset().filter(is_validated=False)
        return Response(ArticleSerializer(articles, many=True).data)

    @action(detail=True, methods=["put"], url_path="validate", permission_classes=(IsAuthenticated, IsModerator))
    def validate_article(self, request, *args, **kwargs):
        article = self.get_object()
        if article.is_validated:
            return Response({"message": "Article already validated"}, status=status.HTTP_400_BAD_REQUEST)
        article.is_validated = True
        article.save(update_fields=["is_validated", "updated_at"])
        return Response({"message": "Article validated successfully"})

    # ---- Ingestion: PDF -> GROBID -> Article(is_validated=False) -------------

    @swagger_auto_schema(
        methods=["post"],
        operation_description="Extract an article from an uploaded PDF",
        request_body=_file_schema("PDF file"),
        responses=_INGESTION_RESPONSES,
    )
    @action(detail=False, methods=["post"], url_path="upload-via-file", permission_classes=(IsAuthenticated, IsAdmin))
    def upload_article_via_file(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"message": "Please upload a PDF file."}, status=status.HTTP_400_BAD_REQUEST)
        content = upload.read(settings.MAX_PDF_UPLOAD_SIZE + 1)
        error = self._check_pdf(upload.name, content)
        if error:
            return Response({"message": error}, status=status.HTTP_400_BAD_REQUEST)
        return self._ingest(request, [(upload.name, content)])

    @swagger_auto_schema(
        methods=["post"],
        operation_description="Extract every PDF contained in an uploaded zip archive",
        request_body=_file_schema("Zip archive of PDF files"),
        responses=_INGESTION_RESPONSES,
    )
    @action(detail=False, methods=["post"], url_path="upload-via-zip", permission_classes=(IsAuthenticated, IsAdmin))
    def upload_article_via_zip(self, request, *args, **kwargs):
        zip_file = request.FILES.get("file")
        if zip_file is None or not zip_file.name.lower().endswith(".zip"):
            return Response({"message": "Please upload a zip file."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with ZipFile(zip_file) as archive:
                members = [
                    m for m in archive.infolist()
                    if not m.is_dir() and m.filename.lower().endswith(".pdf")
                    and m.file_size <= settings.MAX_PDF_UPLOAD_SIZE
                ]
                pdfs = [(os.path.basename(m.filename), archive.read(m)) for m in members]
        except BadZipFile:
            return Response({"message": "Invalid zip file."}, status=status.HTTP_400_BAD_REQUEST)
        pdfs = [(name, content) for name, content in pdfs if content.startswith(PDF_MAGIC)]
        if not pdfs:
            return Response({"message": "No PDF files found in the zip file."}, status=status.HTTP_400_BAD_REQUEST)
        return self._ingest(request, pdfs)

    @swagger_auto_schema(
        methods=["post"],
        operation_description="Download a PDF from a URL and extract the article",
        request_body=_url_schema("URL of a PDF file"),
        responses=_INGESTION_RESPONSES,
    )
    @action(detail=False, methods=["post"], url_path="upload-via-url", permission_classes=(IsAuthenticated, IsAdmin))
    def upload_article_via_url(self, request, *args, **kwargs):
        pdf_url = request.data.get("url")
        if not pdf_url or not pdf_url.startswith(("http://", "https://")):
            return Response({"message": "Please provide an http(s) url"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with requests.get(pdf_url, stream=True, timeout=30) as response:
                response.raise_for_status()
                content = response.raw.read(settings.MAX_PDF_UPLOAD_SIZE + 1, decode_content=True)
        except requests.RequestException as exc:
            return Response({"message": f"Could not download the file: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
        name = os.path.basename(pdf_url.split("?")[0]) or "article.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        error = self._check_pdf(name, content)
        if error:
            return Response({"message": error}, status=status.HTTP_400_BAD_REQUEST)
        return self._ingest(request, [(name, content)])

    @swagger_auto_schema(
        methods=["post"],
        operation_description="Extract every PDF of a Google Drive folder not imported yet",
        request_body=_url_schema("Google Drive folder URL"),
        responses=_INGESTION_RESPONSES,
    )
    @action(detail=False, methods=["post"], url_path="upload-via-drive", permission_classes=(IsAuthenticated, IsAdmin))
    def upload_article_via_drive(self, request, *args, **kwargs):
        if not settings.GOOGLE_DRIVE_ENABLED:
            return Response({"message": "Google Drive is not configured on this server."}, status=status.HTTP_501_NOT_IMPLEMENTED)
        folder_id = extract_drive_folder_id(request.data.get("url") or "")
        if not folder_id:
            return Response({"message": "Please provide a Google Drive folder url"}, status=status.HTTP_400_BAD_REQUEST)

        from .google_drive.google_drive_api_handler import get_drive_handler

        drive = get_drive_handler()
        files = drive.list_pdfs(folder_id)
        already_imported = set(
            Article.objects.filter(url__in=[f.get("webContentLink") for f in files]).values_list("url", flat=True)
        )
        new_files = [f for f in files if f.get("webContentLink") not in already_imported]
        if not new_files:
            return Response({"message": "No new PDF in this folder.", "created": [], "failed": {}})

        with tempfile.TemporaryDirectory() as tmp:
            documents = []
            for f in new_files:
                path = os.path.join(tmp, os.path.basename(f["name"]))
                drive.download_file(f["id"], path)
                documents.append((path, f["webContentLink"]))
            return self._run_ingestion(documents)

    # ---- helpers --------------------------------------------------------------

    @staticmethod
    def _check_pdf(name, content):
        if len(content) > settings.MAX_PDF_UPLOAD_SIZE:
            return f"{name} is larger than {settings.MAX_PDF_UPLOAD_SIZE // (1024 * 1024)} MB."
        if not content.startswith(PDF_MAGIC):
            return f"{name} is not a PDF file."
        return None

    def _ingest(self, request, pdfs):
        """Store uploaded PDFs, publish them, then extract them with GROBID."""
        storage = FileSystemStorage()
        documents = []
        for name, content in pdfs:
            stored_name = storage.save(os.path.join(UPLOAD_SUBDIR, os.path.basename(name)), ContentFile(content))
            path = storage.path(stored_name)
            documents.append((path, self._public_url(request, storage, stored_name, path)))
        return self._run_ingestion(documents)

    @staticmethod
    def _public_url(request, storage, stored_name, path):
        """Where readers download the PDF: Google Drive if configured, else our media URL."""
        if settings.GOOGLE_DRIVE_ENABLED:
            from .google_drive.google_drive_api_handler import get_drive_handler

            drive = get_drive_handler()
            file_id = drive.upload_file(path, settings.GOOGLE_DRIVE_UPLOAD_FOLDER_ID)
            return drive.get_web_content_link(file_id)
        return request.build_absolute_uri(storage.url(stored_name))

    @staticmethod
    def _run_ingestion(documents):
        try:
            report = ArticleIngestor(tei_dir=settings.GROBID_TEI_DIR).ingest(documents)
        except GrobidUnavailable as exc:
            logger.error("GROBID unavailable: %s", exc)
            return Response({"message": "The PDF extraction service is unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        code = status.HTTP_201_CREATED if report.created else status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(report.as_dict(), status=code)
