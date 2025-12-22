import os
import sys
import re
from datetime import date
from typing import List, Dict, Any, Union, TypedDict, Annotated
import operator

# Carrega variáveis de ambiente
from dotenv import load_dotenv

load_dotenv()

# --- IMPORTAÇÕES DE UTILS ---
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

    from langgraph.graph import StateGraph, END
    from langgraph.prebuilt import ToolNode
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph.message import add_messages

    print("✓ Bibliotecas LangGraph e OpenAI carregadas com sucesso.")
except ImportError as e:
    print(f"✗ Erro Crítico: {e}")
    sys.exit(1)


# --- 1. DEFINIÇÃO DAS FERRAMENTAS ---

@tool
def descobrir_numero_apolice(termo_busca: str) -> str:
    """
    Use esta ferramenta para buscar dados da apólice pelo PLACA, NOME ou CPF.
    Retorna dados da apólice vigente.
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

    INSTRUÇÃO: Use a apólice com data de início mais recente (Vigente).
    """


@tool
def buscar_clientes_com_vencimento_hoje() -> Union[List[Dict[str, Any]], str]:
    """Busca no banco de dados todas as parcelas de seguro que vencem hoje."""
    return buscar_parcelas_vencendo_hoje()


@tool
def enviar_lembrete_whatsapp(numero_telefone: str, nome_cliente: str, data_vencimento: str, valor_parcela: float,
                             numero_apolice: str, placa: str) -> str:
    """Envia uma mensagem de lembrete de vencimento via WhatsApp (API Oficial)."""
    # ... (Mantendo sua lógica original de envio caso queira usar)
    return "Função de envio de WhatsApp acionada (Simulação)."


@tool
def obter_contato_especialista(intencao_usuario: str) -> str:
    """Retorna o contato do especialista baseado no assunto."""
    intencao = intencao_usuario.lower()
    if "rco" in intencao or "prorroga" in intencao or "ônibus" in intencao:
        return "Para RCO e Prorrogações, fale com a **Leidiane**: (62) 9300-6461."
    elif "sinistro" in intencao or "bati" in intencao or "roubo" in intencao:
        return "Para Sinistros, fale urgente com a **Thuanny**: (62) 9417-6837."
    else:
        return "Para Auto, Vida e outros, fale com a **Mara**: (11) 94516-2002."


@tool
def obter_codigo_de_barras_boleto(numero_apolice: str, mes_referencia: int = 0) -> str:
    """
    Obtém código de barras do boleto.

    PARÂMETROS:
    - numero_apolice: O número da apólice encontrada.
    - mes_referencia: (Opcional) Se o usuário pedir "boleto de dezembro", envie 12. Se for "esse mês", envie o mês atual. Se não especificar, envie 0.
    """
    print(f"🛠️ TOOL: Gerar Boleto {numero_apolice} (Mês ref: {mes_referencia})")

    # Busca a parcela (A lógica no utils já sabe filtrar pelo mês se > 0)
    parcela = buscar_parcela_atual(numero_apolice, mes_referencia)

    if not parcela:
        return f"Não encontrei boletos pendentes para a apólice {numero_apolice} no mês solicitado."

    caminho_pdf = parcela.get('caminho_pdf_boletos')
    data_vencimento_str = parcela.get('data_vencimento_atual') or parcela.get('data_vencimento')
    nome_seguradora = str(parcela.get('seguradora', '')).lower()

    if not caminho_pdf: return "PDF do boleto não encontrado."

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

    # =========================================================================
    # LÓGICA DE NEGOCIAÇÃO (A MUDANÇA ESTÁ AQUI)
    # =========================================================================

    # Cenário: Dívida muito antiga (>25 dias) E o usuário NÃO pediu essa parcela específica
    if dias_atraso > 25 and mes_referencia == 0:
        return (
            f"⚠️ **STATUS: PENDÊNCIA ANTIGA DETECTADA**\n"
            f"Encontrei uma parcela vencida em **{data_vencimento.strftime('%d/%m/%Y')}** ({dias_atraso} dias atrás).\n\n"
            f"🛑 **INSTRUÇÃO PARA O AGENTE (NÃO ENTREGUE O BOLETO AINDA):**\n"
            f"1. Informe ao cliente que consta essa parcela de {data_vencimento.strftime('%B')} em aberto.\n"
            f"2. Pergunte: 'Você já realizou o pagamento desta parcela anterior?'\n"
            f"3. ALERTE que a falta de pagamento pode causar o **CANCELAMENTO** da apólice.\n\n"
            f"--> **SE O CLIENTE DISSER QUE JÁ PAGOU:**\n"
            f"Chame esta ferramenta novamente, mas agora especifique o parâmetro `mes_referencia={hoje.month}` (Mês Atual) para pular a dívida antiga."
        )

    # Se o cliente pediu especificamente a parcela velha (mes_referencia > 0) e ela está velha:
    if dias_atraso > 25 and mes_referencia > 0:
        return (
            f"🚫 **BLOQUEIO DE SEGURANÇA**\n"
            f"Você pediu especificamente o boleto de {data_vencimento.strftime('%m/%Y')}, mas ele venceu há {dias_atraso} dias.\n"
            f"Não posso emitir. Fale com a **LEIDIANE** para verificar reabilitação da apólice."
        )

    # Se passou da tolerância simples (ex: 7 dias), mas não é bloqueio total
    if dias_atraso > tolerancia:
        nome_exibicao = "Essor" if "essor" in nome_seguradora else "Kovr"
        return (
            f"⚠️ **Boleto Vencido há {dias_atraso} dias.**\n"
            f"A {nome_exibicao} só aceita até {tolerancia} dias. Fale com a LEIDIANE para prorrogação."
        )

    # =========================================================================
    # EXTRAÇÃO DO CÓDIGO (Caso esteja tudo ok ou cliente forçou mês atual)
    # =========================================================================

    aviso_cobertura = ""
    if dias_atraso > 0:
        aviso_cobertura = f"\n\n⚠️ **ATENÇÃO:** Você está SEM COBERTURA até a baixa bancária."

    if extrair_codigo_de_barras:
        pdf_bytes = baixar_pdf_bytes(caminho_pdf)
        if pdf_bytes:
            data_fmt = data_vencimento.strftime('%d/%m/%Y')
            codigo = extrair_codigo_de_barras(pdf_bytes, data_fmt)
            if codigo:
                return (
                    f"Aqui está o boleto com vencimento em **{data_fmt}**:{aviso_cobertura}\n\n"
                    f"```text\n{codigo}\n```\n\n"
                    f"📋 _(Clique para copiar)_"
                )

    return f"Boleto válido ({data_vencimento.strftime('%d/%m/%Y')}), mas não consegui ler o código de barras automaticamente. Verifique o PDF."


@tool
def marcar_parcela_como_paga(numero_apolice: str) -> str:
    """Registra a baixa de pagamento de uma parcela no sistema."""
    return "Esta função deve ser usada apenas com confirmação visual do comprovante. (Simulação)"


# --- 2. CONFIGURAÇÃO DO LANGGRAPH ---

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

tools = [
    buscar_clientes_com_vencimento_hoje,
    enviar_lembrete_whatsapp,
    obter_codigo_de_barras_boleto,
    marcar_parcela_como_paga,
    descobrir_numero_apolice,
    obter_contato_especialista
]

llm_with_tools = None
if OPENAI_API_KEY:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    llm_with_tools = llm.bind_tools(tools)
else:
    print("⚠️ ALERTA: OPENAI_API_KEY não encontrada.")


# --- PROMPT DO SISTEMA (PERSONALIDADE ATUALIZADA) ---

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


hoje_str = date.today().strftime("%d/%m/%Y")
mes_atual = date.today().month

system_prompt = f"""Você é o Agente da MOREIRASEG. Hoje é {hoje_str} (Mês {mes_atual}).

### 🛑 PROTOCOLO DE BOLETOS (IMPORTANTE):
1. Primeiro, encontre a apólice usando a placa ou nome.
2. Ao pedir o boleto, use a ferramenta `obter_codigo_de_barras_boleto`.
3. **SE A FERRAMENTA RETORNAR UM ALERTA DE PENDÊNCIA ANTIGA:**
   - Não bloqueie o atendimento.
   - Pergunte ao cliente: "Consta uma pendência de [Data Antiga]. Ela já foi paga?"
   - **SE O CLIENTE DISSER "SIM" (JÁ PAGUEI):**
     - Acredite no cliente.
     - Chame a ferramenta novamente, mas desta vez **force o parâmetro `mes_referencia={mes_atual}`** para pegar o boleto de agora.
   - **SE O CLIENTE DISSER "NÃO":**
     - Aí sim, avise que não pode emitir o novo sem quitar o antigo e mande para a Leidiane.

### 🛑 OUTROS ASSUNTOS:
- "Cotação"/"Novo Seguro" -> Use `obter_contato_especialista` (Mara).
- "Sinistro"/"Batida" -> Use `obter_contato_especialista` (Thuanny).

Seja educado, mas firme quanto aos riscos de cancelamento.
"""


# --- CONSTRUÇÃO DO GRAFO ---

def chatbot_node(state: AgentState):
    return {"messages": [llm_with_tools.invoke([SystemMessage(content=system_prompt)] + state["messages"])]}


tool_node = ToolNode(tools)

workflow = StateGraph(AgentState)
workflow.add_node("agent", chatbot_node)
workflow.add_node("tools", tool_node)
workflow.set_entry_point("agent")


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END


workflow.add_conditional_edges("agent", should_continue, ["tools", END])
workflow.add_edge("tools", "agent")

memory = MemorySaver()
app = workflow.compile(checkpointer=memory)

print("✓ LangGraph Configurado com Lógica de Negociação de Boletos.")


# --- 3. INTERFACE ---

def executar_agente(comando: str) -> str:
    if not llm_with_tools: return "Erro: Agente sem API Key."
    config = {"configurable": {"thread_id": "sessao_dinamica"}}  # Thread fixa para manter contexto da conversa

    try:
        input_message = HumanMessage(content=comando)
        output = app.invoke({"messages": [input_message]}, config=config)
        return output["messages"][-1].content
    except Exception as e:
        return f"Erro técnico: {str(e)}"
