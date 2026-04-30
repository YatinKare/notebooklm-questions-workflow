from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_api_key: str = ""
    notebook_id: str = ""
    nlm_cookie_path: str = "/mnt/data/nlm_cookies.json"
    db_path: str = "/mnt/data/app.db"
    cors_origin: str = "*"
    extractor_model: str = "gemini-2.0-flash"
    verifier_model: str = "gemini-2.0-flash"


settings = Settings()
