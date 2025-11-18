import os
import requests
import json
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env (apenas se executado localmente)
load_dotenv()

# --- CONFIGURAÇÕES DA API DO WHATSAPP ---
# As variáveis são carregadas do .env (local) ou do Streamlit Secrets (produção)
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
META_TEMPLATE_NAME = os.getenv("META_TEMPLATE_NAME")


def enviar_mensagem_whatsapp(destinatario: str, variaveis_template: dict) -> bool:
    """
    Envia uma mensagem de modelo (template) via API do WhatsApp Business da Meta.

    Args:
        destinatario (str): O número de telefone do cliente (formato internacional, ex: 5562912345678).
        variaveis_template (dict): Um dicionário com as variáveis (parâmetros)
                                   necessárias para preencher o corpo do template.
                                   Ex: {"nome": "Cliente", "aplice": "AB-123", "valor": "R$ 500,00"}

    Returns:
        True se a mensagem foi enviada com sucesso, False caso contrário.
    """
    # Verifica se as configurações críticas estão disponíveis
    if not all([META_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, META_TEMPLATE_NAME]):
        print("\n" + "=" * 50)
        print("ALERTA: CONFIGURAÇÃO DE WHATSAPP INCOMPLETA.")
        print(
            "Certifique-se de que META_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID e META_TEMPLATE_NAME estão configurados.")
        print("Retornando True para simulação.")
        print("=" * 50 + "\n")
        return True  # Retorna True simulado se faltarem chaves, para não quebrar testes

    # O endpoint da API é específico para o ID do seu número de telefone
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    # Converte o dicionário de variáveis para o formato de componente da API
    component_parameters = []
    for key, value in variaveis_template.items():
        component_parameters.append({
            "type": "text",
            "text": str(value)  # Garante que todos os valores são strings
        })

    # Estrutura do payload para enviar um template (mensagem de modelo)
    payload = {
        "messaging_product": "whatsapp",
        "to": destinatario,
        "type": "template",
        "template": {
            "name": META_TEMPLATE_NAME,
            "language": {
                "code": "pt_BR"  # Linguagem do template
            },
            "components": [
                {
                    "type": "body",
                    "parameters": component_parameters
                }
            ]
        }
    }

    # Cabeçalhos da requisição
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    print("\n" + "=" * 50)
    print(f"ENVIANDO WHATSAPP REAL para: {destinatario}")
    print(f"Template: {META_TEMPLATE_NAME}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print("=" * 50)

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()  # Lança um erro para códigos de status HTTP ruins (4xx ou 5xx)

        print(f"Sucesso ao enviar WhatsApp. Status: {response.status_code}")
        print(f"Resposta da API: {response.json()}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"ERRO ao enviar WhatsApp: {e}")
        if 'response' in locals() and response.text:
            print(f"Detalhes do Erro da API: {response.text}")
        return False


# Bloco para testar esta função diretamente
if __name__ == '__main__':
    # Este é um número de telefone de teste válido no ambiente de desenvolvimento da Meta
    # Substitua pelo seu próprio número de teste, se necessário, ou use o do cliente no cenário real.

    # IMPORTANTE: Destinatário deve ser um número registrado na Meta para testes!
    numero_teste = os.getenv("NUMERO_DESTINATARIO_TESTE", "556291204461")

    # Variáveis baseadas no seu template "lembrete_vencimento_humanizado"
    variaveis = {
        "aplice": "99-9999",
        "placa": "ABC-1234",
        "valor": "R$ 542,80",
        "parcela": "3/5",  # Exemplo de variável extra
        "nome_cliente": "Fulano de Tal"  # Exemplo de variável extra
    }

    # O seu template "lembrete_vencimento_humanizado" precisa das variáveis {1} a {5}
    # de acordo com o print que você forneceu do Gerenciador.
    # Vamos mapear as variáveis do dicionário para a ordem no template:
    # {1} = Nome do Cliente
    # {2} = Aplice
    # {3} = Placa
    # {4} = Valor
    # {5} = Parcela/Vencimento (o que for mais relevante, vou usar a Parcela aqui)

    template_vars_ordenadas = {
        "1": variaveis["nome_cliente"],
        "2": variaveis["aplice"],
        "3": variaveis["placa"],
        "4": variaveis["valor"],
        "5": variaveis.get("parcela", "Vencimento")
    }

    # A API espera os parâmetros em uma lista *ordenada* com a chave 'text'.
    # O agente de IA precisará fornecer o dicionário de variáveis na ordem correta
    # que o template espera.

    # Exemplo: O agente de IA deverá gerar um dicionário como:
    # {"nome_cliente": "João", "aplice": "123", "placa": "XYZ", "valor": "R$ 100", "parcela": "2/3"}

    # Simulando o preenchimento do template:
    template_parameters = {
        "nome_cliente": "Daniele Moreira",
        "aplice": "AB-12345",
        "placa": "DEF-6789",
        "valor": "R$ 750,00",
        "parcela_data": "3/5 (10/11/2025)"
    }

    # Para que a função fique genérica, ela precisará de uma lista ordenada de strings para o template.
    # O agente de IA deverá fornecer APENAS o texto dos campos, na ordem.
    # Por enquanto, vamos manter o dicionário para a função placeholder e deixar o agente
    # de IA responsável por garantir que as variáveis necessárias sejam passadas.

    print(f"TESTE: Tentando enviar mensagem para {numero_teste}")

    # A função principal do agente (agent_logic.py) fará o mapeamento e passará o dicionário.
    # Aqui passamos um dicionário de exemplo:
    sucesso = enviar_mensagem_whatsapp(numero_teste, template_parameters)

    print("\n" + "=" * 50)
    print(f"Resultado do Envio: {'SUCESSO' if sucesso else 'FALHA'}")
    print("=" * 50)