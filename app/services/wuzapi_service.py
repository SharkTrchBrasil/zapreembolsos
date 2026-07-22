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
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self.headers, timeout=10.0)
                return response.status_code in [200, 201]
            except Exception as e:
                print(f"[WuzAPI Error] Falha ao enviar mensagem para {phone}: {e}")
                return False

wuzapi_client = WuzAPIService()
