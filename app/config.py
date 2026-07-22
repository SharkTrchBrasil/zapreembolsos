import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "ZapReembolso API"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/zapreembolso"
    
    WUZAPI_BASE_URL: str = "http://localhost:8080"
    WUZAPI_USER_TOKEN: str = "seu_token_wuzapi"
    
    WEBHOOK_SECRET: str = "change_me_in_production"
    
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET: str = "zap-reembolsos"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
