import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    SUPABASE_PROJECT_URL: str
    SUPABASE_SECRET_KEY: str
    GEMINI_API_KEY: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Configure global logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("news-summary-backend")
