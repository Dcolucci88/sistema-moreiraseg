import schedule
import time
import os
from datetime import datetime
from dotenv import load_dotenv

# Importa o módulo do agente de IA
from agent_logic import executar_agente

# --- CONFIGURAÇÃO DE AMBIENTE E SECRETS ---
# O agendador precisa carregar as credenciais por conta própria
# Força o carregamento do .env se não estiver no ambiente Streamlit
load_dotenv()


# --- FUNÇÃO PRINCIPAL DE TRABALHO ---

def executar_fluxo_de_cobranca():
    """
    Função que será agendada. Ela executa o agente de IA com o comando
    para iniciar o fluxo de trabalho de lembretes de vencimento.
    """
    print("\n" + "=" * 80)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INICIANDO FLUXO DE COBRANÇA DIÁRIA PROATIVA...")

    # Comando para acionar o fluxo de trabalho completo no Agente de IA
    comando = "Execute o fluxo de trabalho de cobrança e envie os lembretes de vencimento de hoje."

    try:
        # Chama a função principal do seu agente de IA
        resultado = executar_agente(comando)

        print(f"RESULTADO DO AGENTE: {resultado}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] FLUXO DE COBRANÇA CONCLUÍDO.")

    except Exception as e:
        print(f"ERRO CRÍTICO no Agendador ao executar o agente: {e}")


# --- CONFIGURAÇÃO DO AGENDAMENTO (SCHEDULE) ---

# Agende a função para rodar todos os dias úteis (Monday a Friday) às 09:00 AM (fuso horário local do Streamlit/servidor)
# Ajuste o horário conforme o fuso horário da sua corretora e o melhor horário para o lembrete.
schedule.every().day.at("09:00").do(executar_fluxo_de_cobranca)
# Você pode agendar para mais vezes:
# schedule.every(10).minutes.do(executar_fluxo_de_cobranca)

print("=" * 80)
print(f"Agendador configurado para rodar a tarefa diariamente às 09:00.")
print(f"Verificando agora para ver se a tarefa deve ser executada...")
print("=" * 80 + "\n")

# --- LOOP PRINCIPAL DO AGENDADOR ---

if __name__ == '__main__':
    # Esta parte é importante. No ambiente de produção do Streamlit,
    # um script rodando o tempo todo não é ideal, mas para fins de teste
    # e simulação, o loop abaixo manterá o agendador ativo.

    # Imediatamente verifica se há alguma tarefa agendada para ser executada agora
    schedule.run_pending()

    # O Streamlit roda apenas o app.py, então esta parte será testada localmente.
    # No ambiente de produção, esta lógica é movida para uma thread no app.py
    # para não bloquear a interface.

    print("Iniciando loop de agendamento. (CTRL+C para parar se estiver localmente)")
    while True:
        # Verifica se há tarefas pendentes e as executa
        schedule.run_pending()
        # Espera 1 segundo antes de verificar novamente
        time.sleep(1)