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


# --- FERRAMENTA 1: TRIAGEM ---
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


# --- FERRAMENTA 2: BOLETO COM REGRAS DE NEGÓCIO ---
@tool
def obter_codigo_de_barras_boleto(numero_apolice: str) -> str:
    """Obtém código de barras aplicando regras de RCO e formatando para cópia fácil."""

    # 1. Busca dados
    parcela = buscar_parcela_atual(numero_apolice)
    if not parcela: return f"Apólice {numero_apolice} não encontrada."

    caminho_pdf = parcela.get('caminho_pdf_boletos')
    data_vencimento_str = parcela.get('data_vencimento_atual')
    # Tenta pegar seguradora (se não tiver, assume genérico)
    nome_seguradora = str(parcela.get('seguradora', '')).lower()

    if not caminho_pdf: return "PDF do boleto não encontrado."

    # 2. Cálculos de Data
    hoje = date.today()
    if isinstance(data_vencimento_str, str):
        data_vencimento = date.fromisoformat(data_vencimento_str)
    else:
        data_vencimento = data_vencimento_str

    dias_atraso = (hoje - data_vencimento).days

    # 3. Definição de Tolerância
    tolerancia = 0
    if "essor" in nome_seguradora:
        tolerancia = 10
    elif "kovr" in nome_seguradora:
        tolerancia = 5

    # 4. Regras de Negócio

    # --- Regra Crítica (> 20 dias) ---
    if dias_atraso > 20:
        return (
            f"🚨 **URGENTE: RISCO DE CANCELAMENTO**\n"
            f"O boleto venceu há {dias_atraso} dias. Fale com a LEIDIANE imediatamente para tentar salvar a apólice."
        )

    # --- Regra de Prorrogação (Passou da tolerância) ---
    if dias_atraso > tolerancia:
        nome_exibicao = "Essor" if "essor" in nome_seguradora else "Kovr"
        return (
            f"⚠️ **Boleto Vencido há {dias_atraso} dias.**\n"
            f"A {nome_exibicao} só aceita até {tolerancia} dias. O código antigo não funciona mais.\n"
            f"Solicite a **Prorrogação** (novo boleto) com a LEIDIANE."
        )

    # --- Regra de Cobertura (Atrasado mas aceitável) ---
    aviso_cobertura = ""
    if dias_atraso > 0:
        aviso_cobertura = f"\n\n⚠️ **ATENÇÃO:** Você está SEM COBERTURA até a baixa bancária do pagamento."

    # 5. Extração e Formatação (O Pulo do Gato para o Copiar/Colar)
    if extrair_codigo_de_barras:
        pdf_bytes = baixar_pdf_bytes(caminho_pdf)
        if pdf_bytes:
            # Formata data para dd/mm/aaaa
            data_fmt = data_vencimento.strftime('%d/%m/%Y')
            codigo = extrair_codigo_de_barras(pdf_bytes, data_fmt)

            if codigo:
                # As crases triplas ```text criam a caixa com botão de cópia
                return (
                    f"Aqui está o código de barras para o pagamento:{aviso_cobertura}\n\n"
                    f"```text\n{codigo}\n```\n\n"
                    f"📋 _(Clique no ícone acima para copiar)_"
                )

    return "Não consegui ler o código, mas o boleto está válido (verifique o PDF)."


# --- ATENÇÃO: AQUI EU REMOVI A SEGUNDA VERSÃO REPETIDA DA FUNÇÃO ACIMA ---

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

# LISTA DE FERRAMENTAS CORRIGIDA (Adicionei a obter_contato_especialista)
tools = [
    buscar_clientes_com_vencimento_hoje,
    enviar_lembrete_whatsapp,
    obter_codigo_de_barras_boleto,
    marcar_parcela_como_paga,
    descobrir_numero_apolice,
    obter_contato_especialista  # <--- FALTAVA ISSO AQUI
]

# Verifica a chave da OpenAI agora
if OPENAI_API_KEY and META_ACCESS_TOKEN and AGENT_IMPORTS_AVAILABLE:
    try:
        # Inicializa o LLM com OpenAI (GPT-4o mini)
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=OPENAI_API_KEY,
            temperature=0,
            max_tokens=4096
        )

        # DEFINIÇÃO DO CÉREBRO (PROMPT DO SISTEMA ATUALIZADO)
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é o Agente Inteligente da CORRETORA MOREIRASEG.
                Sua personalidade é Profissional, Resolutiva e Clara.

                ### 🚀 SEUS SUPER-PODERES (REGRA DE OURO):
                1. **BUSCA POR PLACA:** Se o usuário der uma **PLACA**, use a ferramenta `descobrir_numero_apolice` **IMEDIATAMENTE** para achar o número da apólice.
                2. Somente com o número da apólice em mãos, use as outras ferramentas.

                ### ⚠️ IMPORTANTE:
                Se o usuário fornecer um NOME, explique educadamente que devido a homônimos, você precisa da **PLACA** ou do **CPF** para localizar o seguro com segurança.

                ---

                ### 🧠 REGRAS DE NEGÓCIO (MEMORIZE ISTO):

                **1. SOBRE PAGAMENTOS ATRASADOS (RCO):**
                   - O segurado fica **SEM COBERTURA** a partir do primeiro dia de atraso até a baixa bancária. AVISO OBRIGATÓRIO.
                   - **Seguradora ESSOR:** Aceita pagamento do MESMO boleto até **10 dias corridos** após vencimento.
                   - **Seguradora KOVR:** Aceita pagamento do MESMO boleto até **5 dias corridos** após vencimento.
                   - **Cancelamento:** Após **20 dias** de atraso, as seguradoras iniciam o cancelamento da apólice.
                   - **Prorrogação:** Se passar do prazo (5 ou 10 dias), o cliente precisa de um NOVO boleto (Prorrogação). Não é possível prorrogar o mesmo boleto duas vezes.

                **2. SOBRE A EQUIPE (TRIAGEM):**
                   Use a ferramenta `obter_contato_especialista` para direcionar:
                   - **LEIDIANE:** Assuntos de RCO, Prorrogação de boleto vencido, Renovação de Frota.
                   - **THUANNY:** Sinistro (Batidas, Roubos, Acidentes).
                   - **MARA:** Seguros de Automóvel (Carro/Moto), Vida, Residencial, Escolar e APP.             
                   
                **3. CRITÉRIO DE DESEMPATE (PLACA DUPLICADA):**
                   - Se encontrar mais de uma apólice para a mesma placa, verifique o status.
                   - **IGNORE** apólices com atraso superior a 60 dias ou status "Cancelado".
                   - **FOQUE APENAS** na apólice mais recente/vigente.
                   - Não liste a apólice antiga para o usuário, finja que ela não existe para evitar confusão.
            

                ---

                ### 🤖 COMO AGIR EM CADA SITUAÇÃO:

                **SITUAÇÃO 1: Cliente pede boleto (via Placa)**
                - Passo 1: Use `descobrir_numero_apolice`.
                - Passo 2: Se houver duplicidade, aplique o CRITÉRIO DE DESEMPATE (pegue a mais nova).
                - Passo 3: Verifique a data de vencimento da apólice escolhida.
                - Passo 4: Se estiver no prazo (Dia ou Tolerância), use `obter_codigo_de_barras_boleto`.
                  *Se for atrasado na tolerância, avise que está SEM COBERTURA.*

                **SITUAÇÃO 2: Boleto Vencido (Fora do Prazo ou > 20 dias)**
                - NÃO envie código de barras antigo se a ferramenta informar que expirou.
                - Encaminhe para a **Leidiane** (Prorrogação).
                - Se > 20 dias, alerte sobre CANCELAMENTO.

                **SITUAÇÃO 3: Triagem Geral**
                - "Bati o carro" -> Thuanny.
                - "Cotar seguro novo" -> Mara (Auto) ou Leidiane (RCO).

                Não invente dados. Se não achar a placa, pergunte novamente.
                """),

            # AQUI ENTRA O HISTÓRICO DA CONVERSA
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
            memory=memory,
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
    # Teste de triagem
    print(executar_agente("Bati meu carro, o que faço?"))