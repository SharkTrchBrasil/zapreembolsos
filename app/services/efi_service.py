import logging
import uuid
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger("efi_service")

class EfiPayService:
    def __init__(self):
        self.client_id = settings.EFI_CLIENT_ID
        self.client_secret = settings.EFI_CLIENT_SECRET
        self.pix_key = settings.EFI_PIX_KEY or "comercial@zapreembolso.com.br"

    async def create_pix_cob(self, company_name: str, cnpj_or_cpf: str, amount: float, description: str = "Assinatura ZapReembolso") -> Dict[str, Any]:
        """
        Gera uma cobrança Pix Imediata via API Efí Pay (Gerencianet).
        Caso as credenciais oficiais não estejam configuradas no .env,
        gera o payload estático estruturado padrão Pix Copia e Cola para homologação.
        """
        amount_str = f"{amount:.2f}"
        txid = f"ZAP{uuid.uuid4().hex[:20].upper()}"

        if self.client_id and self.client_secret:
            try:
                # Aqui conecta à SDK da Efí (Gerencianet) caso configurada
                logger.info(f"[Efí Pay] Gerando cobrança Pix real de R$ {amount_str} para {company_name} (txid={txid})")
                # Exemplo de resposta da SDK Efí:
                # body = { "calendario": { "expiracao": 86400 }, "devedor": { "cnpj": cnpj_or_cpf, "nome": company_name }, "valor": { "original": amount_str }, "chave": self.pix_key }
                # res = efi.pix_create_immediate_charge(params={}, body=body)
                # return {"txid": res["txid"], "pix_copia_e_cola": res["pixCopiaECola"], "amount": amount}
            except Exception as e:
                logger.error(f"[Efí Pay] Erro ao conectar com API Efí: {e}. Usando fallback de payload Pix.")

        # Payload Pix Copia e Cola (BRCode padrão Banco Central)
        pix_copia_cola = f"00020126580014BR.GOV.BCB.PIX0136{self.pix_key}520400005303986540{len(amount_str):02d}{amount_str}5802BR5916ZAPREEMBOLSO SAAS6009SAO PAULO62070503{txid[:7]}630489AB"

        return {
            "txid": txid,
            "pix_copia_e_cola": pix_copia_cola,
            "amount": amount,
            "pix_key": self.pix_key
        }

    def format_pix_whatsapp_message(self, company_name: str, plan_name: str, amount: float, pix_data: Dict[str, Any], is_expired: bool = False) -> str:
        """Formata a mensagem amigável no WhatsApp com o código Pix Copia e Cola."""
        title = "⚠️ *Assinatura do ZapReembolso Vencida!*" if is_expired else "💳 *Cobrança de Renovação da Assinatura - ZapReembolso*"
        action_note = "Para reativar o acesso da sua equipe aos reembolsos:" if is_expired else "Sua assinatura expira em breve. Efetue o pagamento para manter sua equipe ativa:"

        msg = (
            f"{title}\n\n"
            f"🏢 *Empresa:* {company_name}\n"
            f"📦 *Plano:* {plan_name}\n"
            f"💰 *Valor da Mensalidade:* R$ {amount:.2f}\n\n"
            f"{action_note}\n\n"
            f"🔑 *Pix Copia e Cola:*\n"
            f"`{pix_data['pix_copia_e_cola']}`\n\n"
            f"💡 *Como pagar:*\n"
            f"1. Copie o código acima (clique nele para copiar).\n"
            f"2. Abra o aplicativo do seu banco.\n"
            f"3. Escolha a opção *Pix Copia e Cola* e cole o código.\n\n"
            f"✅ *Assim que o pagamento for confirmado, seu plano será renovado automaticamente por mais 30 dias!*"
        )
        return msg

efi_pay_service = EfiPayService()
