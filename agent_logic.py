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


# --- 1. DEFINIÇÃO DAS FERRAMENTAS (COM DOCSTRINGS CORRIGIDAS) ---

@tool
def descobrir_numero_apolice(termo_busca: str) -> str:
    """
    Busca dados da apólice vigente pelo PLACA, NOME ou CPF.

    Args:
        termo_busca: A placa (ex: ABC-1234) ou nome do cliente.
    """
    # print(f"🛠️ TOOL: Buscar Apólice Blindada para: {termo_busca}")
    resultados = buscar_apolice_inteligente(termo_busca)

    if not resultados:
        return "Não encontrei nenhuma apólice com esse dado."

    if isinstance(resultados, str):
        return resultados

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
    """
    Envia uma mensagem de lembrete de vencimento via WhatsApp.

    Args:
        numero_telefone: Telefone do cliente.
        nome_cliente: Nome do cliente.
        data_vencimento: Data de vencimento.
        valor_parcela: Valor da parcela.
        numero_apolice: Número da apólice.
        placa: Placa do veículo.
    """
    return "Função de envio de WhatsApp acionada (Simulação)."


@tool
def obter_contato_especialista(intencao_usuario: str) -> str:
    """
    Retorna o contato do especialista baseado no assunto.

    Args:
        intencao_usuario: O assunto que o usuário quer tratar (ex: Sinistro, Cotação).
    """
    intencao = intencao_usuario.lower()
    if "rco" in intencao or "prorroga" in intencao or "ônibus" in intencao:
        return "Para RCO e Prorrogações, fale com a **Leidiane**: (62) 9300-6461."
    elif "sinistro" in intencao or "bati" in intencao or "roubo" in intencao:
        return "Para Sinistros, fale urgente com a **Thuanny**: (62) 9417-6837."
    else:
        return "Para Auto, Vida e outros, fale com a **Mara**: (11) 94516-2002."


@tool
def solicitar_autorizacao_leidiane(numero_apolice: str, placa: str, cliente_afirmou_pagamento: bool) -> str:
    """
    ACIONAR QUANDO: Cliente afirma que pagou uma parcela antiga (>25 dias).
    AÇÃO: Envia mensagem para LEIDIANE pedindo validação manual.

    Args:
        numero_apolice: O número da apólice em questão.
        placa: A placa do veículo.
        cliente_afirmou_pagamento: Sempre True se o cliente disse que pagou.
    """
    print(f"🚨 NOTIFICAÇÃO PARA LEIDIANE: Cliente da placa {placa} afirma que pagou. Validar apólice {numero_apolice}.")

    # Retorno para o Agente saber o que dizer ao cliente
    return (
        "✅ Solicitação enviada para a Leidiane com sucesso.\n"
        "INSTRUÇÃO AO AGENTE: Avise o cliente exatamente assim: 'Ok, registrei seu pagamento. "
        "Por segurança, aguarde um instante, preciso validar sua apólice na Seguradora antes de você pagar. "
        "Já avisei a equipe e te enviamos em instantes.'"
    )


@tool
def obter_codigo_de_barras_boleto(numero_apolice: str, mes_referencia: int = 0) -> str:
    """
    Obtém código de barras do boleto.

    Args:
        numero_apolice: O número da apólice encontrada.
        mes_referencia: (Opcional) Se o usuário pedir um mês específico (ex: 12 para Dezembro). Se não, use 0.
    """
    print(f"🛠️ TOOL: Gerar Boleto {numero_apolice} (Mês ref: {mes_referencia})")

    parcela = buscar_parcela_atual(numero_apolice, mes_referencia)

    if not parcela:
        return f"Não encontrei boletos pendentes para a apólice {numero_apolice}."

    caminho_pdf = parcela.get('caminho_pdf_boletos')
    data_vencimento_str = parcela.get('data_vencimento_atual') or parcela.get('data_vencimento')
    nome_seguradora = str(parcela.get('seguradora', '')).lower()
    placa = parcela.get('apolices', {}).get('placa', 'Não informada')

    if not caminho_pdf: return "PDF do boleto não encontrado."

    hoje = date.today()
    if isinstance(data_vencimento_str, str):
        data_vencimento = date.fromisoformat(data_vencimento_str)
    else:
        data_vencimento = data_vencimento_str

    dias_atraso = (hoje - data_vencimento).days

    tolerancia = 0
    if "essor" in nome_seguradora:
        tolerancia = 10
    elif "kovr" in nome_seguradora:
        tolerancia = 5

    # =========================================================================
    # LÓGICA DE TRAVA DE SEGURANÇA E ESCALONAMENTO
    # =========================================================================

    # CENÁRIO 1: Agente descobre a pendência antiga pela primeira vez
    if dias_atraso > 25 and mes_referencia == 0:
        return (
            f"⚠️ **ALERTA DE SISTEMA**\n"
            f"Consta parcela vencida em **{data_vencimento.strftime('%d/%m/%Y')}** ({dias_atraso} dias atrás).\n\n"
            f"🛑 **INSTRUÇÃO:** Pergunte ao cliente: 'Consta uma pendência antiga de {data_vencimento.strftime('%B')}. Ela já foi paga?'"
        )

    # CENÁRIO 2: Agente tenta pegar o mês atual (mes_referencia > 0)
    # Isso significa que o cliente disse "SIM, JÁ PAGUEI".
    if dias_atraso > 25 and mes_referencia > 0:
        return (
            f"⛔ **BLOQUEIO DE SEGURANÇA ATIVO**\n"
            f"O sistema detectou um atraso crítico de {dias_atraso} dias na parcela anterior.\n"
            f"Mesmo com a afirmação do cliente, **NÃO ENTREGUE O CÓDIGO DE BARRAS.**\n"
            f"Risco de apólice cancelada na Cia.\n\n"
            f"👉 **AÇÃO OBRIGATÓRIA:** Chame IMEDIATAMENTE a ferramenta `solicitar_autorizacao_leidiane`."
        )

    # Se passou da tolerância simples
    if dias_atraso > tolerancia:
        nome_exibicao = "Essor" if "essor" in nome_seguradora else "Kovr"
        return (
            f"⚠️ **Boleto Vencido há {dias_atraso} dias.**\n"
            f"A {nome_exibicao} só aceita até {tolerancia} dias. Fale com a LEIDIANE."
        )

    # =========================================================================
    # EXTRAÇÃO (Só libera se estiver tudo 100% em dia)
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

    return f"Boleto válido, mas não li o código."


@tool
def marcar_parcela_como_paga(numero_apolice: str) -> str:
    """Registra a baixa de pagamento de uma parcela (Simulação)."""
    return "Esta função deve ser usada apenas com confirmação visual do comprovante."


# --- 2. CONFIGURAÇÃO DO LANGGRAPH ---

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

tools = [
    buscar_clientes_com_vencimento_hoje,
    enviar_lembrete_whatsapp,
    obter_codigo_de_barras_boleto,
    marcar_parcela_como_paga,
    descobrir_numero_apolice,
    obter_contato_especialista,
    solicitar_autorizacao_leidiane  # <--- NOVA FERRAMENTA DE VALIDAÇÃO
]

llm_with_tools = None
if OPENAI_API_KEY:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    llm_with_tools = llm.bind_tools(tools)
else:
    print("⚠️ ALERTA: OPENAI_API_KEY não encontrada.")


# --- PROMPT DO SISTEMA (PERSONALIDADE SEGURA) ---

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


hoje_str = date.today().strftime("%d/%m/%Y")

system_prompt = f"""Você é o Agente da MOREIRASEG. Hoje é {hoje_str}.

### 🛑 PROTOCOLO DE SEGURANÇA - LEIA COM ATENÇÃO:

1. **Ao ver pendência antiga (>25 dias):**
   - Pergunte: "Já pagou a parcela antiga?"

2. **Se o cliente disser "SIM" (Já paguei):**
   - Tente buscar o boleto do mês atual (use `obter_codigo_de_barras_boleto` com mês > 0).
   - **SE A FERRAMENTA BLOQUEAR E PEDIR VALIDAÇÃO:**
     - **OBEDECER IMEDIATAMENTE.**
     - Use a ferramenta `solicitar_autorizacao_leidiane` (envie True no pagamento).
     - Não tente argumentar. O risco de cancelamento é real.
     - Responda ao cliente com a frase exata retornada pela ferramenta.

3. **Se o cliente disser "NÃO" (Não paguei):**
   - Encaminhe para a Leidiane regularizar a dívida.

### 🛑 OUTROS:
- Cotações -> Mara.
- Sinistros -> Thuanny.
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

print("✓ LangGraph Configurado: Fluxo de Validação Humana (Leidiane) Ativo.")


# --- 3. INTERFACE ---

def executar_agente(comando: str) -> str:
    if not llm_with_tools: return "Erro: Agente sem API Key."
    config = {"configurable": {"thread_id": "sessao_segura_v3"}}

    try:
        input_message = HumanMessage(content=comando)
        output = app.invoke({"messages": [input_message]}, config=config)
        return output["messages"][-1].content
    except Exception as e:
        return f"Erro técnico: {str(e)}"