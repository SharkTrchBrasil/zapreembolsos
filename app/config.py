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
    GEMINI_FALLBACK_KEYS: str = ""
    GROQ_API_KEY: str = ""
    
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET: str = "zap-reembolsos"

    EFI_CLIENT_ID: str = "Client_Id_Example"
    EFI_CLIENT_SECRET: str = "Client_Secret_Example"
    EFI_CERTIFICATE_PATH: str = "cert.pem"
    
    JWT_SECRET: str = "your_super_secret_jwt_key_here"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    EFI_PIX_KEY: str = "comercial@zapreembolso.com.br"
    
    REDIS_URL: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
