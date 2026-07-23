import logging
import json
import re
from datetime import datetime, date
from typing import Dict, Any, Optional
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger("nlu_service")

class NLUService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.client = None
        if self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"[NLU] Erro ao conectar Gemini NLU: {e}")

        self.groq_client = None
        if settings.GROQ_API_KEY:
            self.groq_client = AsyncOpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1"
            )

        self.mistral_client = None
        if settings.MISTRAL_API_KEY:
            self.mistral_client = AsyncOpenAI(
                api_key=settings.MISTRAL_API_KEY,
                base_url="https://api.mistral.ai/v1"
            )

    async def parse_expense_query(self, user_text: str) -> Dict[str, Any]:
        """
        Analisa texto livre do usuário e extrai:
        - person_name: Nome do funcionário (se citado)
        - start_date / end_date: Datas inicial e final (YYYY-MM-DD)
        - category: Categoria da despesa (ex: COMBUSTIVEL, ALIMENTACAO)
        - group_by: Categoria de agrupamento ("category", "person", "date")
        - action: "QUERY", "RANKING", "PENDING", "EXPORT", "UNKNOWN"
        - confidence: Confiança da extração (0.0 a 1.0)
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        prompt = f"""
Você é um parser NLU de relatórios de reembolso corporativo.
Data de hoje: {today_str}.

Analise a mensagem do usuário e extraia um JSON com a estrutura exata:
{{
  "person_name": string ou null,
  "start_date": "YYYY-MM-DD" ou null,
  "end_date": "YYYY-MM-DD" ou null,
  "category": "COMBUSTIVEL" | "ALIMENTACAO" | "HOSPEDAGEM" | "TRANSPORTE" | "MANUTENCAO" | "OUTROS" ou null,
  "group_by": "category" | "person" | "date" ou null,
  "action": "QUERY" | "RANKING" | "PENDING" | "EXPORT" | "UNKNOWN",
  "filters_count": integer (quantidade de filtros identificados entre pessoa, datas e categoria)
}}

Mensagem do usuário: "{user_text}"
Responda APENAS o JSON puro.
"""
        if self.client:
            try:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
                response = await self.client.aio.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config=config
                )
                if response and response.text:
                    return json.loads(response.text.strip())
            except Exception as e:
                logger.warning(f"[NLU] Falha na extração de NLU via Gemini: {e}")

        # Fallback para Groq
        if self.groq_client:
            try:
                logger.info("[NLU] 🟠 Tentando Groq NLU...")
                response = await self.groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                )
                content = response.choices[0].message.content
                if content:
                    logger.info("[NLU] ✅ Sucesso Groq NLU!")
                    return json.loads(content)
            except Exception as e:
                logger.warning(f"[NLU] ❌ Falha Groq NLU: {e}")

        # Fallback para Mistral
        if self.mistral_client:
            try:
                logger.info("[NLU] 🟠 Tentando Mistral NLU...")
                response = await self.mistral_client.chat.completions.create(
                    model="mistral-small-latest",
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                )
                content = response.choices[0].message.content
                if content:
                    logger.info("[NLU] ✅ Sucesso Mistral NLU!")
                    return json.loads(content)
            except Exception as e:
                logger.warning(f"[NLU] ❌ Falha Mistral NLU: {e}")

        # Fallback local via RegEx se a IA estiver offline ou sem cota
        return self._local_regex_parse(user_text)

    def _local_regex_parse(self, text: str) -> Dict[str, Any]:
        clean = text.lower().strip()
        result = {
            "person_name": None,
            "start_date": None,
            "end_date": None,
            "category": None,
            "group_by": None,
            "action": "QUERY",
            "filters_count": 0
        }
        
        # Categorias
        if "combustivel" in clean or "gasolina" in clean or "posto" in clean:
            result["category"] = "COMBUSTIVEL"
        elif "alimentacao" in clean or "almoço" in clean or "jantar" in clean or "comida" in clean:
            result["category"] = "ALIMENTACAO"

        # Ranking
        if "quem mais gastou" in clean or "ranking" in clean or "top" in clean:
            result["action"] = "RANKING"

        # Pendentes
        if "pendente" in clean or "aprovar" in clean or "aguardando" in clean:
            result["action"] = "PENDING"

        # Exportar
        if "exportar" in clean or "pdf" in clean or "excel" in clean:
            result["action"] = "EXPORT"

        # Contagem de filtros
        filters = 0
        if result["person_name"]: filters += 1
        if result["start_date"]: filters += 1
        if result["category"]: filters += 1
        result["filters_count"] = filters

        return result

nlu_service = NLUService()
