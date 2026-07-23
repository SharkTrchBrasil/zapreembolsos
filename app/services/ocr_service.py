import json
import base64
import asyncio
from datetime import date
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from app.config import settings
import logging

logger = logging.getLogger("ocr_service")

OCR_PROMPT = """
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
""".strip()


class OCRService:
    def __init__(self):
        # --- Clientes Gemini ---
        self.gemini_clients = []
        
        if settings.GEMINI_API_KEY:
            self.gemini_clients.append(genai.Client(api_key=settings.GEMINI_API_KEY))
            
        if hasattr(settings, 'GEMINI_FALLBACK_KEYS') and settings.GEMINI_FALLBACK_KEYS:
            keys = [k.strip() for k in settings.GEMINI_FALLBACK_KEYS.split(",") if k.strip()]
            for k in keys:
                self.gemini_clients.append(genai.Client(api_key=k))
        
        logger.info(f"[OCR] {len(self.gemini_clients)} chave(s) Gemini configurada(s).")

        # --- Cliente Groq (fallback final) ---
        self.groq_client = None
        if settings.GROQ_API_KEY:
            self.groq_client = AsyncOpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1"
            )
            logger.info("[OCR] ✅ Groq configurado como fallback.")
        else:
            logger.warning("[OCR] ⚠️ GROQ_API_KEY não configurada.")

        # --- Cliente Mistral (fallback do Groq) ---
        self.mistral_client = None
        if settings.MISTRAL_API_KEY:
            self.mistral_client = AsyncOpenAI(
                api_key=settings.MISTRAL_API_KEY,
                base_url="https://api.mistral.ai/v1"
            )
            logger.info("[OCR] ✅ Mistral configurado como fallback final.")
        else:
            logger.warning("[OCR] ⚠️ MISTRAL_API_KEY não configurada.")

    async def _try_gemini(self, image_bytes: bytes) -> str | None:
        """Tenta todos os clientes Gemini e modelos. Retorna o conteúdo ou None."""
        models_to_try = ["gemini-2.0-flash", "gemini-2.0-flash-lite"]

        for i, current_client in enumerate(self.gemini_clients, 1):
            for model_name in models_to_try:
                try:
                    logger.info(f"[OCR] Gemini Chave {i}/{len(self.gemini_clients)} | Modelo: {model_name}")
                    response = await current_client.aio.models.generate_content(
                        model=model_name,
                        contents=[
                            OCR_PROMPT,
                            types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')
                        ]
                    )
                    content = response.text
                    if content:
                        logger.info(f"[OCR] ✅ Sucesso Gemini! Chave {i}/{len(self.gemini_clients)} | Modelo: {model_name}")
                        return content
                except Exception as e:
                    logger.warning(f"[OCR] ❌ Gemini Chave {i}/{len(self.gemini_clients)} | {model_name} | {e}")

        return None

    async def _try_groq(self, image_base64: str) -> str | None:
        """Tenta processar com Groq Llama Vision. Retorna o conteúdo ou None."""
        if not self.groq_client:
            return None

        models_to_try = ["llama-3.2-11b-vision-preview", "llama-3.2-90b-vision-preview"]

        for model_name in models_to_try:
            try:
                logger.info(f"[OCR] 🟣 Tentando Groq | Modelo: {model_name}")
                response = await self.groq_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": OCR_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_base64}"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=1024,
                    temperature=0.1
                )
                content = response.choices[0].message.content
                if content:
                    logger.info(f"[OCR] ✅ Sucesso Groq! Modelo: {model_name}")
                    return content
            except Exception as e:
                logger.warning(f"[OCR] ❌ Groq | {model_name} | {e}")

        return None

    async def _try_mistral(self, image_base64: str) -> str | None:
        """Tenta processar com Mistral Pixtral Vision. Retorna o conteúdo ou None."""
        if not self.mistral_client:
            return None

        models_to_try = ["pixtral-12b-2409"]

        for model_name in models_to_try:
            try:
                logger.info(f"[OCR] 🟠 Tentando Mistral | Modelo: {model_name}")
                response = await self.mistral_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": OCR_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_base64}"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=1024,
                    temperature=0.1
                )
                content = response.choices[0].message.content
                if content:
                    logger.info(f"[OCR] ✅ Sucesso Mistral! Modelo: {model_name}")
                    return content
            except Exception as e:
                logger.warning(f"[OCR] ❌ Mistral | {model_name} | {e}")

        return None

    def _parse_response(self, content: str) -> dict:
        """Limpa e parseia o JSON retornado pela IA."""
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

    async def extract_receipt_from_image_base64(self, image_base64: str) -> dict:
        """Usa IA Vision para ler cupons fiscais, recibos e notas fiscais."""
        if not self.gemini_clients and not self.groq_client and not self.mistral_client:
            logger.warning("Nenhuma chave de API configurada. Usando fallback de teste.")
            return {
                "merchant_name": "Posto Shell Marginal (Teste)",
                "merchant_cnpj": "12.345.678/0001-90",
                "amount": 150.00,
                "expense_date": date.today().strftime("%Y-%m-%d"),
                "category": "COMBUSTIVEL"
            }

        image_bytes = base64.b64decode(image_base64)

        # 1) Tentar Gemini (todas as chaves)
        content = await self._try_gemini(image_bytes)

        # 2) Se Gemini falhou, tentar Groq
        if not content:
            logger.info("[OCR] 🔄 Gemini esgotado. Tentando Groq...")
            content = await self._try_groq(image_base64)

        # 3) Se Groq falhou, tentar Mistral
        if not content:
            logger.info("[OCR] 🔄 Groq falhou. Tentando Mistral...")
            content = await self._try_mistral(image_base64)

        # 4) Se todos falharam, esperar e tentar Gemini de novo
        if not content:
            logger.warning("[OCR] ⏳ Todos falharam. Aguardando 35s para retry Gemini...")
            await asyncio.sleep(35)
            content = await self._try_gemini(image_bytes)

        if not content:
            raise ValueError("Não foi possível processar a imagem: Gemini, Groq e Mistral esgotaram a cota.")

        return self._parse_response(content)


ocr_service = OCRService()
