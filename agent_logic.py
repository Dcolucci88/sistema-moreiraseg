# ESTE É O CÓDIGO COMPLETO E CORRIGIDO PARA agent_logic.py

import os
import streamlit as st  # <-- ADICIONADO para ler os "Secrets"
from datetime import date
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool

# Importa as funções que criamos. Elas serão as "ferramentas" da nossa IA.
from utils.supabase_client import (
    buscar_cobrancas_boleto_do_dia,
    atualizar_status_pagamento,
    buscar_parcela_atual,
    baixar_pdf_bytes
)
from utils.pdf_parser import extrair_codigo_de_barras


# --- 1. Definição das Ferramentas ---
# (Suas funções @tool permanecem 100% intactas)

@tool
def buscar_clientes_com_vencimento_hoje():
    """
    Executa uma busca no banco de dados por todas as apólices de seguro do tipo 'Boleto'
    que possuem uma parcela vencendo exatamente hoje e cujo pagamento esteja pendente.
    Retorna uma lista de apólices para iniciar o processo de cobrança.
    """
    print("EXECUTANDO FERRAMENTA: buscar_clientes_com_vencimento_hoje")
    return buscar_cobrancas_boleto_do_dia()


@tool
def obter_codigo_de_barras_boleto(numero_apolice: str):
    """
    Usada quando um cliente solicita o código de barras para pagamento de uma apólice específica.
    Esta ferramenta precisa do 'numero_apolice' para funcionar.
    Ela baixa o carnê em PDF e extrai a linha digitável correta para o vencimento atual.
    """
    print(f"EXECUTANDO FERRAMenta: obter_codigo_de_barras_boleto para a apólice {numero_apolice}")

    parcela = buscar_parcela_atual(numero_apolice)
    if not parcela:
        return f"Não foi possível encontrar os dados da apólice {numero_apolice}."

    caminho_pdf = parcela.get('caminho_pdf_boletos')
    data_vencimento = parcela.get('data_vencimento_atual')

    if not caminho_pdf or not data_vencimento:
        return f"Dados de PDF ou vencimento faltando para a apólice {numero_apolice}."

    pdf_bytes = baixar_pdf_bytes(caminho_pdf)
    if not pdf_bytes:
        return f"Não foi possível baixar o carnê em PDF para a apólice {numero_apolice}."

    # Formata a data para o formato 'dd/mm/yyyy' que o parser espera
    data_formatada = data_vencimento.strftime('%d/%m/%Y')

    codigo_barras = extrair_codigo_de_barras(pdf_bytes, data_formatada)
    return codigo_barras


@tool
def marcar_parcela_como_paga(numero_apolice: str):
    """
    Usada quando um cliente informa que já pagou o boleto de uma apólice específica.
    Esta ferramenta atualiza o status da parcela para 'Pago' no banco de dados.
    Precisa do 'numero_apolice' para identificar qual apólice deve ser atualizada.
    """
    print(f"EXECUTANDO FERRAMenta: marcar_parcela_como_paga para a apólice {numero_apolice}")

    parcela = buscar_parcela_atual(numero_apolice)
    if not parcela:
        return f"Não foi possível encontrar os dados da apólice {numero_apolice} para dar baixa."

    data_vencimento = parcela.get('data_vencimento_atual')
    if not data_vencimento:
        return f"Não foi possível determinar a data de vencimento para a apólice {numero_apolice}."

    success = atualizar_status_pagamento(numero_apolice, data_vencimento)
    if success:
        return f"A baixa de pagamento para a apólice {numero_apolice} foi registrada com sucesso."
    else:
        return f"Ocorreu um erro ao tentar registrar a baixa de pagamento para a apólice {numero_apolice}."


# --- 2. Inicialização do Modelo de Linguagem (LLM) ---

# --- LÓGICA DE CARREGAMENTO HÍBRIDA (Groq) ---
GROQ_API_KEY = None
try:
    # 1. Tenta carregar dos "Secrets" do Streamlit (para deploy)
    if "groq_api_key" in st.secrets:
        GROQ_API_KEY = st.secrets["groq_api_key"]
except Exception:
    # Ignora. Acontece em scripts non-streamlit.
    pass

# 2. Se falhar (para rodar no PC ou script), carrega do .env
if not GROQ_API_KEY:
    load_dotenv()  # Carrega o .env
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# --- 3. Criação do Agente (Condicional) ---

# Inicializa componentes como None. Eles só serão criados se a chave existir.
llm = None
prompt = None
agent = None
agent_executor = None
tools = [buscar_clientes_com_vencimento_hoje, obter_codigo_de_barras_boleto, marcar_parcela_como_paga]

if GROQ_API_KEY:
    # Se a chave foi encontrada, inicializa o LLM e o Agente
    llm = ChatGroq(
        model_name="llama3-70b-8192",
        groq_api_key=GROQ_API_KEY
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", """Você é um assistente de IA da MOREIRASEG CORRETORA DE SEGUROS.
Sua personalidade é Profissional, Confiável e Prestativa.
Sua função é gerenciar a cobrança de parcelas de seguros.
Use suas ferramentas para buscar informações, obter códigos de barras e dar baixa em pagamentos.
Responda de forma direta e execute a ação solicitada.
IMPORTANTE: Quando a ferramenta 'buscar_clientes_com_vencimento_hoje' for usada, sua resposta final deve ser APENAS a lista que a ferramenta retornou, sem nenhum texto adicional. Se a lista estiver vazia, sua resposta final deve ser apenas '[]'."""),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)

    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True
    )
else:
    # Isso será impresso no log do Streamlit Cloud se a chave falhar
    print("ALERTA: A chave GROQ_API_KEY não foi encontrada. O Agente de IA ficará desabilitado.")


# --- 4. Função Principal (Modificada) ---
def executar_agente(comando: str):
    """Envia um comando para o agente de IA e retorna a resposta."""

    # --- VERIFICAÇÃO ---
    # Verifica se o agente foi inicializado corretamente
    if agent_executor is None:
        print(
            "ERRO: executar_agente foi chamado, mas o agent_executor não foi inicializado. (Verifique a GROQ_API_KEY)")
        return "Desculpe, o Agente de IA não está configurado corretamente. (Faltando API Key)"
    # --- FIM DA VERIFICAÇÃO ---

    print(f"\n--- Executando Agente com o comando: '{comando}' ---")
    try:
        response = agent_executor.invoke({"input": comando})
        return response['output']
    except Exception as e:
        print(f"Ocorreu um erro ao executar o agente: {e}")
        return "Desculpe, não consegui processar sua solicitação no momento."


# Bloco para testar este arquivo diretamente
if __name__ == '__main__':
    print("Testando o agente de IA...")
    # Teste 1: Buscar cobranças do dia
    # print(executar_agente("Verifique e liste as cobranças com vencimento para hoje."))

    # Teste 2: Simular um pedido de código de barras
    print(executar_agente("O cliente da apólice 783 precisa do código de barras."))

    # Teste 3: Simular uma confirmação de pagamento
    # print(executar_agente("O cliente da apólice 783 confirmou o pagamento."))
