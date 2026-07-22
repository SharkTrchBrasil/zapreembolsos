import logging
from typing import Optional
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger("chatbot_service")

class ChatbotService:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.client = None
        self.client_ready = False
        self._setup_client()

    def _setup_client(self):
        if not self.api_key:
            logger.warning("[Chatbot] OPENAI_API_KEY não configurada. IA desabilitada.")
            return

        try:
            self.client = AsyncOpenAI(api_key=self.api_key)
            
            self.system_instruction = """
Você é o assistente virtual executivo do ZapReembolso.
O usuário enviou uma mensagem de texto com uma dúvida ou saudação.

Diretrizes de Resposta (MUITO IMPORTANTES):
1. Seja estritamente profissional, direto e conciso (máximo 1 ou 2 frases curtas).
2. Não seja "tagarela" nem demonstre emoções exageradas.
3. Se perguntarem como enviar uma despesa, informe brevemente que basta enviar a *foto do cupom fiscal ou recibo* pelo WhatsApp.
4. Se perguntarem sobre relatórios ou aprovações, diga que as funções (RELATORIO, APROVAR) são exclusivas para gestores.
5. Nunca invente dados ou regras adicionais.
"""
            self.client_ready = True
        except Exception as e:
            logger.error(f"[Chatbot] Erro ao inicializar OpenAI: {e}")

    async def generate_response(self, text: str) -> str:
        if not self.client_ready:
            return "Olá. Para registrar uma despesa, envie a foto do cupom fiscal ou recibo."
            
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self.system_instruction},
                    {"role": "user", "content": text}
                ],
                temperature=0.2, # Super baixo para ser direto e sem enrolação
                max_tokens=150
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[Chatbot] Falha ao gerar resposta (OpenAI): {e}")
            return "Desculpe, erro técnico. Para solicitar reembolso, envie a foto do recibo."

chatbot_service = ChatbotService()
