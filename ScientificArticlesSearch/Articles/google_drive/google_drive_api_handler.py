import logging
import os
from functools import lru_cache
from io import FileIO

from django.conf import settings
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .google_api_service import create_service

logger = logging.getLogger(__name__)

PDF_MIME_TYPE = "application/pdf"


class GoogleDriveAPIHandler:
    def __init__(self, client_secret_file, api_name="drive", api_version="v3", scopes=None, token_file=None):
        scopes = scopes or ["https://www.googleapis.com/auth/drive"]
        self.service = create_service(client_secret_file, api_name, api_version, scopes, token_file=token_file)

    def list_pdfs(self, folder_id):
        """All PDFs directly inside `folder_id`, following pagination."""
        files, page_token = [], None
        while True:
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and mimeType='{PDF_MIME_TYPE}' and trashed=false",
                fields="nextPageToken, files(id, name, webContentLink)",
                pageToken=page_token,
            ).execute()
            files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                return files

    def get_web_content_link(self, file_id):
        file_metadata = self.service.files().get(fileId=file_id, fields="webContentLink").execute()
        return file_metadata.get("webContentLink")

    def download_file(self, file_id, download_path):
        request = self.service.files().get_media(fileId=file_id)
        with FileIO(download_path, mode="wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    def upload_file(self, file_path, folder_id, file_name=None):
        """Upload a file into `folder_id` and return its Drive file id."""
        file_metadata = {"name": file_name or os.path.basename(file_path), "parents": [folder_id]}
        media = MediaFileUpload(file_path, mimetype=PDF_MIME_TYPE, resumable=True)
        file = self.service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        logger.info("Uploaded %s to Google Drive (%s)", file_metadata["name"], file["id"])
        return file["id"]


@lru_cache(maxsize=1)
def get_drive_handler():
    """Shared Drive client, created on first use (never at import time)."""
    return GoogleDriveAPIHandler(
        settings.GOOGLE_DRIVE_CLIENT_SECRET_FILE,
        token_file=settings.GOOGLE_DRIVE_TOKEN_FILE,
    )
