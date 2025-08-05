import os
from datetime import date
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from supabase import create_client, Client

# Carrega as variáveis de ambiente do arquivo .env que você criou no Passo 1
load_dotenv()

# --- CORREÇÃO PRINCIPAL AQUI ---
# Pega a URL e a chave do Supabase buscando pelo NOME das variáveis de ambiente
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY") # Esta deve ser sua ANON KEY

# Verifica se as variáveis foram carregadas corretamente do arquivo .env
if not url or not key:
    raise ValueError("As variáveis de ambiente SUPABASE_URL e SUPABASE_KEY não foram definidas no arquivo .env.")

# Cria uma instância única do cliente Supabase para ser usada em todo o projeto
supabase: Client = create_client(url, key)

def calcular_vencimento_parcela(inicio_vigencia_str: str, dia_vencimento: int, numero_parcela: int) -> date:
    """
    Calcula a data de vencimento exata para uma parcela específica.
    A primeira parcela (numero_parcela=1) vence no mês seguinte ao início da vigência.
    """
    data_base = date.fromisoformat(inicio_vigencia_str)
    vencimento = data_base + relativedelta(months=numero_parcela)
    return vencimento.replace(day=dia_vencimento)

def buscar_cobrancas_boleto_do_dia():
    """
    Busca no Supabase todas as apólices que têm uma parcela de boleto vencendo hoje.
    Esta é a função principal que o agendador usará.
    """
    hoje = date.today()
    dia_de_hoje = hoje.day
    print(f"Buscando cobranças para o dia {hoje.strftime('%d/%m/%Y')}...")

    try:
        response = supabase.table('apólices').select("*").eq('tipo_cobranca', 'Boleto').eq('dia_vencimento', dia_de_hoje).execute()
    except Exception as e:
        print(f"Erro ao buscar apólices no Supabase: {e}")
        return []

    if not response.data:
        print("Nenhuma apólice encontrada com vencimento no dia de hoje.")
        return []

    apolices_com_vencimento_hoje = []
    
    for apolice in response.data:
        inicio_vigencia = apolice.get('data_inicio_vigencia')
        qtd_parcelas = apolice.get('quantidade_parcelas')

        if not inicio_vigencia or not qtd_parcelas:
            continue
            
        for i in range(1, int(qtd_parcelas) + 1):
            vencimento_calculado = calcular_vencimento_parcela(inicio_vigencia, dia_de_hoje, i)
            
            if vencimento_calculado == hoje:
                chave_status = f"status_pagamento_{hoje.strftime('%m_%Y')}"
                status_parcela = apolice.get(chave_status, 'Pendente')
                
                if status_parcela == 'Pendente':
                    print(f"Apólice encontrada: {apolice.get('numero_apolice')}")
                    apolice['data_vencimento_atual'] = hoje.isoformat()
                    apolices_com_vencimento_hoje.append(apolice)
                break 

    return apolices_com_vencimento_hoje

def atualizar_status_pagamento(numero_apolice: str, data_vencimento: date):
    """
    Atualiza o status de pagamento de uma parcela específica para 'Pago'.
    """
    chave_status = f"status_pagamento_{data_vencimento.strftime('%m_%Y')}"
    update_data = {chave_status: 'Pago'}
    
    try:
        supabase.table('apólices').update(update_data).eq('numero_apolice', numero_apolice).execute()
        print(f"Status da apólice {numero_apolice} para o mês {data_vencimento.strftime('%m/%Y')} atualizado para 'Pago'.")
        return True
    except Exception as e:
        print(f"Erro ao atualizar status da apólice {numero_apolice}: {e}")
        return False
