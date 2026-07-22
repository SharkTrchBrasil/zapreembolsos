import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "ZapReembolso API"
    DEBUG: bool = True
    DATABASE_URL: str = "sqlite+aiosqlite:///./zapreembolso.db"
    
    WUZAPI_BASE_URL: str = "http://localhost:8080"
    WUZAPI_USER_TOKEN: str = "seu_token_wuzapi"
    
    OPENAI_API_KEY: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
