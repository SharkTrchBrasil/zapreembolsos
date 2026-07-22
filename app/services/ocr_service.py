import json
import base64
from datetime import date
from google import genai
from google.genai import types
from app.config import settings

class OCRService:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None

    async def extract_receipt_from_image_base64(self, image_base64: str) -> dict:
        """Usa Gemini 2.5 Flash Vision para ler cupons fiscais, recibos e notas fiscais."""
        if not self.client:
            # Fallback para testes se GEMINI_API_KEY não estiver preenchida
            print("[OCR] GEMINI_API_KEY não configurada. Usando fallback.")
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
        models_to_try = ["gemini-2.0-flash", "gemini-flash-latest", "gemini-3.5-flash"]
        content = None
        last_error = None

        for model_name in models_to_try:
            try:
                print(f"[OCR] Tentando extração com modelo {model_name}...")
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')
                    ]
                )
                content = response.text
                if content:
                    print(f"[OCR] Sucesso com o modelo {model_name}!")
                    break
            except Exception as e:
                print(f"[OCR Warning] Falha no modelo {model_name}: {e}")
                last_error = e

        if not content:
            raise ValueError(f"Não foi possível processar a imagem com IA: {last_error}")

        if not content:
            raise ValueError("Resposta vazia da IA.")
            
        content = content.strip()
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[OCR Error] JSON inválido retornado pela IA: {e}")
            raise ValueError("Não foi possível extrair os dados da imagem (JSON inválido).")

ocr_service = OCRService()
