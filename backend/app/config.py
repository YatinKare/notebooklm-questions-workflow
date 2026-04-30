from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    google_api_key: str = ""
    notebook_id: str = ""
    nlm_cookie_path: str = "/mnt/data/nlm_cookies.json"
    nlm_mcp_command: str = ""
    nlm_mcp_args: str = ""
    notebooklm_query_timeout: float = 120.0
    db_path: str = "/mnt/data/app.db"
    cors_origin: str = "*"
    extractor_model: str = "gemini-2.5-flash"
    verifier_model: str = "gemini-2.5-flash"


settings = Settings()
