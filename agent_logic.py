import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool

# Importa as funções que criamos. Elas serão as "ferramentas" da nossa IA.
from utils.supabase_client import buscar_cobrancas_boleto_do_dia, atualizar_status_pagamento
# OBS: Precisaremos adicionar uma função para baixar o PDF no supabase_client.py depois.
# from utils.pdf_parser import extrair_codigo_de_barras

# Carrega as variáveis de ambiente (GROQ_API_KEY) do arquivo .env
load_dotenv()

# --- 1. Definição das Ferramentas ---
# A IA lê o texto abaixo de @tool (docstring) para saber quando usar cada função.

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
    print(f"EXECUTANDO FERRAMENTA: obter_codigo_de_barras_boleto para a apólice {numero_apolice}")
    # TODO: Implementar a lógica completa:
    # 1. Buscar no Supabase a apólice para achar o caminho do PDF e a data de vencimento atual.
    # 2. Chamar uma função 'baixar_pdf_bytes(caminho)' do supabase_client.
    # 3. Chamar 'extrair_codigo_de_barras(bytes, data_formatada)'.
    return f"Código de barras para a apólice {numero_apolice} é: 12345.67890 12345.678901 12345.678901 2 12345678901234 (IMPLEMENTAÇÃO PENDENTE)"

@tool
def marcar_parcela_como_paga(numero_apolice: str):
    """
    Usada quando um cliente informa que já pagou o boleto de uma apólice específica.
    Esta ferramenta atualiza o status da parcela para 'Pago' no banco de dados.
    Precisa do 'numero_apolice' para identificar qual apólice deve ser atualizada.
    """
    print(f"EXECUTANDO FERRAMENTA: marcar_parcela_como_paga para a apólice {numero_apolice}")
    # TODO: Implementar a lógica para pegar a data de vencimento correta.
    from datetime import date
    # Exemplo, usando a data de hoje para a baixa. O ideal é buscar a data correta.
    data_hoje = date.today() 
    return atualizar_status_pagamento(numero_apolice, data_hoje)

# --- 2. Inicialização do Modelo de Linguagem (LLM) ---
llm = ChatGroq(
    model_name="llama3-70b-8192",
    groq_api_key=os.environ.get("GROQ_API_KEY")
)

# --- 3. Criação do Prompt do Agente ---
prompt = ChatPromptTemplate.from_messages([
    ("system", """Você é um assistente de IA da MOREIRASEG CORRETORA DE SEGUROS.
Sua personalidade é Profissional, Confiável e Prestativa.
Sua função é gerenciar a cobrança de parcelas de seguros.
Use suas ferramentas para buscar informações, obter códigos de barras e dar baixa em pagamentos.
Responda de forma direta e execute a ação solicitada."""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# --- 4. Criação e Execução do Agente ---
tools = [buscar_clientes_com_vencimento_hoje, obter_codigo_de_barras_boleto, marcar_parcela_como_paga]
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(
    agent=agent, 
    tools=tools, 
    verbose=True # verbose=True é MUITO útil para vermos o "raciocínio" da IA no terminal
)

# --- Função Principal ---
def executar_agente(comando: str):
    """Envia um comando para o agente de IA e retorna a resposta."""
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
    executar_agente("Verifique e liste as cobranças com vencimento para hoje.")
    
    # Teste 2: Simular um pedido de código de barras
    executar_agente("O cliente da apólice 987654321 precisa do código de barras para pagar.")

    # Teste 3: Simular uma confirmação de pagamento
    executar_agente("O cliente da apólice 112233445 confirmou o pagamento.")
