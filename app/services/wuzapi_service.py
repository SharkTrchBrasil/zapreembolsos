import httpx
import base64
import logging
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from app.config import settings

logger = logging.getLogger("wuzapi")

class WuzAPIService:
    def __init__(self):
        self.base_url = settings.WUZAPI_BASE_URL.rstrip('/')
        self.headers = {
            "token": settings.WUZAPI_USER_TOKEN,
            "Content-Type": "application/json"
        }
        self._client = None

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def send_text_message(self, phone: str, message: str) -> bool:
        """Envia mensagem de texto simples pelo WuzAPI."""
        url = f"{self.base_url}/chat/send/text"
        payload = {
            "Phone": phone,
            "Body": message
        }
        logger.debug(f"Enviando para {url}")
        
        try:
            response = await self.get_client().post(url, json=payload, headers=self.headers)
            logger.info(f"Mensagem enviada para {phone} - Status: {response.status_code}")
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Falha de rede ao enviar mensagem para {phone}: {e}")
            return False

    async def send_image_message(self, phone: str, image_url: str, caption: str = "") -> bool:
        """Envia uma mensagem de imagem com legenda pelo WuzAPI."""
        url = f"{self.base_url}/chat/send/image"
        payload = {
            "Phone": phone,
            "Image": image_url,
            "Caption": caption
        }
        logger.debug(f"Enviando imagem para {phone}")

        try:
            response = await self.get_client().post(url, json=payload, headers=self.headers)
            logger.info(f"Imagem enviada para {phone} - Status: {response.status_code}")
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Falha ao enviar imagem para {phone}: {e}")
            # Fallback para mensagem de texto caso o endpoint de imagem falhe
            fallback_msg = f"{caption}\n\n🔗 **Ver Comprovante:** {image_url}"
            return await self.send_text_message(phone, fallback_msg)

    async def send_typing_indicator(self, phone: str, is_typing: bool = True) -> bool:
        """Envia indicador de 'digitando...' para o contato."""
        url = f"{self.base_url}/chat/presence"
        payload = {
            "Phone": phone,
            "State": "composing" if is_typing else "paused",
            "Media": ""
        }
        try:
            response = await self.get_client().post(url, json=payload, headers=self.headers)
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Falha ao enviar typing_indicator para {phone}: {e}")
            return False

    async def send_document_message(self, phone: str, document_base64: str, filename: str, caption: str = "") -> bool:
        """Envia um arquivo (PDF/CSV) em base64 pelo WuzAPI."""
        url = f"{self.base_url}/chat/send/document"
        payload = {
            "Phone": phone,
            "Document": f"data:application/octet-stream;base64,{document_base64}",
            "FileName": filename,
            "Caption": caption
        }
        try:
            response = await self.get_client().post(url, json=payload, headers=self.headers)
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Falha ao enviar documento para {phone}: {e}")
            return False

    async def download_media(self, url: str, media_key_b64: str, media_type: str = "Image") -> bytes:
        """Faz o download da mídia criptografada da CDN do WhatsApp e a decripta."""
        try:
            r = await self.get_client().get(url)
            r.raise_for_status()
            encrypted_data = r.content

            media_key = base64.b64decode(media_key_b64)
            app_info = f"WhatsApp {media_type} Keys".encode()
            
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=112,
                salt=None,
                info=app_info,
                backend=default_backend()
            )
            expanded_key = hkdf.derive(media_key)
            
            iv = expanded_key[0:16]
            cipher_key = expanded_key[16:48]
            
            # Formato dos dados: [conteúdo criptografado][10-byte MAC]
            encrypted_content = encrypted_data[:-10]
            
            cipher = Cipher(algorithms.AES(cipher_key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted_padded_data = decryptor.update(encrypted_content) + decryptor.finalize()
            
            unpadder = padding.PKCS7(128).unpadder()
            decrypted_data = unpadder.update(decrypted_padded_data) + unpadder.finalize()
            
            return decrypted_data
        except Exception as e:
            logger.error(f"Falha ao baixar e decriptar mídia: {e}")
            return None

wuzapi_client = WuzAPIService()
