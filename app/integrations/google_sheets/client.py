import json
import os
import tempfile
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class GoogleSheetsPermissionError(RuntimeError):
    pass


class GoogleSheetsClient:
    def __init__(self, oauth_client_path: str, token_path: str):
        self.oauth_client_path = oauth_client_path
        self.token_path = token_path
        self.credentials = self._authenticate()
        import gspread

        self.client = gspread.authorize(self.credentials)

    def _build_flow(self):
        """Cria o InstalledAppFlow a partir de env var JSON ou arquivo em disco."""
        env_json = os.getenv("GOOGLE_SHEETS_OAUTH_CLIENT_JSON")
        if env_json:
            client_config = json.loads(env_json)
            return InstalledAppFlow.from_client_config(client_config, SCOPES)
        if os.path.exists(self.oauth_client_path):
            return InstalledAppFlow.from_client_secrets_file(self.oauth_client_path, SCOPES)
        return None

    def _authenticate(self):
        credentials = None

        if os.path.exists(self.token_path):
            credentials = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = self._build_flow()
                if flow is None:
                    raise FileNotFoundError(
                        f"Arquivo OAuth não encontrado: {self.oauth_client_path}. "
                        "Configure GOOGLE_SHEETS_OAUTH_CLIENT_JSON no ambiente."
                    )
                credentials = flow.run_local_server(
                    port=0,
                    prompt="select_account consent",
                )

            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(self.token_path, "w", encoding="utf-8") as token_file:
                token_file.write(credentials.to_json())

        return credentials

    def authenticated_email(self):
        try:
            request = UrlRequest(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {self.credentials.token}"},
            )
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload.get("email", "")
        except Exception:
            return ""

    def open_spreadsheet(self, spreadsheet_id: str):
        try:
            return self.client.open_by_key(spreadsheet_id)
        except Exception as exc:
            message = str(exc)
            if "403" in message or "PERMISSION_DENIED" in message:
                email = self.authenticated_email() or "conta autenticada"
                raise GoogleSheetsPermissionError(
                    "A conta autenticada no OAuth não tem permissão para abrir a "
                    f"planilha. Compartilhe a planilha com o e-mail autenticado: {email}."
                ) from exc
            raise

    def get_worksheet_by_gid(self, spreadsheet_id: str, gid: int):
        spreadsheet = self.open_spreadsheet(spreadsheet_id)

        for worksheet in spreadsheet.worksheets():
            if worksheet.id == gid:
                return worksheet

        raise ValueError(f"Aba com GID {gid} não encontrada.")
