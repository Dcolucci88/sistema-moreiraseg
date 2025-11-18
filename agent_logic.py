import os
import streamlit as st
from datetime import date
from dotenv import load_dotenv
import requests
import re
from typing import List, Dict, Any, Union
import sys  # Importado para o sys.exit()

# Carrega variáveis de ambiente do .env, caso existam
load_dotenv()

# --- VERIFICAÇÃO DAS VARIÁVEIS DE AMBIENTE ---
print("Variáveis carregadas:")
print(f"GEMINI_API_KEY: {'***' if os.environ.get('GEMINI_API_KEY') else 'NÃO ENCONTRADA'}")
print(f"META_ACCESS_TOKEN: {'***' if os.environ.get('META_ACCESS_TOKEN') else 'NÃO ENCONTRADA'}")

# --- IMPORTAÇÕES ALTERNATIVAS - ABORDAGEM MAIS RECENTE ---
try:
    from langchain_google_genai import ChatGoogleGenerativeAI

    print("✓ ChatGoogleGenerativeAI importado")
except ImportError as e:
    print(f"✗ ChatGoogleGenerativeAI: {e}")
    sys.exit(1)

# --- CORREÇÃO DE IMPORTAÇÃO (LangChain v0.2+) ---
# 'create_tool_calling_agent' é importado diretamente de .agents
try:
    from langchain.agents import AgentExecutor
    from langchain.agents import create_tool_calling_agent # <-- Este é o caminho correto

    print("✓ Agentes LangChain importados (Executor/ToolCalling)")
    AGENT_IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"✗ Erro ao importar agentes LangChain: {e}")
    AGENT_IMPORTS_AVAILABLE = False
# --- FIM DA CORREÇÃO ---

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

# --- Importações de Utilitários (Assumimos que existem) ---
try:
    from utils.supabase_client import (
        buscar_parcelas_vencendo_hoje,
        atualizar_status_pagamento,
        buscar_parcela_atual,
        baixar_pdf_bytes
    )

    print("✓ Utils supabase_client importados")
except ImportError:
    print("ALERTA: utils/supabase_client não encontrado. Usando mocks para teste de unidade.")

    # Implementação de Mocks para o teste de unidade (apenas para este arquivo)
    MOCK_DADOS_VENCIMENTO = [
        {
            "valor": 450.75,
            "numero_parcela": 3,
            "data_vencimento": date.today().isoformat(),  # Vencimento HOJE
            "apolices": {
                "cliente": "João da Silva",
                "contato": "5511987654321",
                "numero_apolice": "AP-10020",
                "placa": "ABC-1234"
            }
        },
        {
            "valor": 123.45,
            "numero_parcela": 5,
            "data_vencimento": date.today().isoformat(),  # Vencimento HOJE
            "apolices": {
                "cliente": "Maria Oliveira",
                "contato": "5521999998888",
                "numero_apolice": "AP-10021",
                "placa": "XYZ-5678"
            }
        }
    ]


    def buscar_parcelas_vencendo_hoje() -> Union[List[Dict[str, Any]], str]:
        """MOCK: Retorna dados de clientes para o Agente testar o loop de envio."""
        return MOCK_DADOS_VENCIMENTO


    def atualizar_status_pagamento(numero_apolice: str, data_vencimento: date) -> bool:
        """MOCK: Simula a atualização de status no banco de dados."""
        print(f"MOCK: Baixa de pagamento simulada para a apólice {numero_apolice}.")
        return True


    def buscar_parcela_atual(numero_apolice: str) -> Union[Dict[str, Any], None]:
        """MOCK: Simula a busca de uma única parcela."""
        if numero_apolice == "AP-10020":
            return {
                "caminho_pdf_boletos": "caminho/mock/joao_carnes.pdf",
                "data_vencimento_atual": date.today().isoformat(),
                "apolices": {"cliente": "João da Silva"}
            }
        if numero_apolice == "AP-10021":
            return {
                "caminho_pdf_boletos": "caminho/mock/maria_carnes.pdf",
                "data_vencimento_atual": date.today().isoformat(),
                "apolices": {"cliente": "Maria Oliveira"}
            }
        return None


    def baixar_pdf_bytes(caminho: str) -> Union[bytes, None]:
        """MOCK: Simula o download de um arquivo PDF."""
        # --- CORREÇÃO DE SINTAXE (Linha 100) ---
        # Removidos caracteres não-ASCII (Código -> Codigo)
        return b"%PDF-1.4\n%Caminho: " + caminho.encode(
            'utf-8') + b"\n%Codigo de Barras: 12345.67890 12345.67890 12345.67890 1 1234\n%%EOF"
        # --- FIM DA CORREÇÃO DE SINTAXE ---


# --- 1. Definição das Ferramentas ---

@tool
def buscar_clientes_com_vencimento_hoje() -> Union[List[Dict[str, Any]], str]:
    """
    Executa uma busca no banco de dados por todas as parcelas de seguro
    que vencem exatamente hoje e cujo pagamento esteja pendente.
    Retorna uma lista de objetos...
    """
    print("EXECUTANDO FERRAMENTA: buscar_clientes_com_vencimento_hoje")
    return buscar_parcelas_vencendo_hoje()


@tool
def enviar_lembrete_whatsapp(numero_telefone: str, nome_cliente: str, data_vencimento: str, valor_parcela: float,
                             numero_apolice: str, placa: str) -> str:
    """
    Envia uma mensagem de lembrete de vencimento humanizada via WhatsApp (API Oficial da Meta).
    ...
    """
    print(f"EXECUTANDO FERRAMENTA: enviar_lembrete_whatsapp para {nome_cliente} ({numero_telefone})")

    # Usa apenas variáveis de ambiente
    TOKEN = os.environ.get("META_ACCESS_TOKEN")
    PHONE_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

    if not TOKEN or not PHONE_ID:
        print("ERRO: Credenciais META_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID não encontradas.")
        if os.environ.get("MOCK_WHATSAPP"):
            return f"MOCK: Mensagem simulada enviada com sucesso para {nome_cliente}."
        return "Erro: Credenciais da API do WhatsApp não configuradas."

    # Limpa o número de telefone
    numero_limpo = re.sub(r'\D', '', numero_telefone)
    # (Lógica de prefixo 55 omitida)

    # Lógica de URL
    url = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    # Formatando o valor
    valor_formatado = f"{valor_parcela:,.2f}".replace('.', '#').replace(',', '.').replace('#', ',')

    # Payload do WhatsApp
    payload = {
        "messaging_product": "whatsapp",
        "to": numero_limpo,
        "type": "template",
        "template": {
            "name": "lembrete_vencimento_humanizado",
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
            return f"Erro ao enviar mensagem para {nome_cliente}: {response_data.get('error', {}).get('message', 'Erro desconhecido')}"

    except Exception as e:
        return f"Exceção ao enviar mensagem: {e}"


@tool
def obter_codigo_de_barras_boleto(numero_apolice: str) -> str:
    """
    Usada quando um cliente solicita o código de barras para pagamento de uma apólice específica.
    ...
    """
    print(f"EXECUTANDO FERRAMENTA: obter_codigo_de_barras_boleto para a apólice {numero_apolice}")

    # Este código assume que a função 'extrair_codigo_de_barras' está acessível.
    try:
        from utils.pdf_parser import extrair_codigo_de_barras
    except ImportError:
        # Se estivermos no modo de teste, mockamos o retorno
        if os.environ.get("MOCK_WHATSAPP"):
            return "MOCK: O código de barras simulado é 12345.67890 12345.67890 12345.67890 1 1234."
        return "Erro: A biblioteca 'utils.pdf_parser' não foi encontrada. Ferramenta de código de barras desabilitada."

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

    # Formata a data
    data_formatada = date.fromisoformat(data_vencimento).strftime('%d/%m/%Y') if isinstance(data_vencimento,
                                                                                            str) else data_vencimento.strftime(
        '%d/%m/%Y')

    codigo_barras = extrair_codigo_de_barras(pdf_bytes, data_formatada)
    return codigo_barras if codigo_barras else "Não foi possível extrair o código de barras para o vencimento atual."


@tool
def marcar_parcela_como_paga(numero_apolice: str) -> str:
    """
    Usada quando um cliente informa que já pagou o boleto...
    """
    print(f"EXECUTANDO FERRAMENTA: marcar_parcela_como_paga para a apólice {numero_apolice}")

    parcela = buscar_parcela_atual(numero_apolice)
    if not parcela:
        return f"Não foi possível encontrar os dados da apólice {numero_apolice} para dar baixa."

    data_vencimento = parcela.get('data_vencimento_atual')
    if not data_vencimento:
        return f"Não foi possível determinar a data de vencimento para a apólice {numero_apolice}."

    # Se data_vencimento for uma string ISO, converte para date.
    if isinstance(data_vencimento, str):
        data_vencimento = date.fromisoformat(data_vencimento)

    success = atualizar_status_pagamento(numero_apolice, data_vencimento)
    if success:
        return f"A baixa de pagamento para a apólice {numero_apolice} foi registrada com sucesso."
    else:
        return f"Ocorreu um erro ao tentar registrar a baixa de pagamento para a apólice {numero_apolice}."


# --- 2. Inicialização do Modelo de Linguagem (LLM) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
META_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

# (Removido o try/except do Streamlit para simplificar o teste local)

# --- 4. Criação do Agente (Condicional) ---
llm = None
prompt = None
agent = None
agent_executor = None
tools = [
    buscar_clientes_com_vencimento_hoje,
    enviar_lembrete_whatsapp,
    obter_codigo_de_barras_boleto,
    marcar_parcela_como_paga
]

if GEMINI_API_KEY and META_ACCESS_TOKEN and AGENT_IMPORTS_AVAILABLE:
    try:
        # Inicializa o LLM
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",  # <--- O modelo novo e correto da sua lista
            google_api_key=GEMINI_API_KEY,
            temperature=0.1,
            max_output_tokens=4096
        )

        # Cria o prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um assistente de IA da MOREIRASEG CORRETORA DE SEGUROS.
Sua personalidade é Profissional, Confiável e Prestativa.
Sua principal função é executar proativamente o fluxo de trabalho de cobrança de parcelas de seguro.

### FLUXO DE TRABALHO DE COBRANÇA AUTOMÁTICA:
Quando o usuário pedir para 'verificar cobranças' ou 'enviar lembretes do dia', seu plano de ação é:

1.  **PASSO 1: BUSCAR**
    Use a ferramenta `buscar_clientes_com_vencimento_hoje` UMA VEZ para obter a lista de TODAS as parcelas pendentes do dia.

2.  **PASSO 2: ANALISAR E EXECUTAR (LOOP)**
    - Se a lista estiver vazia ou houver erro, informe ao usuário.
    - Se a lista contiver dados, você deve iterar sobre CADA item da lista.
    - Para CADA item, extraia os dados e chame a ferramenta `enviar_lembrete_whatsapp`.
    - Formato dos dados:
      {{
        "valor": 123.45,
        "numero_parcela": 3,
        "data_vencimento": "2025-11-05",
        "apolices": {{
          "cliente": "Nome do Cliente",
          "contato": "11987654321",
          "numero_apolice": "AP-98765",
          "placa": "XYZ-1234"
        }}
      }}

3.  **PASSO 3: RESUMIR**
    Após tentar enviar mensagens para TODOS os clientes, forneça um resumo final.

### OUTRAS TAREFAS:
- Código de barras: use `obter_codigo_de_barras_boleto`
- Baixa de pagamento: use `marcar_parcela_como_paga`"""),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),  # Adicionado placeholder para o LangChain
        ])

        # --- CORREÇÃO DE INICIALIZAÇÃO DO AGENTE ---
        # Substituindo 'initialize_agent' pela nova sintaxe
        agent = create_tool_calling_agent(llm, tools, prompt)

        agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            handle_parsing_errors=True,  # Adicionado para robustez
            max_iterations=10
        )
        # --- FIM DA CORREÇÃO ---

        print("✓ Agente inicializado com sucesso usando create_tool_calling_agent")

    except Exception as e:
        print(f"✗ Erro ao inicializar agente: {e}")
        agent_executor = None
else:
    missing = []
    if not GEMINI_API_KEY: missing.append("GEMINI_API_KEY")
    if not META_ACCESS_TOKEN: missing.append("META_ACCESS_TOKEN")
    if not AGENT_IMPORTS_AVAILABLE: missing.append("importações do agente")
    print(f"ALERTA: Agente desabilitado. Itens faltantes: {', '.join(missing)}")


# --- 5. Função Principal ---
def executar_agente(comando: str) -> str:
    """Envia um comando para o agente de IA e retorna a resposta."""
    if agent_executor is None:
        return "Desculpe, o Agente de IA não está configurado corretamente."

    print(f"\n--- Executando Agente com o comando: '{comando}' ---")
    try:
        # --- CORREÇÃO DE EXECUÇÃO (run -> invoke) ---
        # A nova sintaxe do AgentExecutor usa 'invoke' e espera um dicionário
        response = agent_executor.invoke({"input": comando})
        # A resposta agora é um dicionário, pegamos a saída 'output'
        return response.get('output', 'Erro: Nenhuma saída gerada.')
        # --- FIM DA CORREÇÃO ---
    except Exception as e:
        print(f"Ocorreu um erro ao executar o agente: {e}")
        return f"Desculpe, não consegui processar sua solicitação. Erro: {e}"


# Bloco para testar este arquivo diretamente
if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("TESTE DO AGENTE DE IA - MOREIRASEG")
    print("=" * 60)

    # Configuração do ambiente de teste
    os.environ["MOCK_WHATSAPP"] = "True"

    # Se as chaves reais não existirem, usar mocks para teste
    if not (GEMINI_API_KEY and META_ACCESS_TOKEN):
        print("Usando modo de teste com dados mock...")
        os.environ["GEMINI_API_KEY"] = "MOCK_GEMINI_KEY"  # Placeholder se não estiver no .env
        os.environ["META_ACCESS_TOKEN"] = "MOCK_META_TOKEN"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "MOCK_PHONE_ID"

        # Re-inicializar o Agente com chaves mockadas ou reais (se .env existir)
        try:
            gemini_key_to_use = os.environ.get("GEMINI_API_KEY", "MOCK_KEY_FOR_INIT")

            if gemini_key_to_use == "MOCK_KEY_FOR_INIT" or not gemini_key_to_use.startswith("AIza"):
                print(
                    "ALERTA: Chave GEMINI_API_KEY real não encontrada no .env. O teste pode falhar na chamada da API.")
                raise ValueError("Chave GEMINI_API_KEY real não encontrada no .env para o teste.")

            llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                google_api_key=gemini_key_to_use
            )

            # --- CORREÇÃO DE INICIALIZAÇÃO (TESTE) ---
            agent = create_tool_calling_agent(llm, tools, prompt)
            agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True,
                                           max_iterations=10)
            # --- FIM DA CORREÇÃO ---
            print("INFO: Agente re-inicializado com chaves do .env para teste.")

        except Exception as e:
            print(f"ERRO DE CONFIGURAÇÃO DO TESTE: Falha ao inicializar o ChatGoogleGenerativeAI. {e}")
            print("O agente não pode ser executado. Configure a GEMINI_API_KEY no seu .env para testes reais.")
            sys.exit(1)  # Sai do script se o agente não puder ser inicializado

    # Testes
    testes = [
        ("FLUXO DE COBRANÇA", "Execute o fluxo de trabalho de cobrança e envie os lembretes de vencimento de hoje."),
        ("CÓDIGO DE BARRAS",
         "O cliente João da Silva perguntou qual é o código de barras para o pagamento da apólice AP-10020."),
        ("BAIXA DE PAGAMENTO", "O cliente Maria Oliveira disse que já pagou a apólice AP-10021. Dê baixa no sistema.")
    ]

    for nome_teste, comando in testes:
        print(f"\n{nome_teste}:")
        print("-" * 40)
        resultado = executar_agente(comando)
        print(f"\nRESULTADO: {resultado}")
        print("-" * 40)

    print("\n" + "=" * 60)
    print("TESTE CONCLUÍDO!")
    print("=" * 60)