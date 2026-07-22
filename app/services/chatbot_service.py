import logging
from typing import Optional
from google import genai
from google.genai import types
from app.config import settings

logger = logging.getLogger("chatbot_service")

class ChatbotService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.client = None
        self.client_ready = False
        self._setup_client()

    def _setup_client(self):
        if not self.api_key:
            logger.warning("[Chatbot] GEMINI_API_KEY não configurada. IA desabilitada.")
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
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
            logger.error(f"[Chatbot] Erro ao inicializar Gemini: {e}")

    async def generate_response(self, text: str) -> str:
        if not self.client_ready:
            return "Olá. Para registrar uma despesa, envie a foto do cupom fiscal ou recibo."
            
        try:
            # Configurando temperatura e instruções de sistema
            config = types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=0.2,
                max_output_tokens=150
            )
            
            # Usando generate_content_async para não travar o event loop do FastAPI
            response = await self.client.aio.models.generate_content(
                model='gemini-2.0-flash',
                contents=text,
                config=config
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"[Chatbot] Falha ao gerar resposta (Gemini): {e}")
            return "Desculpe, erro técnico. Para solicitar reembolso, envie a foto do recibo."

chatbot_service = ChatbotService()
