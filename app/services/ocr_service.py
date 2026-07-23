import json
import base64
import asyncio
from datetime import date
from google import genai
from google.genai import types
from app.config import settings
import logging

logger = logging.getLogger("ocr_service")

class OCRService:
    def __init__(self):
        self.clients = []
        
        # Chave principal
        if settings.GEMINI_API_KEY:
            self.clients.append(genai.Client(api_key=settings.GEMINI_API_KEY))
            
        # Fallbacks configurados via .env (separados por vírgula)
        if hasattr(settings, 'GEMINI_FALLBACK_KEYS') and settings.GEMINI_FALLBACK_KEYS:
            keys = [k.strip() for k in settings.GEMINI_FALLBACK_KEYS.split(",") if k.strip()]
            for k in keys:
                self.clients.append(genai.Client(api_key=k))
        
        logger.info(f"[OCR] {len(self.clients)} chave(s) de API Gemini configurada(s).")

    async def _try_all_clients(self, image_bytes: bytes, prompt: str) -> str | None:
        """Tenta todos os clientes e modelos. Retorna o conteúdo ou None."""
        models_to_try = ["gemini-2.0-flash", "gemini-2.0-flash-lite"]
        last_error = None

        for i, current_client in enumerate(self.clients, 1):
            for model_name in models_to_try:
                try:
                    logger.info(f"[OCR] Chave {i}/{len(self.clients)} | Modelo: {model_name}")
                    response = await current_client.aio.models.generate_content(
                        model=model_name,
                        contents=[
                            prompt,
                            types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')
                        ]
                    )
                    content = response.text
                    if content:
                        logger.info(f"[OCR] ✅ Sucesso! Chave {i}/{len(self.clients)} | Modelo: {model_name}")
                        return content
                except Exception as e:
                    logger.warning(f"[OCR] ❌ Chave {i}/{len(self.clients)} | Modelo: {model_name} | Erro: {e}")
                    last_error = e

        return None

    async def extract_receipt_from_image_base64(self, image_base64: str) -> dict:
        """Usa Gemini Vision para ler cupons fiscais, recibos e notas fiscais."""
        if not self.clients:
            logger.warning("Nenhuma chave de API configurada. Usando fallback de teste.")
            return {
                "merchant_name": "Posto Shell Marginal (Teste)",
                "merchant_cnpj": "12.345.678/0001-90",
                "amount": 150.00,
                "expense_date": date.today().strftime("%Y-%m-%d"),
                "category": "COMBUSTIVEL"
            }

        prompt = """
        Você é um leitor especialista de cupons fiscais, notas fiscais (NFe/NFCe) e recibos comerciais brasileiros.
        Analise a imagem enviada e extraia as informações no seguinte formato JSON estrito:
        {
          "merchant_name": "Nome da empresa/posto/restaurante (ex: Posto Shell, Restaurante Silva)",
          "merchant_cnpj": "CNPJ com formatação ou null se não houver",
          "amount": float com o valor total pago (ex: 185.50),
          "expense_date": "YYYY-MM-DD" com a data da compra (se não legível, use a data de hoje),
          "category": "Uma destas categorias exatas: COMBUSTIVEL, ALIMENTACAO, HOSPEDAGEM, TRANSPORTE, MANUTENCAO, OUTROS"
        }
        Retorne APENAS o JSON estrito, sem explicações adicionais ou marcações markdown.
        """

        image_bytes = base64.b64decode(image_base64)

        # Primeira tentativa com todos os clientes
        content = await self._try_all_clients(image_bytes, prompt)

        # Se todas falharam com rate limit, espera e tenta mais uma vez
        if not content:
            logger.warning("[OCR] ⏳ Todas as chaves falharam. Aguardando 35s para retry...")
            await asyncio.sleep(35)
            logger.info("[OCR] 🔄 Retentando após aguardar cooldown...")
            content = await self._try_all_clients(image_bytes, prompt)

        if not content:
            raise ValueError("Não foi possível processar a imagem com IA: todas as chaves esgotaram a cota.")
            
        content = content.strip()
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON inválido retornado pela IA: {e}")
            raise ValueError("Não foi possível extrair os dados da imagem (JSON inválido).")

ocr_service = OCRService()

