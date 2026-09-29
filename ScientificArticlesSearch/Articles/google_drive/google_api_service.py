import os
import pickle

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


class GoogleDriveNotConfigured(RuntimeError):
    pass


def create_service(client_secret_file, api_name, api_version, scopes, token_file=None):
    """Build an authorised Google API client.

    The OAuth token is cached in `token_file`. The interactive browser consent
    flow only runs when there is no usable token, which is why this must never
    be called at import time.
    """
    token_file = token_file or f"token_{api_name}_{api_version}.pickle"
    cred = None
    if os.path.exists(token_file):
        with open(token_file, "rb") as token:
            cred = pickle.load(token)

    if not cred or not cred.valid:
        if cred and cred.expired and cred.refresh_token:
            cred.refresh(Request())
        else:
            if not client_secret_file or not os.path.exists(client_secret_file):
                raise GoogleDriveNotConfigured(
                    "Google Drive is enabled but neither a valid token nor the OAuth client secret file was found"
                )
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, list(scopes))
            cred = flow.run_local_server()

        with open(token_file, "wb") as token:
            pickle.dump(cred, token)

    return build(api_name, api_version, credentials=cred)
