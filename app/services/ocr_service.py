import json
from datetime import date
from openai import AsyncOpenAI
from app.config import settings

class OCRService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None

    async def extract_receipt_from_image_base64(self, image_base64: str) -> dict:
        """Usa OpenAI GPT-4o-mini Vision para ler cupons fiscais, recibos e notas fiscais."""
        if not self.client:
            # Fallback para testes se OPENAI_API_KEY não estiver preenchida no .env
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

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                        }
                    ]
                }
            ],
            max_tokens=350
        )

        content = response.choices[0].message.content
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
