import os
import sys
import re
from datetime import date
from typing import List, Dict, Any, Union, TypedDict, Annotated
import operator

# Carrega variáveis de ambiente
from dotenv import load_dotenv

load_dotenv()

# --- IMPORTAÇÕES DE UTILS (MANTIDAS DO SEU PROJETO) ---
try:
    from utils.supabase_client import (
        buscar_parcelas_vencendo_hoje,
        atualizar_status_pagamento,
        buscar_parcela_atual,
        baixar_pdf_bytes,
        buscar_apolice_inteligente
    )
except ImportError as e:
    print(f"✗ Erro ao importar utils.supabase_client: {e}")
    sys.exit(1)

# Tenta importar o leitor de PDF
try:
    from utils.pdf_parser import extrair_codigo_de_barras
except ImportError:
    extrair_codigo_de_barras = None

import requests

# --- IMPORTAÇÕES LANGCHAIN E LANGGRAPH ---
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage
    from langchain_core.tools import tool
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    # LangGraph Core
    from langgraph.graph import StateGraph, END
    from langgraph.prebuilt import ToolNode
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph.message import add_messages

    print("✓ Bibliotecas LangGraph e OpenAI carregadas com sucesso.")
except ImportError as e:
    print(f"✗ Erro Crítico: {e}")
    print("Por favor, instale: pip install langgraph langchain-openai langchain-core")
    sys.exit(1)


# --- 1. DEFINIÇÃO DAS FERRAMENTAS (SUA LÓGICA DE NEGÓCIO) ---

@tool
def descobrir_numero_apolice(termo_busca: str) -> str:
    """
    Use esta ferramenta APENAS para buscar BOLETOS ou CONSULTAS DE APÓLICE JÁ EXISTENTES.
    ⛔ PROIBIDO USAR PARA COTAÇÕES OU VENDAS NOVAS.
    Retorna apenas a apólice VIGENTE mais recente.
    """
    print(f"🛠️ TOOL: Buscar Apólice Blindada para: {termo_busca}")

    resultados = buscar_apolice_inteligente(termo_busca)

    if not resultados:
        return "Não encontrei nenhuma apólice com esse dado."

    if isinstance(resultados, str):
        return resultados

    hoje = date.today()

    return f"""
    RESULTADO DA BUSCA:
    {resultados}

    ---
    INSTRUÇÃO OBRIGATÓRIA PARA O AGENTE:
    Se houver mais de uma apólice na lista acima:
    1. Compare as datas de vigência.
    2. IGNORE qualquer apólice com 'Fim de Vigência' anterior a {hoje}.
    3. USE APENAS o número da apólice que está ativa agora.
    """


@tool
def buscar_clientes_com_vencimento_hoje() -> Union[List[Dict[str, Any]], str]:
    """
    Busca no banco de dados todas as parcelas de seguro que vencem hoje e estão pendentes.
    """
    print("🛠️ TOOL: Buscar Vencimentos Hoje")
    return buscar_parcelas_vencendo_hoje()


@tool
def enviar_lembrete_whatsapp(numero_telefone: str, nome_cliente: str, data_vencimento: str, valor_parcela: float,
                             numero_apolice: str, placa: str) -> str:
    """
    Envia uma mensagem de lembrete de vencimento via WhatsApp (API Oficial da Meta).
    """
    print(f"🛠️ TOOL: Enviar WhatsApp para {nome_cliente}")

    TOKEN = os.environ.get("META_ACCESS_TOKEN")
    PHONE_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

    if os.environ.get("MOCK_WHATSAPP") == "True":
        return f"MOCK: Mensagem simulada enviada com sucesso para {nome_cliente}."

    if not TOKEN or not PHONE_ID:
        return "Erro: Credenciais da API do WhatsApp não configuradas."

    numero_limpo = re.sub(r'\D', '', numero_telefone)
    url = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    valor_formatado = f"{valor_parcela:,.2f}".replace('.', '#').replace(',', '.').replace('#', ',')
    template_name = os.environ.get("META_TEMPLATE_NAME", "hello_world")

    if template_name == "hello_world":
        payload = {
            "messaging_product": "whatsapp",
            "to": numero_limpo,
            "type": "template",
            "template": {"name": "hello_world", "language": {"code": "en_US"}}
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": numero_limpo,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "pt_BR"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": nome_cliente},
                            {"type": "text", "text": data_vencimento},
                            {"type": "text", "text": numero_apolice},
                            {"type": "text", "text": placa},
                            {"type": "text", "text": valor_formatado}
                        ]
                    }
                ]
            }
        }

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return f"Mensagem enviada com sucesso para {nome_cliente}."
        else:
            return f"Erro ao enviar: {response.json().get('error', {}).get('message', 'Erro desconhecido')}"
    except Exception as e:
        return f"Exceção ao enviar mensagem: {e}"


@tool
def obter_contato_especialista(intencao_usuario: str) -> str:
    """Retorna o contato do especialista baseado no assunto (RCO, Sinistro, Auto)."""
    intencao = intencao_usuario.lower()
    if "rco" in intencao or "prorroga" in intencao or "ônibus" in intencao:
        return "Para RCO e Prorrogações, fale com a **Leidiane**: (62) 9300-6461."
    elif "sinistro" in intencao or "bati" in intencao or "roubo" in intencao:
        return "Para Sinistros, fale urgente com a **Thuanny**: (62) 9417-6837."
    else:
        return "Para Auto, Vida e outros, fale com a **Mara**: (11) 94516-2002."


# ... (No meio do arquivo agent_logic.py) ...

@tool
def obter_codigo_de_barras_boleto(numero_apolice: str, mes_referencia: int = 0) -> str:
    """
    Obtém código de barras do boleto.
    IMPORTANTE:
    - Se o usuário pedir um mês específico (ex: "boleto de dezembro"), envie 'mes_referencia=12'.
    - Se não especificar, envie 0 (o sistema pegará o mais antigo pendente).
    """
    print(f"🛠️ TOOL: Gerar Boleto {numero_apolice} (Mês: {mes_referencia})")

    # AQUI ESTÁ A MÁGICA: Passamos o mês para o supabase filter
    parcela = buscar_parcela_atual(numero_apolice, mes_referencia)

    if not parcela:
        return f"Não encontrei parcelas pendentes para a apólice {numero_apolice} (Mês ref: {mes_referencia or 'Automático'})."

    caminho_pdf = parcela.get('caminho_pdf_boletos')
    data_vencimento_str = parcela.get('data_vencimento_atual') or parcela.get('data_vencimento')
    nome_seguradora = str(parcela.get('seguradora', '')).lower()

    if not caminho_pdf: return "PDF do boleto não encontrado."

    # Lógica de Datas
    hoje = date.today()
    if isinstance(data_vencimento_str, str):
        data_vencimento = date.fromisoformat(data_vencimento_str)
    else:
        data_vencimento = data_vencimento_str

    dias_atraso = (hoje - data_vencimento).days

    # Regras de Tolerância
    tolerancia = 0
    if "essor" in nome_seguradora:
        tolerancia = 10
    elif "kovr" in nome_seguradora:
        tolerancia = 5

    # --- TRAVA DE SEGURANÇA INTELIGENTE ---
    # Só bloqueia se for muito antigo E se o usuário NÃO pediu esse mês especificamente.
    # Se o usuário pediu "Mês 12" e o mês 12 venceu há 26 dias, ainda avisamos,
    # mas se for a parcela errada (velha), a lógica do buscar_parcela_atual já resolveu.
    if dias_atraso > 25:
        return (
            f"🚫 **BLOQUEIO DE SEGURANÇA**\n"
            f"A fatura de vencimento **{data_vencimento.strftime('%d/%m/%Y')}** venceu há {dias_atraso} dias.\n"
            f"⚠️ **NÃO PAGUE.** Risco de cancelamento. Fale com a LEIDIANE."
        )

    # ... (Resto da função continua igual: gera código de barras etc) ...

    # ... COPIE O RESTANTE DA LÓGICA DE EXTRAIR CÓDIGO DA RESPOSTA ANTERIOR AQUI ...
    if extrair_codigo_de_barras:
        pdf_bytes = baixar_pdf_bytes(caminho_pdf)
        if pdf_bytes:
            data_fmt = data_vencimento.strftime('%d/%m/%Y')
            codigo = extrair_codigo_de_barras(pdf_bytes, data_fmt)
            if codigo:
                aviso_cobertura = "\n\n⚠️ **ATENÇÃO:** Sem cobertura até baixa." if dias_atraso > 0 else ""
                return (
                    f"Aqui está o boleto de vencimento **{data_fmt}**:{aviso_cobertura}\n\n"
                    f"```text\n{codigo}\n```\n\n"
                    f"📋 _(Clique para copiar)_"
                )

    return f"Boleto válido (Venc: {data_vencimento.strftime('%d/%m/%Y')}), mas não li o código de barras."

@tool
def marcar_parcela_como_paga(numero_apolice: str) -> str:
    """Registra a baixa de pagamento de uma parcela no sistema."""
    print(f"🛠️ TOOL: Baixa de pagamento Apólice {numero_apolice}")
    parcela = buscar_parcela_atual(numero_apolice)
    if not parcela: return f"Apólice {numero_apolice} não encontrada."

    data_vencimento = parcela.get('data_vencimento_atual')
    if isinstance(data_vencimento, str):
        data_vencimento = date.fromisoformat(data_vencimento)

    success = atualizar_status_pagamento(numero_apolice, data_vencimento)
    return "Baixa registrada com sucesso." if success else "Erro ao registrar baixa."


# --- 2. CONFIGURAÇÃO DO LANGGRAPH ---

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Lista de ferramentas disponíveis para o agente
tools = [
    buscar_clientes_com_vencimento_hoje,
    enviar_lembrete_whatsapp,
    obter_codigo_de_barras_boleto,
    marcar_parcela_como_paga,
    descobrir_numero_apolice,
    obter_contato_especialista
]

# Inicialização do LLM
llm_with_tools = None
if OPENAI_API_KEY:
    # Usando GPT-4o-mini com temperatura 0 para máxima precisão
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    llm_with_tools = llm.bind_tools(tools)
else:
    print("⚠️ ALERTA: OPENAI_API_KEY não encontrada.")


# --- DEFINIÇÃO DO ESTADO E PROMPT ---

class AgentState(TypedDict):
    # 'add_messages' é crucial: ele garante que o histórico seja acumulado e não sobrescrito
    messages: Annotated[list, add_messages]


system_prompt = """Você é o Agente da MOREIRASEG.

### 🛑 PROTOCOLO DE URGÊNCIA (LEIA ANTES DE TUDO):
1. **"COTAÇÃO", "NOVO SEGURO", "COMPRAR"?**
   - **AÇÃO:** Use `obter_contato_especialista`. NÃO peça dados.

2. **"BATIDA", "SINISTRO"?**
   - **AÇÃO:** Use `obter_contato_especialista` (Thuanny).

3. **APENAS SE FOR BOLETO/COBRANÇA:**
   - Peça a placa/CPF e use `descobrir_numero_apolice`.

### 🧠 INTELIGÊNCIA DE APÓLICES:
- Ao buscar, ignore apólices ANTIGAS/VENCIDAS. Foque apenas na VIGENTE.
- Se o usuário pedir boleto, primeiro ache a apólice, depois use `obter_codigo_de_barras_boleto`.

### 💰 REGRAS:
- Essor: Boleto até +10 dias.
- Kovr: Boleto até +5 dias.
- Passou do prazo? Mande para LEIDIANE.

Seja breve e direto.
"""


# --- NÓS DO GRAFO ---

def chatbot_node(state: AgentState):
    """Nó de decisão do Agente"""
    return {"messages": [llm_with_tools.invoke([SystemMessage(content=system_prompt)] + state["messages"])]}


# Nó de Ferramentas (Pré-construído pelo LangGraph)
tool_node = ToolNode(tools)

# --- CONSTRUÇÃO DO GRAFO ---

workflow = StateGraph(AgentState)

# Adiciona Nós
workflow.add_node("agent", chatbot_node)
workflow.add_node("tools", tool_node)

# Define Entrada
workflow.set_entry_point("agent")


# Lógica Condicional (Router)
def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    # Se a IA decidiu chamar uma ferramenta, vá para 'tools'
    if last_message.tool_calls:
        return "tools"
    # Se não, termine
    return END


# Define Arestas
workflow.add_conditional_edges("agent", should_continue, ["tools", END])
workflow.add_edge("tools", "agent")  # <--- O LOOP DE RACIOCÍNIO (Volta para o agente após usar ferramenta)

# Compilação com Memória
# Checkpointer em memória (volátil ao reiniciar o app, persistente durante a sessão)
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)

print("✓ LangGraph Configurado e Compilado.")


# --- 3. FUNÇÃO PRINCIPAL (INTERFACE) ---

def executar_agente(comando: str) -> str:
    """
    Função chamada pelo front-end (Streamlit) para processar mensagens.
    """
    if not llm_with_tools:
        return "Erro: Agente não configurado (Falta API Key)."

    # Configuração de Sessão (Thread ID)
    # Em produção, você pode passar um ID de usuário real aqui para persistir conversas longas
    config = {"configurable": {"thread_id": "sessao_unica_usuario"}}

    print(f"\n🤖 LangGraph Input: '{comando}'")

    try:
        # Invoca o grafo
        # O estado inicial é apenas a nova mensagem do usuário
        input_message = HumanMessage(content=comando)

        output = app.invoke({"messages": [input_message]}, config=config)

        # Pega a última mensagem gerada pelo modelo (que é texto, não tool call)
        ultima_resposta = output["messages"][-1].content

        return ultima_resposta

    except Exception as e:
        erro_msg = f"Erro crítico no agente: {str(e)}"
        print(erro_msg)
        return "Desculpe, ocorreu um erro técnico ao processar sua solicitação."


# --- TESTE LOCAL ---
if __name__ == "__main__":
    print("--- INICIANDO TESTE LOCAL ---")
    print(executar_agente("Olá, preciso de uma cotação"))
