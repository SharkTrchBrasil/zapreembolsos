import os
import boto3
from botocore.exceptions import ClientError
from app.config import settings

class StorageService:
    def __init__(self):
        # Utiliza boto3 com credentials puxadas do environment via pydantic
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
            region_name=settings.AWS_REGION
        )
        self.bucket_name = settings.AWS_S3_BUCKET

    def upload_image(self, file_bytes: bytes, file_name: str, content_type: str = "image/jpeg") -> str:
        """
        Faz o upload da imagem pro S3 e retorna a key gerada.
        Se as credenciais não estiverem configuradas, salva localmente na pasta 'uploads' por enquanto.
        """
        if not settings.AWS_ACCESS_KEY_ID:
            # Fallback para desenvolvimento local
            os.makedirs("uploads", exist_ok=True)
            local_path = os.path.join("uploads", file_name.replace("/", "_"))
            with open(local_path, "wb") as f:
                f.write(file_bytes)
            return local_path

        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=file_name,
                Body=file_bytes,
                ContentType=content_type
            )
            return file_name
        except ClientError as e:
            print(f"[S3 Error] Falha no upload: {e}")
            raise e

    def generate_presigned_url(self, file_key: str, expiration: int = 3600) -> str:
        """
        Gera uma URL temporária (presigned) para visualização do comprovante no painel ou WhatsApp.
        """
        if not settings.AWS_ACCESS_KEY_ID:
            return f"http://localhost:8000/static/uploads/{file_key}"

        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': file_key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            print(f"[S3 Error] Falha ao gerar URL presigned: {e}")
            return ""

storage_service = StorageService()
