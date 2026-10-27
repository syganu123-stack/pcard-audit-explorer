import os
import json
import gzip
import shutil
import tempfile
from pathlib import Path

import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

BASE = Path(__file__).resolve().parent
DB = BASE / "pcards.db"

def download_database():
    if DB.exists():
        print("Database already exists.")
        return

    file_id = os.environ["GOOGLE_DRIVE_FILE_ID"]
    credentials_path = os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS",
        "/etc/secrets/google-service-account.json"
    )
    credentials_json = Path(credentials_path).read_text()

    info = json.loads(credentials_json)
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    credentials.refresh(Request())

    url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
    headers = {"Authorization": f"Bearer {credentials.token}"}

    with tempfile.TemporaryDirectory() as folder:
        archive = Path(folder) / "pcards.db.gz"

        with requests.get(
            url,
            params={"alt": "media"},
            headers=headers,
            stream=True,
            timeout=120
        ) as response:
            response.raise_for_status()
            with archive.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        output.write(chunk)

        temporary_db = BASE / "pcards.db.tmp"
        try:
            with gzip.open(archive, "rb") as source:
                with temporary_db.open("wb") as target:
                    shutil.copyfileobj(source, target)

            os.replace(temporary_db, DB)
        finally:
            temporary_db.unlink(missing_ok=True)

    print("Database downloaded successfully.")

if __name__ == "__main__":
    download_database()
