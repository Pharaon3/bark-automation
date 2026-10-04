# auth.py
import json
import os
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import DELETE_PROCESSED_EMAILS, DELETE_MODE

FULL_ACCESS = 'https://mail.google.com/'


def required_scopes():
    """Smallest Gmail scope that does what config.py asks for."""
    if not DELETE_PROCESSED_EMAILS:
        return ['https://www.googleapis.com/auth/gmail.readonly']
    if DELETE_MODE == 'delete':
        return [FULL_ACCESS]                                        # permanent delete needs full access
    return ['https://www.googleapis.com/auth/gmail.modify']         # read + move to Trash


SCOPES = required_scopes()
TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'GmailBot_credentials.json'


def token_covers_scopes(token_path, needed):
    """True if the saved token was granted the scopes we need now."""
    try:
        with open(token_path, 'r') as f:
            granted = set(json.load(f).get('scopes') or [])
    except (OSError, ValueError):
        return False
    return FULL_ACCESS in granted or set(needed) <= granted


def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        if token_covers_scopes(TOKEN_FILE, SCOPES):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        else:
            # Token was created with weaker permissions (e.g. read-only before the
            # delete feature): sign in again once to grant the new permission.
            print("Gmail token has fewer permissions than needed, re-authorizing...")
            os.remove(TOKEN_FILE)

    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            # Token expired or revoked (happens every 7 days while the
            # consent screen is in Testing mode). Re-authorize.
            print("Gmail token expired or revoked, re-authorizing...")
            creds = None
            os.remove(TOKEN_FILE)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)
