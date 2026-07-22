import httpx
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend
from app.config import settings

class WuzAPIService:
    def __init__(self):
        self.base_url = settings.WUZAPI_BASE_URL.rstrip('/')
        self.headers = {
            "token": settings.WUZAPI_USER_TOKEN,
            "Content-Type": "application/json"
        }

    async def send_text_message(self, phone: str, message: str) -> bool:
        """Envia mensagem de texto simples pelo WuzAPI."""
        url = f"{self.base_url}/chat/send/text"
        payload = {
            "Phone": phone,
            "Body": message
        }
        print(f"\n[WuzAPI SEND] Enviando para {url}")
        print(f"[WuzAPI SEND] Payload: {payload}")
        print(f"[WuzAPI SEND] Headers (token censurado): {{'token': '***', 'Content-Type': 'application/json'}}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self.headers, timeout=10.0)
                print(f"[WuzAPI RESPONSE] Status: {response.status_code}")
                print(f"[WuzAPI RESPONSE] Body: {response.text}")
                return response.status_code in [200, 201]
            except Exception as e:
                print(f"[WuzAPI ERROR] Falha de rede ao enviar mensagem para {phone}: {e}")
                return False

    async def send_typing_indicator(self, phone: str, is_typing: bool = True) -> bool:
        """Envia indicador de 'digitando...' para o contato."""
        url = f"{self.base_url}/chat/presence"
        payload = {
            "Phone": phone,
            "State": "composing" if is_typing else "paused",
            "Media": ""
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self.headers, timeout=5.0)
                return response.status_code in [200, 201]
            except Exception as e:
                print(f"[WuzAPI Error] Falha ao enviar typing_indicator para {phone}: {e}")
                return False

    async def download_media(self, url: str, media_key_b64: str, media_type: str = "Image") -> bytes:
        """Faz o download da mídia criptografada da CDN do WhatsApp e a decripta."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=15.0)
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
            decrypted_data = decryptor.update(encrypted_content) + decryptor.finalize()
            
            return decrypted_data
        except Exception as e:
            print(f"[WuzAPI ERROR] Falha ao baixar e decriptar mídia: {e}")
            return None

wuzapi_client = WuzAPIService()
