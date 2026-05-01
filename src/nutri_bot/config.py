from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    tg_token: str
    openai_api_key: str
    supabase_url: str
    supabase_key: str  # service role key
    log_level: str = "INFO"


settings = Settings()
