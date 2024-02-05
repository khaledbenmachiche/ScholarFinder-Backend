from .google_api_service import create_service
from io import BytesIO, FileIO
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload,MediaFileUpload
import os
class GoogleDriveAPIHandler:
    def __init__(self, client_secret_file, api_name, api_version, scopes):
        self.service = create_service(client_secret_file, api_name, api_version, scopes)
        
    def list_files(self, folder_id):
        results = self.service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id, name)"
        ).execute()
        return results.get('files', [])
    
    
    def get_file_content(self, file_id):
        file_content = self.service.files().get_media(fileId=file_id).execute()
        return file_content.decode('utf-8')
    
    def get_file_content_request(self, file_id):
        return self.service.files().get_media(fileId=file_id)
    
    def create_permission(self, file_id):
        request_body = {
            'role': 'reader',
            'type': 'anyone'
        }
        return self.service.permissions().create(fileId=file_id, body=request_body).execute()
    
    
    def get_share_link(self, file_id):
        response_share_link = self.service.files().get(fileId=file_id, fields='webViewLink').execute()
        return response_share_link.get('webViewLink')
    
    
    def get_web_content_link(self, file_id):
        file_metadata = self.service.files().get(fileId=file_id, fields='webContentLink').execute()
        return file_metadata.get('webContentLink')
    
    def update_scraped_files(self, scraped_files_drive_id, updated_content):
        media = MediaIoBaseUpload(BytesIO(updated_content.encode('utf-8')), mimetype='text/plain', resumable=True)
        return self.service.files().update(fileId=scraped_files_drive_id, media_body=media).execute()
    
    def get_file_metadata(self, file_id):
        return self.service.files().get(fileId=file_id, fields='webContentLink').execute()
    
    def download_file(self, file_id, download_path):
        request = self.service.files().get_media(fileId=file_id)
        fh = FileIO(download_path, mode='wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            print(f"Download {int(status.progress() * 100)}%.")
        print("Download Complete!")
    
    def upload_file(self, file_name, file_path, folder_id):
        actual_file_name = os.path.basename(file_name)
        file_metadata = {
            'name': actual_file_name,
            'parents': [folder_id]
        }
        print(f"Uploading file: {actual_file_name}")
        print(f"File path: {file_path}")
        
        media = MediaFileUpload(file_path, resumable=True)
        file = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
        
    