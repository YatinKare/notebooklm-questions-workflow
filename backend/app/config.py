from pathlib import Path
import os
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    google_api_key: str = ""
    notebook_id: str = ""
    nlm_cookie_path: str = "/mnt/data/profiles/default/cookies.json"
    nlm_mcp_command: str = ""
    nlm_mcp_args: str = ""
    notebooklm_query_timeout: float = 120.0
    db_path: str = "/mnt/data/app.db"
    cors_origin: str = "*"
    extractor_model: str = "gemini-2.5-flash"
    verifier_model: str = "gemini-2.5-flash"

    @model_validator(mode="after")
    def validate_paths(self) -> "Settings":
        def is_dir_writable(path_str: str) -> bool:
            try:
                path = Path(path_str).resolve()
                curr = path
                while not curr.exists():
                    if curr.parent == curr:
                        break
                    curr = curr.parent
                if curr.exists():
                    # Check if we can write to this directory
                    return os.access(curr, os.W_OK)
                return False
            except Exception:
                return False

        if not is_dir_writable(self.db_path):
            local_db = Path(__file__).parent.parent / "app.db"
            self.db_path = str(local_db.resolve())

        if not is_dir_writable(self.nlm_cookie_path):
            local_cookie = Path(__file__).parent.parent / "cookies.json"
            self.nlm_cookie_path = str(local_cookie.resolve())

        return self


settings = Settings()

