import os
import streamlit as st
import requests
from typing import Union, Dict, Any, List
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from supabase import create_client, Client
import pandas as pd

# ============================================================
# 1. LÓGICA DE CONEXÃO SIMPLIFICADA E DIAGNÓSTICA
# ============================================================

load_dotenv()


def get_secret(key_name):
    """Busca chaves no Streamlit Secrets ou Variáveis de Ambiente."""
    # 1. Tenta Secrets (Streamlit Cloud)
    try:
        if hasattr(st, "secrets"):
            if key_name in st.secrets: return st.secrets[key_name]
            if key_name.upper() in st.secrets: return st.secrets[key_name.upper()]
    except:
        pass

    # 2. Tenta Ambiente (Local)
    return os.environ.get(key_name) or os.environ.get(key_name.upper())


# Busca as credenciais
SUPABASE_URL = get_secret("supabase_url")
SUPABASE_KEY = get_secret("supabase_key")
supabase: Client = None

# Tenta conectar e MOSTRA O ERRO SE FALHAR
try:
    if not SUPABASE_URL or not SUPABASE_KEY:
        # Se estiver rodando no Streamlit, mostra aviso visual
        # (Descomente a linha abaixo se quiser ver na tela qual chave falta)
        # st.warning(f"Debug Keys: URL found? {bool(SUPABASE_URL)} | KEY found? {bool(SUPABASE_KEY)}")
        print("Aviso: Credenciais do Supabase não encontradas.")
    else:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    # Mostra o erro real na tela para podermos corrigir
    st.error(f"⚠️ Erro detalhado na conexão Supabase: {e}")
    supabase = None


# ============================================================
# 2. FUNÇÕES DE NEGÓCIO E AGENTE DE IA
# ============================================================

def buscar_parcelas_vencendo_hoje() -> List[Dict[str, Any]]:
    if not supabase: return []
    hoje_iso = date.today().isoformat()
    try:
        response = supabase.table("parcelas").select(
            "valor, numero_parcela, data_vencimento, apolices!inner(cliente, contato, numero_apolice, placa)"
        ).eq("data_vencimento", hoje_iso).eq("status", "Pendente").execute()
        return response.data
    except Exception as e:
        print(f"Erro busca hoje: {e}")
        return []


def buscar_parcela_atual(numero_apolice: str) -> Union[Dict[str, Any], None]:
    if not supabase: return None
    try:
        # 1. Pega dados da apólice
        res_apolice = supabase.table("apolices").select("id, caminho_pdf_boletos, cliente").eq("numero_apolice",
                                                                                               numero_apolice).execute()
        if not res_apolice.data: return None

        apolice_data = res_apolice.data[0]
        hoje = date.today().isoformat()

        # 2. Pega a próxima parcela
        res_parcela = supabase.table("parcelas").select("*").eq("apolice_id", apolice_data['id']).eq("status",
                                                                                                     "Pendente").gte(
            "data_vencimento", hoje).order("data_vencimento").limit(1).execute()

        # Fallback
        if not res_parcela.data:
            res_parcela = supabase.table("parcelas").select("*").eq("apolice_id", apolice_data['id']).eq("status",
                                                                                                         "Pendente").order(
                "data_vencimento").limit(1).execute()

        if res_parcela.data:
            dados = res_parcela.data[0]
            dados['caminho_pdf_boletos'] = apolice_data.get('caminho_pdf_boletos')
            dados['data_vencimento_atual'] = dados['data_vencimento']
            dados['apolices'] = {'cliente': apolice_data['cliente']}
            return dados
        return None
    except Exception as e:
        print(f"Erro buscar parcela: {e}")
        return None


def baixar_pdf_bytes(caminho_ou_url: str) -> Union[bytes, None]:
    if not caminho_ou_url: return None
    try:
        if str(caminho_ou_url).startswith("http"):
            response = requests.get(caminho_ou_url, timeout=15)
            return response.content if response.status_code == 200 else None
        else:
            return supabase.storage.from_("moreiraseg-apolices-pdfs-2025").download(caminho_ou_url)
    except Exception as e:
        print(f"Erro PDF: {e}")
        return None


def atualizar_status_pagamento(numero_apolice: str, data_vencimento: date) -> bool:
    if not supabase: return False
    try:
        res = supabase.table("apolices").select("id").eq("numero_apolice", numero_apolice).execute()
        if not res.data: return False

        apolice_id = res.data[0]['id']
        data_str = data_vencimento.isoformat() if isinstance(data_vencimento, date) else data_vencimento

        supabase.table("parcelas").update({"status": "Pago", "data_pagamento": date.today().isoformat()}).eq(
            "apolice_id", apolice_id).eq("data_vencimento", data_str).execute()

        # Retrocompatibilidade
        try:
            d = date.fromisoformat(data_str)
            supabase.table('apolices').update({f"status_pagamento_{d.strftime('%m_%Y')}": 'Pago'}).eq('id',
                                                                                                      apolice_id).execute()
        except:
            pass
        return True
    except:
        return False


# --- FUNÇÕES LEGADO (DASHBOARD) ---

def adicionar_dias_uteis(data_inicial: date, dias_uteis: int) -> date:
    d = data_inicial
    count = 0
    while count < dias_uteis:
        d += timedelta(days=1)
        if d.weekday() < 5: count += 1
    return d


def buscar_todas_as_parcelas_pendentes():
    if not supabase: return []
    try:
        res = supabase.table("parcelas").select("*, apolices(cliente, numero_apolice)").eq("status",
                                                                                           "Pendente").execute()
        lista = []
        for p in res.data:
            if p.get('apolices'):
                p['cliente'] = p['apolices']['cliente']
                p['numero_apolice'] = p['apolices']['numero_apolice']
            lista.append(p)
        return lista
    except:
        return []


def get_apolices(search_term=None):
    if not supabase: return pd.DataFrame()
    try:
        query = supabase.table('apolices').select("*").order('id', desc=True)
        if search_term:
            term = f"%{search_term}%"
            query = query.or_(f"numero_apolice.ilike.{term},cliente.ilike.{term},placa.ilike.{term}")

        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            df['data_inicio_vigencia'] = pd.to_datetime(df['data_inicio_vigencia']).dt.date
            df['data_final_de_vigencia'] = df['data_inicio_vigencia'].apply(
                lambda x: x + relativedelta(years=1) if pd.notnull(x) else None)
            df['dias_restantes'] = (pd.to_datetime(df['data_final_de_vigencia']).dt.date - date.today()).apply(
                lambda x: x.days)
            df['prioridade'] = df['dias_restantes'].apply(lambda d: '⚪ Expirada' if d < 0 else (
                '🔥 Urgente' if d <= 15 else ('⚠️ Alta' if d <= 30 else ('⚠️ Média' if d <= 60 else '✅ Baixa'))))
        return df
    except:
        return pd.DataFrame()


def get_sinistros():
    if not supabase: return pd.DataFrame()
    try:
        res = supabase.table('sinistros').select("*").order('data_ultima_atualizacao', desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except:
        return pd.DataFrame()


def add_historico(apolice_id, usuario_email, acao, detalhes=""):
    if not supabase: return
    try:
        supabase.table('historico').insert(
            {'apolice_id': apolice_id, 'usuario': usuario_email, 'acao': acao, 'detalhes': detalhes}).execute()
    except:
        pass


def add_historico_sinistro(sinistro_id, usuario_email, status_anterior, status_novo, observacao=""):
    if not supabase: return
    try:
        supabase.table('historico_sinistros').insert(
            {'sinistro_id': sinistro_id, 'usuario': usuario_email, 'status_anterior': status_anterior,
             'status_novo': status_novo, 'observacao': observacao}).execute()
    except:
        pass


# Compatibilidade
def buscar_cobrancas_boleto_do_dia(): return buscar_parcelas_vencendo_hoje()