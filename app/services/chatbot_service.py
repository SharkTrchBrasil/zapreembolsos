import logging
import json
import os
from typing import Optional
from google import genai
from google.genai import types
from app.config import settings

logger = logging.getLogger("chatbot_service")

TEMPLATE_FILE = os.path.join(os.path.dirname(__file__), "..", "templates", "bot_responses.json")

class ChatbotService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.client = None
        self.client_ready = False
        self.templates_data = {"templates": [], "default_fallback": "Olá! Para registrar uma despesa, envie a foto do seu cupom fiscal ou recibo."}
        self._load_templates()
        self._setup_client()

    def _load_templates(self):
        """Carrega templates locais em JSON para fallback inteligente quando a IA falhar ou esgotar a cota."""
        try:
            if os.path.exists(TEMPLATE_FILE):
                with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                    self.templates_data = json.load(f)
                logger.info(f"[Chatbot] {len(self.templates_data.get('templates', []))} templates JSON carregados com sucesso.")
            else:
                logger.warning(f"[Chatbot] Arquivo de templates não encontrado em {TEMPLATE_FILE}")
        except Exception as e:
            logger.error(f"[Chatbot] Erro ao carregar templates JSON: {e}")

    def _setup_client(self):
        if not self.api_key:
            logger.warning("[Chatbot] GEMINI_API_KEY não configurada. Usando motor de templates locais.")
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

    def _get_template_response(self, text: str, user_role: str = None) -> str:
        """Busca a melhor resposta em template JSON por correspondência de palavras-chave."""
        clean_text = text.lower().strip()
        for t in self.templates_data.get("templates", []):
            for kw in t.get("keywords", []):
                if kw in clean_text:
                    return t.get("response")
                    
        if user_role == "ADMIN":
            return "Olá, Gestor! Para ver o painel, digite RELATORIO. Para gerenciar despesas use APROVAR ou REJEITAR."
        return self.templates_data.get("default_fallback", "Olá! Para registrar uma despesa, envie a foto do seu cupom fiscal ou recibo.")

    async def generate_response(self, text: str, user_role: str = None) -> str:
        if not self.client_ready:
            return self._get_template_response(text, user_role)

        # Modelos para tentar caso ocorra 429 Rate/Quota Limit
        models_to_try = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.0-flash-lite']
        
        # Ajusta a instrução baseada na role do usuário
        role_instruction = ""
        if user_role == "ADMIN":
            role_instruction = "O usuário é um GESTOR/ADMIN. Não peça para ele enviar fotos de recibos (embora ele possa). Diga que ele pode gerenciar aprovações e ver relatórios. (Use DASHBOARD, RELATORIO, APROVAR)."
        else:
            role_instruction = "O usuário é um FUNCIONÁRIO. Diga que para solicitar reembolso, basta enviar a FOTO do cupom fiscal ou recibo."

        dynamic_instruction = self.system_instruction + "\n" + role_instruction
        
        config = types.GenerateContentConfig(
            system_instruction=dynamic_instruction,
            temperature=0.2,
            max_output_tokens=150
        )

        for model_name in models_to_try:
            try:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=text,
                    config=config
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"[Chatbot] Falha no modelo {model_name}: {e}. Tentando fallback...")

        # Se todos os modelos de IA falharem (ex: cota esgotada), usa o Template JSON
        logger.info("[Chatbot] Utilizando resposta via Template JSON após esgotamento de cota da IA.")
        return self._get_template_response(text, user_role)

chatbot_service = ChatbotService()
