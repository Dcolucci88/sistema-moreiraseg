import os
import streamlit as st
from datetime import date
from dotenv import load_dotenv
from utils.supabase_client import (
    buscar_parcelas_vencendo_hoje,
    atualizar_status_pagamento,
    buscar_parcela_atual,
    baixar_pdf_bytes,
    buscar_apolice_inteligente
)

# Tenta importar o leitor de PDF, se falhar, o código trata depois
try:
    from utils.pdf_parser import extrair_codigo_de_barras
except ImportError:
    extrair_codigo_de_barras = None

from langchain.memory import ConversationBufferWindowMemory
from langchain_core.prompts import MessagesPlaceholder  # Para dizer ao Prompt onde a memória deve ir
import requests
import re
from typing import List, Dict, Any, Union
import sys  # Importado para o sys.exit()

# Carrega variáveis de ambiente do .env, caso existam
load_dotenv()

# --- VERIFICAÇÃO DAS VARIÁVEIS DE AMBIENTE (ALTERADO PARA OPENAI) ---
print("Variáveis carregadas:")
print(f"OPENAI_API_KEY: {'***' if os.environ.get('OPENAI_API_KEY') else 'NÃO ENCONTRADA'}")
print(f"META_ACCESS_TOKEN: {'***' if os.environ.get('META_ACCESS_TOKEN') else 'NÃO ENCONTRADA'}")

# --- 3. Memória (CONFIGURAÇÃO GLOBAL) ---
# Criamos o objeto de memória que vai guardar as últimas 5 mensagens
memory = ConversationBufferWindowMemory(
    memory_key="chat_history",
    return_messages=True,
    k=5
)

# --- IMPORTAÇÕES DO MOTOR DE IA (ALTERADO PARA OPENAI) ---
try:
    from langchain_openai import ChatOpenAI
    print("✓ ChatOpenAI importado")
except ImportError as e:
    print(f"✗ ChatOpenAI: {e}")
    print("Instale a biblioteca: pip install langchain-openai")
    sys.exit(1)

# --- CORREÇÃO DE IMPORTAÇÃO (LangChain v0.2+) ---
try:
    from langchain.agents import AgentExecutor
    from langchain.agents import create_tool_calling_agent

    print("✓ Agentes LangChain importados (Executor/ToolCalling)")
    AGENT_IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"✗ Erro ao importar agentes LangChain: {e}")
    AGENT_IMPORTS_AVAILABLE = False

try:
    from langchain_core.prompts import ChatPromptTemplate
    print("✓ ChatPromptTemplate importado")
except ImportError as e:
    print(f"✗ ChatPromptTemplate: {e}")
    sys.exit(1)

try:
    from langchain.tools import tool
    print("✓ tool importado")
except ImportError as e:
    print(f"✗ tool: {e}")
    sys.exit(1)


# --- 1. Definição das Ferramentas (MANTIDAS INTACTAS) ---

@tool
def descobrir_numero_apolice(termo_busca: str) -> str:
    """
    Use esta ferramenta quando o usuário informar apenas a PLACA ou o NOME do cliente
    e você precisar descobrir o 'numero_apolice' para realizar outras tarefas.
    Retorna uma lista de apólices encontradas.
    """
    resultados = buscar_apolice_inteligente(termo_busca)
    if not resultados:
        return "Não encontrei nenhuma apólice com esse nome ou placa."
    return f"Encontrei estas apólices: {resultados}"

@tool
def buscar_clientes_com_vencimento_hoje() -> Union[List[Dict[str, Any]], str]:
    """
    Busca no banco de dados todas as parcelas de seguro que vencem hoje e estão pendentes.
    """
    print("EXECUTANDO FERRAMENTA: buscar_clientes_com_vencimento_hoje")
    return buscar_parcelas_vencendo_hoje()


@tool
def enviar_lembrete_whatsapp(numero_telefone: str, nome_cliente: str, data_vencimento: str, valor_parcela: float,
                             numero_apolice: str, placa: str) -> str:
    """
    Envia uma mensagem de lembrete de vencimento via WhatsApp (API Oficial da Meta).
    """
    print(f"EXECUTANDO FERRAMENTA: enviar_lembrete_whatsapp para {nome_cliente} ({numero_telefone})")

    TOKEN = os.environ.get("META_ACCESS_TOKEN")
    PHONE_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

    # Verifica se estamos em modo de teste ou produção
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

    # Usa o nome do template definido nas variáveis ou um padrão
    template_name = os.environ.get("META_TEMPLATE_NAME", "hello_world")

    # Se for hello_world, não mandamos parâmetros (regra do WhatsApp para teste)
    if template_name == "hello_world":
        payload = {
            "messaging_product": "whatsapp",
            "to": numero_limpo,
            "type": "template",
            "template": {"name": "hello_world", "language": {"code": "en_US"}}
        }
    else:
        # Payload completo para template de produção
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
        response_data = response.json()

        if response.status_code == 200:
            return f"Mensagem enviada com sucesso para {nome_cliente}."
        else:
            return f"Erro ao enviar: {response_data.get('error', {}).get('message', 'Erro desconhecido')}"

    except Exception as e:
        return f"Exceção ao enviar mensagem: {e}"


@tool
def obter_codigo_de_barras_boleto(numero_apolice: str) -> str:
    """
    Obtém o código de barras do boleto atual para uma apólice específica lendo o PDF.
    """
    print(f"EXECUTANDO FERRAMENTA: obter_codigo_de_barras_boleto para a apólice {numero_apolice}")

    # Verifica se a biblioteca pypdf está instalada (via import do utils)
    if extrair_codigo_de_barras is None and os.environ.get("MOCK_WHATSAPP") != "True":
        return "Erro: A biblioteca de leitura de PDF não está instalada. Contacte o suporte."

    if os.environ.get("MOCK_WHATSAPP") == "True":
        return "MOCK: O código de barras simulado é 12345.67890 12345.67890 12345.67890 1 1234."

    parcela = buscar_parcela_atual(numero_apolice)
    if not parcela:
        return f"Não foi possível encontrar os dados da apólice {numero_apolice}."

    caminho_pdf = parcela.get('caminho_pdf_boletos')
    data_vencimento = parcela.get('data_vencimento_atual')

    if not caminho_pdf or not data_vencimento:
        return f"Dados de PDF ou vencimento faltando para a apólice {numero_apolice}."

    pdf_bytes = baixar_pdf_bytes(caminho_pdf)
    if not pdf_bytes:
        return f"Não foi possível baixar o carnê em PDF (Link inválido ou arquivo movido)."

    data_formatada = date.fromisoformat(data_vencimento).strftime('%d/%m/%Y') if isinstance(data_vencimento, str) else data_vencimento.strftime('%d/%m/%Y')

    codigo_barras = extrair_codigo_de_barras(pdf_bytes, data_formatada)
    return codigo_barras if codigo_barras else "Não foi possível extrair o código de barras do PDF (Arquivo pode ser imagem)."


@tool
def marcar_parcela_como_paga(numero_apolice: str) -> str:
    """
    Registra a baixa de pagamento de uma parcela no sistema.
    """
    print(f"EXECUTANDO FERRAMENTA: marcar_parcela_como_paga para a apólice {numero_apolice}")

    parcela = buscar_parcela_atual(numero_apolice)
    if not parcela:
        return f"Não foi possível encontrar os dados da apólice {numero_apolice} para dar baixa."

    data_vencimento = parcela.get('data_vencimento_atual')
    if not data_vencimento:
        return f"Não foi possível determinar a data de vencimento."

    if isinstance(data_vencimento, str):
        data_vencimento = date.fromisoformat(data_vencimento)

    success = atualizar_status_pagamento(numero_apolice, data_vencimento)
    if success:
        return f"A baixa de pagamento para a apólice {numero_apolice} foi registrada com sucesso."
    else:
        return f"Ocorreu um erro ao tentar registrar a baixa."


# --- 2. Inicialização do Agente e LLM (AGORA COM OPENAI) ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")

llm = None
agent_executor = None
tools = [
    buscar_clientes_com_vencimento_hoje,
    enviar_lembrete_whatsapp,
    obter_codigo_de_barras_boleto,
    marcar_parcela_como_paga,
    descobrir_numero_apolice
]

# Verifica a chave da OpenAI agora
if OPENAI_API_KEY and META_ACCESS_TOKEN and AGENT_IMPORTS_AVAILABLE:
    try:
        # Inicializa o LLM com OpenAI (GPT-4o mini)
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=OPENAI_API_KEY,
            temperature=0,  # 0 deixa ele mais preciso e menos criativo
            max_tokens=4096
        )

        # Cria o prompt COM MEMÓRIA
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um Agente de IA da MOREIRASEG CORRETORA DE SEGUROS.
        Sua personalidade é Profissional, Confiável e Prestativa.

        ### SEUS SUPER-PODERES (FERRAMENTAS):
        1. Se o usuário der uma **PLACA** ou **NOME**, use a ferramenta `descobrir_numero_apolice` PRIMEIRO para achar o número da apólice.
        2. Com o número da apólice em mãos, use a ferramenta correta (ex: `obter_codigo_de_barras_boleto`).

        ### FLUXO DE COBRANÇA:
        1. Buscar parcelas vencendo hoje (`buscar_clientes_com_vencimento_hoje`).
        2. Para cada parcela, enviar WhatsApp (`enviar_lembrete_whatsapp`).

        Não peça confirmação se a busca retornar apenas um resultado óbvio. Execute a tarefa solicitada imediatamente.
        """),

            # AQUI ENTRA O HISTÓRICO DA CONVERSA (CRUCIAL PARA MEMÓRIA)
            MessagesPlaceholder(variable_name="chat_history"),

            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        # Cria o Agente
        agent = create_tool_calling_agent(llm, tools, prompt)

        # Cria o Executor COM A MEMÓRIA INTEGRADA
        agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            memory=memory,  # <--- Passando a memória definida lá em cima
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=10
        )

        print("✓ Agente inicializado com sucesso (GPT-4o mini + Memória)")

    except Exception as e:
        print(f"✗ Erro ao inicializar agente OpenAI: {e}")
        agent_executor = None
else:
    print("ALERTA: Agente desabilitado. Verifique as chaves OPENAI_API_KEY no .env ou Secrets.")


# --- 5. Função Principal ---
def executar_agente(comando: str) -> str:
    """Envia um comando para o agente de IA e retorna a resposta."""
    if agent_executor is None:
        return "Desculpe, o Agente de IA não está configurado corretamente. Verifique as chaves de API."

    print(f"\n--- Executando Agente com o comando: '{comando}' ---")
    try:
        # O invoke agora usa a memória automaticamente
        response = agent_executor.invoke({"input": comando})
        return response.get('output', 'Erro: Nenhuma saída gerada.')
    except Exception as e:
        print(f"Ocorreu um erro ao executar o agente: {e}")
        return f"Desculpe, tive um problema técnico: {e}"


# Bloco de teste local
if __name__ == '__main__':
    print("TESTE LOCAL INICIADO")
    # Simula conversa
    print(executar_agente("Olá, quem é você?"))
    print(executar_agente("O que você pode fazer?"))