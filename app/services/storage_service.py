import os
import uuid
import logging
import boto3
from io import BytesIO
from botocore.exceptions import ClientError, BotoCoreError
from app.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self):
        # ✅ Lazy initialization (igual ao Menuhub) — NÃO cria o cliente aqui
        self._s3_client = None
        self.bucket_name = settings.AWS_S3_BUCKET.strip().strip('"').strip("'") if settings.AWS_S3_BUCKET else "zap-reembolsos"

    def _get_s3_client(self):
        """Inicializa ou retorna o cliente S3 (lazy initialization, padrão Menuhub)"""
        if self._s3_client is not None:
            return self._s3_client

        aws_access_key = settings.AWS_ACCESS_KEY_ID.strip().strip('"').strip("'") if settings.AWS_ACCESS_KEY_ID else None
        aws_secret_key = settings.AWS_SECRET_ACCESS_KEY.strip().strip('"').strip("'") if settings.AWS_SECRET_ACCESS_KEY else None
        aws_region = settings.AWS_REGION.strip().strip('"').strip("'") if settings.AWS_REGION else "us-east-1"

        if not aws_access_key or not aws_secret_key:
            logger.error("[CRITICAL] Credenciais AWS incompletas. Cliente S3 não inicializado.")
            logger.error(f"   AWS_ACCESS_KEY_ID presente: {bool(aws_access_key)}")
            logger.error(f"   AWS_SECRET_ACCESS_KEY presente: {bool(aws_secret_key)}")
            return None

        try:
            # Mostra qual chave está sendo usada (para debug)
            masked_key = f"{aws_access_key[:4]}...{aws_access_key[-4:]}" if len(aws_access_key) > 8 else "***"
            print(f"🔑 Tentando autenticar no S3 com Access Key: {masked_key}")
            
            self._s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region
            )
            print(f"[OK] Cliente S3 inicializado | Bucket: {self.bucket_name} | Region: {aws_region}")
        except (BotoCoreError, ClientError) as e:
            print(f"[CRITICAL] FALHA ao inicializar o cliente S3: {e}")
        except Exception as e:
            print(f"[CRITICAL] ERRO INESPERADO ao inicializar o cliente S3: {e}")

        return self._s3_client

    def upload_image(self, file_bytes: bytes, file_name: str, content_type: str = "image/jpeg") -> str:
        """
        Faz o upload da imagem pro S3 e retorna a key gerada.
        Usa upload_fileobj com BytesIO (padrão Menuhub).
        Se as credenciais não estiverem configuradas, salva localmente.
        """
        if not settings.AWS_ACCESS_KEY_ID:
            # Fallback para desenvolvimento local
            os.makedirs("uploads", exist_ok=True)
            local_path = os.path.join("uploads", file_name.replace("/", "_"))
            with open(local_path, "wb") as f:
                f.write(file_bytes)
            return local_path

        s3 = self._get_s3_client()
        if not s3:
            raise Exception("Cliente S3 não disponível. Verifique credenciais AWS.")

        try:
            file_obj = BytesIO(file_bytes)
            s3.upload_fileobj(
                file_obj,
                self.bucket_name,
                file_name,
                ExtraArgs={
                    'ContentType': content_type,
                    'CacheControl': 'public, max-age=31536000, immutable',
                }
            )
            logger.info(f"✅ Upload S3 concluído: {file_name} ({len(file_bytes)} bytes)")
            return file_name
        except ClientError as e:
            logger.error(f"[S3 Error] Falha no upload: {e}", exc_info=True)
            raise e

    def generate_presigned_url(self, file_key: str, expiration: int = 3600) -> str:
        """
        Gera uma URL temporária (presigned) para visualização do comprovante no painel ou WhatsApp.
        """
        if not settings.AWS_ACCESS_KEY_ID:
            return f"http://localhost:8000/static/uploads/{file_key}"

        s3 = self._get_s3_client()
        if not s3:
            return ""

        try:
            url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': file_key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            logger.error(f"[S3 Error] Falha ao gerar URL presigned: {e}")
            return ""

storage_service = StorageService()
