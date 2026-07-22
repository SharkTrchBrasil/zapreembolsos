# 🚀 ZapReembolso - Gestão Inteligente de Despesas e Comprovantes via WhatsApp

O **ZapReembolso** é uma plataforma SaaS B2B operando 100% via **WhatsApp**, projetada para pequenas e médias empresas (PMEs) eliminarem a burocracia de papéis, cupons fiscais rasgados e relatórios manuais de reembolso em planilhas.

Sem necessidade de os funcionários baixarem aplicativos pesados, eles simplesmente enviam uma foto do cupom fiscal (combustível, almoço, hospedagem, transporte) no WhatsApp da empresa. A inteligência artificial lê os dados da nota, categoriza a despesa e notifica o gestor/financeiro instantaneamente para aprovação.

---

## 📌 Proposta de Valor & Posicionamento Estratégico

### O Problema do Mercado Atual
* **Perda de Tempo & Papéis Rasgados:** Funcionários de rua (vendedores, motoristas, técnicos) perdem recibos ou entregam papéis amassados no fim do mês.
* **Complexidade dos Softwares Corporativos:** Ferramentas tradicionais de reembolso (como VExpenses, Flash, SAP Concur) exigem download de aplicativo, senhas complexas e contratos caros (acima de R$ 1.000/mês).
* **Demora no Fechamento Contábil:** O financeiro perde horas digitando valores de notas em planilhas para calcular o reembolso de cada funcionário.

### A Nossa Solução ("Zero Aplicativo, 100% WhatsApp")
* **Zero Fricção para o Funcionário:** Mandou a foto do recibo no WhatsApp, tá registrado.
* **Leitura Inteligente por IA (GPT-4o-mini Vision):** Extrai automaticamente o nome do estabelecimento, CNPJ, valor total, data e categoria da despesa em segundos.
* **Notificação em Tempo Real para o Gestor:** O gestor da empresa recebe um alerta no WhatsApp com os dados da despesa e pode aprovar com 1 toque.
* **Relatório Consolidado:** Comando `/relatorio` gera o resumo mensal pronto por funcionário e por categoria (Combustível, Alimentação, etc.).

---

## 💎 Planos & Monetização B2B

* 🆓 **Degustação (7 Dias Grátis):** Até 10 comprovantes para teste da empresa.
* ⭐ **Plano PME Start (R$ 97,00/mês):** Até 10 funcionários ativos e comprovantes ilimitados.
* 🚀 **Plano PME Pro (R$ 197,00/mês):** Até 30 funcionários ativos, múltiplos gestores e suporte prioritário.

---

## 🛠️ Arquitetura Técnica

```
[ WhatsApp do Funcionário / Gestor ]
        │
        ▼ (Webhook HTTP POST)
[ WuzAPI (Serviço de WhatsApp em Go/Node) ]
        │
        ▼
[ FastAPI Backend (Python 3.11+) ]
        │
        ├──► [ OpenAI GPT-4o-mini Vision ] (OCR de Cupons Fiscais, Recibos e NFe)
        ├──► [ SQLite / PostgreSQL ] (Empresas, Funcionários e Despesas)
        └──► [ APScheduler ] (Cron de Resumos Diários/Semanais para Gestores)
```

### Estrutura do Projeto
```
zapfaturas/ (ZapReembolso)
├── app/
│   ├── config.py             # Configurações globais e variáveis de ambiente
│   ├── database.py           # Conexão assíncrona SQLAlchemy (AsyncSession)
│   ├── main.py               # Instância FastAPI, Lifespan e Scheduler
│   ├── models.py             # Schemas SQLAlchemy (Company, User, Expense)
│   ├── routes/
│   │   └── webhook.py        # Webhook de mensagens e lógica de comandos
│   └── services/
│       ├── ocr_service.py    # Extração de recibos via OpenAI GPT-4o Vision
│       ├── wuzapi_service.py # Envio de mensagens e mídias via WuzAPI
│       └── notification_service.py # Agendador de resumos para os gestores
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🚀 Como Executar o Projeto Localmente

### 1. Pré-requisitos
* Python 3.10 ou superior instalado.
* Instância do **WuzAPI** ou gateway WhatsApp acessível.
* Chave de API da OpenAI (`OPENAI_API_KEY`).

### 2. Instalação
```bash
# Entrar no diretório
cd C:\Users\Sharkcode\Documents\zapfaturas

# Criar ambiente virtual
python -m venv venv

# Ativar ambiente virtual (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Instalar dependências
pip install -r requirements.txt
```

### 3. Configuração de Variáveis de Ambiente
Crie um arquivo `.env` baseado no `.env.example`:
```env
PROJECT_NAME="ZapReembolso API"
DEBUG=True
DATABASE_URL="sqlite+aiosqlite:///./zapreembolso.db"

# Credenciais do WuzAPI
WUZAPI_BASE_URL="http://localhost:8080"
WUZAPI_USER_TOKEN="seu_token_wuzapi_aqui"

# Chave da OpenAI para o OCR de Recibos
OPENAI_API_KEY="sk-proj-sua_chave_openai_aqui"
```

### 4. Executando o Servidor
```bash
uvicorn app.main:app --reload --port 8000
```
O servidor estará disponível em `http://localhost:8000`.

---

## 🔗 Integração com Webhook

Cadastre o Webhook no painel do **WuzAPI** apontando para:
`POST http://seu-servidor:8000/webhook/wuzapi`

---

## 💬 Fluxo de Mensagens no WhatsApp

### 1. Funcionário envia a foto da Nota Fiscal / Recibo:
> 📸 *[Envio da foto do cupom fiscal do posto de gasolina]*
> 
> 🤖 **ZapReembolso:**
> 🔍 *Lendo seu recibo com IA... Aguarde alguns segundos!*
> 
> ✅ **Despesa Registrada com Sucesso!**
> 🏢 **Local:** Posto Shell Marginal
> 💰 **Valor:** R$ 185,50
> 📅 **Data:** 21/07/2026
> 🏷️ **Categoria:** Combustível
> 📋 **Status:** Pendente de aprovação pelo gestor.

### 2. O Gestor da Empresa recebe a notificação instantânea:
> 🤖 **ZapReembolso [Aviso Gestor]:**
> 📥 **Nova Despesa para Aprovação!**
> 👤 **Funcionário:** João Silva
> 🏢 **Local:** Posto Shell Marginal (R$ 185,50 - Combustível)
> 
> Responda *APROVAR [ID]* para aprovar ou *RELATORIO* para ver o consolidado.

### 3. Comando de Relatório (`RELATORIO`):
> 📊 **Resumo de Despesas - Construtora Alfa**
> 
> 💰 **Total do Mês:** R$ 1.420,00 (8 despesas)
> ⛽ **Combustível:** R$ 850,00
> 🍽️ **Alimentação:** R$ 570,00
> 
> 🔴 **Pendentes de Aprovação:** 2 despesas (R$ 310,00)
