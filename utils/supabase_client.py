import os
import streamlit as st  # Importante: Precisamos do streamlit aqui
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from supabase import create_client, Client
import pandas as pd
import re  # Importado para a função de upload

# --- LÓGICA DE CARREGAMENTO HÍBRIDA (CORRIGIDA) ---

try:
    # 1. Tenta carregar dos "Secrets" do Streamlit (para deploy na nuvem)
    #    Ele lê os "Secrets" que você configurou no formato TOML
    SUPABASE_URL = st.secrets["supabase_url"]
    SUPABASE_KEY = st.secrets["supabase_key"]
    # print("Credenciais carregadas via Streamlit Secrets (Modo Deploy).")

except (KeyError, FileNotFoundError):
    # 2. Se falhar (está rodando no seu PC), carrega do arquivo .env
    # print("Credenciais não encontradas no Streamlit Secrets. Carregando do arquivo .env (Modo Local).")
    load_dotenv()
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# --- VALIDAÇÃO E CRIAÇÃO DO CLIENTE ---

if not SUPABASE_URL or not SUPABASE_KEY:
    # Este erro agora aparecerá no log do Streamlit Cloud se os "Secrets" estiverem errados
    st.error("ERRO CRÍTICO: As credenciais do Supabase (URL e Key) não foram encontradas.")
    st.stop()

try:
    # Cliente Supabase principal (agora usa as variáveis corretas)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    # print("Cliente Supabase inicializado com sucesso.")
except Exception as e:
    st.error(f"Falha ao inicializar o cliente Supabase: {e}")
    st.stop()


# --- SUAS FUNÇÕES ORIGINAIS (INTACTAS) ---
# O resto do seu arquivo permanece exatamente o mesmo.

def adicionar_dias_uteis(data_inicial: date, dias_uteis: int) -> date:
    """Adiciona um número de dias úteis a uma data, pulando fins de semana."""
    dias_adicionados = 0
    data_atual = data_inicial
    while dias_adicionados < dias_uteis:
        data_atual += timedelta(days=1)
        if data_atual.weekday() < 5:
            dias_adicionados += 1
    return data_atual


def buscar_cobrancas_boleto_do_dia():
    """Busca no Supabase as apólices com parcela vencendo hoje, retornando apenas os dados essenciais."""
    hoje = date.today()
    print(f"Buscando cobranças para o dia {hoje.strftime('%d/%m/%Y')}...")
    colunas_necessarias = "numero_apolice, placa, contato, data_inicio_vigencia, quantidade_parcelas, dia_vencimento"
    try:
        response = supabase.table('apolices').select(colunas_necessarias).ilike('tipo_cobranca', '%boleto%').execute()
    except Exception as e:
        print(f"Erro ao buscar apólices no Supabase: {e}")
        return []
    if not response.data:
        print("Nenhuma apólice com tipo de cobrança contendo 'boleto' foi encontrada no banco de dados.")
        return []

    apolices_com_vencimento_hoje = []
    for apolice in response.data:
        numero_apolice = apolice.get('numero_apolice')
        print(f"\n--- Verificando Apólice: {numero_apolice} ---")
        inicio_vigencia_str = apolice.get('data_inicio_vigencia')
        qtd_parcelas = apolice.get('quantidade_parcelas')
        dia_vencimento_padrao = apolice.get('dia_vencimento')
        if not all([inicio_vigencia_str, qtd_parcelas, dia_vencimento_padrao]):
            print("  -> Dados incompletos, pulando apólice.")
            continue
        inicio_vigencia = date.fromisoformat(inicio_vigencia_str)
        for i in range(1, int(qtd_parcelas) + 1):
            vencimento_calculado = None
            if i == 1:
                vencimento_calculado = adicionar_dias_uteis(inicio_vigencia, 5)
            else:
                data_base_parcela = inicio_vigencia + relativedelta(months=1)
                vencimento_calculado = data_base_parcela + relativedelta(months=i - 2)
                try:
                    vencimento_calculado = vencimento_calculado.replace(day=int(dia_vencimento_padrao))
                except ValueError:
                    ultimo_dia_mes = (vencimento_calculado.replace(day=28) + timedelta(days=4)).replace(
                        day=1) - timedelta(days=1)
                    vencimento_calculado = ultimo_dia_mes
            print(f"  Parcela {i}: Vencimento Calculado = {vencimento_calculado.strftime('%d/%m/%Y')}")
            if vencimento_calculado == hoje:
                print(f"  ✅ VENCIMENTO ENCONTRADO PARA HOJE!")
                print(f"  -> Apólice {numero_apolice} adicionada à lista de cobrança.")
                apolice['data_vencimento_atual'] = hoje.isoformat()
                apolices_com_vencimento_hoje.append(apolice)
                break
    if not apolices_com_vencimento_hoje:
        print("\nNenhum boleto de apólice vence hoje.")
    return apolices_com_vencimento_hoje


def atualizar_status_pagamento(numero_apolice: str, data_vencimento: date):
    chave_status = f"status_pagamento_{data_vencimento.strftime('%m_%Y')}"
    update_data = {chave_status: 'Pago'}
    try:
        supabase.table('apolices').update(update_data).eq('numero_apolice', numero_apolice).execute()
        print(
            f"Status da apólice {numero_apolice} para o mês {data_vencimento.strftime('%m/%Y')} atualizado para 'Pago'.")
        return True
    except Exception as e:
        print(f"Erro ao atualizar status da apólice {numero_apolice}: {e}")
        return False


def buscar_parcela_atual(numero_apolice: str):
    hoje = date.today()
    try:
        response = supabase.table('apolices').select("*").eq('numero_apolice', numero_apolice).single().execute()
        apolice = response.data
        if not apolice:
            return None
        inicio_vigencia_str = apolice.get('data_inicio_vigencia')
        qtd_parcelas = apolice.get('quantidade_parcelas')
        dia_vencimento_padrao = apolice.get('dia_vencimento')
        inicio_vigencia = date.fromisoformat(inicio_vigencia_str)
        for i in range(1, int(qtd_parcelas) + 1):
            vencimento_calculado = None
            if i == 1:
                vencimento_calculado = adicionar_dias_uteis(inicio_vigencia, 5)
            else:
                data_base_parcela = inicio_vigencia + relativedelta(months=i - 1)
                try:
                    vencimento_calculado = data_base_parcela.replace(day=int(dia_vencimento_padrao))
                except ValueError:
                    ultimo_dia_mes = (data_base_parcela.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
                        days=1)
                    vencimento_calculado = ultimo_dia_mes
            if vencimento_calculado >= hoje - timedelta(days=30):
                apolice['data_vencimento_atual'] = vencimento_calculado
                return apolice
        return None
    except Exception as e:
        print(f"Erro ao buscar parcela atual para apólice {numero_apolice}: {e}")
        return None


def baixar_pdf_bytes(caminho_pdf: str) -> bytes:
    try:
        BUCKET_NAME = "moreiraseg-apolices-pdfs-2025"
        response = supabase.storage.from_(BUCKET_NAME).download(caminho_pdf)
        return response
    except Exception as e:
        print(f"Erro ao baixar PDF do Supabase Storage: {e}")
        return None


def buscar_todas_apolices():
    """Busca todas as apólices para exibição no dashboard."""
    try:
        response = supabase.table('apolices').select("*").order('id', desc=True).execute()
        return response.data
    except Exception as e:
        print(f"Erro ao buscar todas as apólices: {e}")
        return []


def buscar_todas_as_parcelas_pendentes():
    """Busca em todas as apólices e gera uma lista completa de todas as parcelas pendentes."""
    print("Buscando todas as parcelas pendentes...")
    try:
        response = supabase.table('apolices').select("*").ilike('tipo_cobranca', '%boleto%').execute()
        if not response.data:
            return []
        lista_de_parcelas = []
        for apolice in response.data:
            inicio_vigencia_str = apolice.get('data_inicio_vigencia')
            qtd_parcelas = apolice.get('quantidade_parcelas')
            dia_vencimento_padrao = apolice.get('dia_vencimento')
            if not all([inicio_vigencia_str, qtd_parcelas, dia_vencimento_padrao]):
                continue
            inicio_vigencia = date.fromisoformat(inicio_vigencia_str)
            for i in range(1, int(qtd_parcelas) + 1):
                vencimento_calculado = None
                if i == 1:
                    vencimento_calculado = adicionar_dias_uteis(inicio_vigencia, 5)
                else:
                    data_base_parcela = inicio_vigencia + relativedelta(months=1)
                    vencimento_calculado = data_base_parcela + relativedelta(months=i - 2)
                    try:
                        vencimento_calculado = vencimento_calculado.replace(day=int(dia_vencimento_padrao))
                    except ValueError:
                        ultimo_dia_mes = (vencimento_calculado.replace(day=28) + timedelta(days=4)).replace(
                            day=1) - timedelta(days=1)
                        vencimento_calculado = ultimo_dia_mes
                chave_status = f"status_pagamento_{vencimento_calculado.strftime('%m_%Y')}"
                status_parcela = apolice.get(chave_status, 'Pendente')
                if status_parcela == 'Pendente':
                    parcela_info = {
                        'cliente': apolice.get('cliente'),
                        'numero_apolice': apolice.get('numero_apolice'),
                        'numero_parcela': i,
                        'data_vencimento': vencimento_calculado,
                        'valor': apolice.get('valor_parcela')
                    }
                    lista_de_parcelas.append(parcela_info)
        return lista_de_parcelas
    except Exception as e:
        print(f"Erro ao buscar todas as parcelas pendentes: {e}")
        return []


def get_apolices(search_term=None):
    """Busca apólices, converte as datas corretamente e calcula a data final de vigência."""
    try:
        query = supabase.table('apolices').select("*").order('id', desc=True)
        if search_term:
            ilike_term = f"%{search_term}%"
            query = query.or_(f"numero_apolice.ilike.{ilike_term},cliente.ilike.{ilike_term},placa.ilike.{ilike_term}")

        response = query.execute()
        df = pd.DataFrame(response.data)

        if not df.empty:
            df['data_inicio_vigencia'] = pd.to_datetime(df['data_inicio_vigencia']).dt.date
            df['data_final_de_vigencia'] = df['data_inicio_vigencia'].apply(
                lambda x: x + relativedelta(years=1) if pd.notnull(x) else None)
            today = date.today()
            df['dias_restantes'] = (pd.to_datetime(df['data_final_de_vigencia']) - pd.to_datetime(today)).dt.days

            def define_prioridade(dias):
                if pd.isna(dias) or dias < 0: return '⚪ Expirada'
                if dias <= 15:
                    return '🔥 Urgente'
                elif dias <= 30:
                    return '⚠️ Alta'
                elif dias <= 60:
                    return '⚠️ Média'
                else:
                    return '✅ Baixa'

            df['prioridade'] = df['dias_restantes'].apply(define_prioridade)
        return df
    except Exception as e:
        print(f"Erro ao carregar apólices: {e}")
        return pd.DataFrame()


# --- NOVAS FUNÇÕES PARA O MÓDULO DE SINISTRO ---

def get_sinistros():
    """Busca todos os sinistros cadastrados."""
    try:
        response = supabase.table('sinistros').select("*").order('data_ultima_atualizacao', desc=True).execute()
        if response.data:
            return pd.DataFrame(response.data)
        return pd.DataFrame()
    except Exception as e:
        print(f"Erro ao carregar os sinistros: {e}")
        return pd.DataFrame()


def add_historico_sinistro(sinistro_id, usuario_email, status_anterior, status_novo, observacao=""):
    """Adiciona um registro de ação na tabela 'historico_sinistros'."""
    try:
        supabase.table('historico_sinistros').insert({
            'sinistro_id': sinistro_id,
            'usuario': usuario_email,
            'status_anterior': status_anterior,
            'status_novo': status_novo,
            'observacao': observacao
        }).execute()
    except Exception as e:
        print(f"⚠️ Não foi possível registrar a atualização do sinistro no histórico: {e}")


# --- BLOCO DE MANUTENÇÃO ADMINISTRATIVA (VERSÃO 2 - ATUALIZAÇÃO DIRETA) ---
# Este código SÓ será executado se você rodar este arquivo diretamente.
# Ex: python utils/supabase_client.py
if __name__ == "__main__":
    print("--- EXECUTANDO SCRIPT DE MANUTENÇÃO ADMIN ---")

    # Recarrega o .env para pegar as novas chaves
    load_dotenv()

    # Pega as chaves de ADMIN do arquivo .env
    SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
    ADMIN_ID = os.environ.get("ADMIN_USER_ID")
    ADMIN_URL = os.environ.get("SUPABASE_URL")

    if not all([SERVICE_KEY, ADMIN_ID, ADMIN_URL]):
        print("ERRO: As variáveis SUPABASE_SERVICE_KEY ou ADMIN_USER_ID não foram encontradas no .env.")
    else:
        print("Conectando ao Supabase com privilégios de administrador...")
        try:
            # Cria um cliente SEPARADO E SEGURO apenas para esta tarefa
            supabase_admin: Client = create_client(ADMIN_URL, SERVICE_KEY)

            print(f"Atualizando metadados para o usuário: {ADMIN_ID} (Método Direto de DB)")

            # Define os novos metadados que queremos salvar
            new_metadata = {
                "perfil": "admin",
                "nome_completo": "Administrador Principal"
            }

            # --- ABORDAGEM CORRIGIDA: ATUALIZAR O BANCO DE DADOS DIRETAMENTE ---
            # A chave 'service_role' bypassa o RLS e pode escrever em qualquer tabela.
            # Nós vamos atualizar a coluna 'raw_user_meta_data' na tabela 'users' do schema 'auth'.

            response = supabase_admin.table('"auth"."users"').update(
                {"raw_user_meta_data": new_metadata}
            ).eq("id", ADMIN_ID).execute()

            print("\n--- SUCESSO! ---")
            print("Os metadados do usuário foram atualizados diretamente no banco de dados.")

            if response.data:
                user_updated = response.data[0]
                print(f"Novo perfil: {user_updated['raw_user_meta_data'].get('perfil')}")
            else:
                print("Atualização concluída. Verifique o painel do Supabase para confirmar.")

        except Exception as e:
            print(f"\n--- ERRO DURANTE A ATUALIZAÇÃO (Método DB): {e} ---")