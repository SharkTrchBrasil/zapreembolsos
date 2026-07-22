import httpx
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

wuzapi_client = WuzAPIService()
