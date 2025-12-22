import os
import streamlit as st
import requests  # <--- OBRIGATÓRIO para baixar o PDF
from typing import Union, Dict, Any, List
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from supabase import create_client, Client
import pandas as pd
import re

# ============================================================
# 1. LÓGICA DE CONEXÃO
# ============================================================

SUPABASE_URL = None
SUPABASE_KEY = None
supabase: Client = None

# 1. Tenta carregar dos "Secrets" do Streamlit
try:
    if "supabase_url" in st.secrets:
        SUPABASE_URL = st.secrets["supabase_url"]
        SUPABASE_KEY = st.secrets["supabase_key"]
except Exception:
    pass

# 2. Se falhar, tenta o .env
if not SUPABASE_URL:
    load_dotenv()
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 3. Tenta criar o cliente APENAS se as chaves foram encontradas
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Erro ao criar cliente Supabase: {e}")
        supabase = None
else:
    pass

# ============================================================
# 2. FUNÇÕES DO AGENTE (LANGGRAPH)
# ============================================================

def buscar_parcelas_vencendo_hoje() -> List[Dict[str, Any]]:
    """
    Busca parcelas vencendo HOJE na tabela 'parcelas'.
    """
    if not supabase: return []

    hoje_iso = date.today().isoformat()
    # print(f"DEBUG: Buscando parcelas vencendo hoje: {hoje_iso}")

    try:
        response = supabase.table("parcelas").select(
            "valor, numero_parcela, data_vencimento, apolices!inner(cliente, contato, numero_apolice, placa)"
        ).eq(
            "data_vencimento", hoje_iso
        ).eq(
            "status", "Pendente"
        ).execute()

        return response.data
    except Exception as e:
        print(f"Erro na busca de parcelas hoje: {e}")
        return []


def buscar_parcela_atual(numero_apolice: str) -> Union[Dict[str, Any], None]:
    """
    Busca a parcela pendente MAIS ANTIGA (prioridade para atrasados)
    e injeta o LINK DO PDF da apólice para o Agente ler.
    """
    if not supabase: return None

    try:
        # 1. Pega dados da apólice
        res_apolice = supabase.table("apolices") \
            .select("id, caminho_pdf_boletos, cliente, seguradora") \
            .eq("numero_apolice", numero_apolice) \
            .execute()

        if not res_apolice.data:
            return None

        apolice_data = res_apolice.data[0]
        apolice_id = apolice_data['id']

        # 2. Busca a parcela pendente mais antiga ou a próxima a vencer
        res_parcela = supabase.table("parcelas") \
            .select("*") \
            .eq("apolice_id", apolice_id) \
            .eq("status", "Pendente") \
            .order("data_vencimento", desc=False) \
            .limit(1) \
            .execute()

        if res_parcela.data:
            dados = res_parcela.data[0]

            # 3. Injeção de dados cruciais para o Agente
            dados['caminho_pdf_boletos'] = apolice_data.get('caminho_pdf_boletos')
            dados['seguradora'] = apolice_data.get('seguradora')
            dados['data_vencimento_atual'] = dados['data_vencimento']
            dados['apolices'] = {'cliente': apolice_data['cliente']}

            return dados

        return None

    except Exception as e:
        print(f"Erro buscar_parcela_atual: {e}")
        return None


def baixar_pdf_bytes(caminho_ou_url: str) -> Union[bytes, None]:
    """
    Baixa o PDF. Aceita Links de Internet e Caminhos Internos.
    """
    if not caminho_ou_url:
        return None

    try:
        # CENÁRIO 1: Link Público (http...)
        if str(caminho_ou_url).startswith("http"):
            response = requests.get(caminho_ou_url, timeout=15)
            if response.status_code == 200:
                return response.content
            else:
                return None

        # CENÁRIO 2: Caminho Interno (Storage do Supabase)
        else:
            bucket_name = "moreiraseg-apolices-pdfs-2025"
            return supabase.storage.from_(bucket_name).download(caminho_ou_url)

    except Exception as e:
        print(f"❌ Exceção ao baixar PDF: {e}")
        return None


def atualizar_status_pagamento(numero_apolice: str, data_vencimento: date) -> bool:
    """Atualiza o pagamento na tabela parcelas e tenta atualizar apolices (legado)."""
    if not supabase: return False
    try:
        # Pega ID
        res = supabase.table("apolices").select("id").eq("numero_apolice", numero_apolice).execute()
        if not res.data: return False
        apolice_id = res.data[0]['id']

        data_str = data_vencimento.isoformat() if isinstance(data_vencimento, date) else data_vencimento

        # Atualiza tabela parcelas
        supabase.table("parcelas").update({
            "status": "Pago",
            "data_pagamento": date.today().isoformat()
        }).eq("apolice_id", apolice_id).eq("data_vencimento", data_str).execute()

        # Atualiza tabela apolices (legado) - Melhor esforço
        try:
            d_obj = date.fromisoformat(data_str)
            chave = f"status_pagamento_{d_obj.strftime('%m_%Y')}"
            supabase.table('apolices').update({chave: 'Pago'}).eq('id', apolice_id).execute()
        except:
            pass

        return True
    except Exception as e:
        print(f"Erro update: {e}")
        return False


def buscar_apolice_inteligente(termo: str) -> List[Dict[str, Any]]:
    """
    Busca apólices pesquisando por PLACA ou NOME.
    CORREÇÃO: Ordena por 'data_inicio_vigencia' pois 'fim_vigencia' não existe na tabela.
    """
    if not supabase: return []
    print(f"🔍 IA Buscando apólice por: {termo}")

    try:
        termo_limpo = termo.strip()

        # CORREÇÃO AQUI: Trocado 'fim_vigencia' por 'data_inicio_vigencia'
        response = supabase.table('apolices').select(
            "cliente, numero_apolice, placa, seguradora, data_inicio_vigencia, status"
        ).or_(f"placa.ilike.%{termo_limpo}%,cliente.ilike.%{termo_limpo}%") \
            .order("data_inicio_vigencia", desc=True) \
            .limit(5).execute()

        return response.data
    except Exception as e:
        print(f"Erro na busca inteligente: {e}")
        # Retorna erro amigável para o Agente ler, em vez de crashar
        return f"Erro técnico no banco de dados ao buscar '{termo}': {str(e)}"

# ============================================================
# 3. FUNÇÕES LEGADO (PARA O DASHBOARD)
# ============================================================

def adicionar_dias_uteis(data_inicial: date, dias_uteis: int) -> date:
    dias_adicionados = 0
    data_atual = data_inicial
    while dias_adicionados < dias_uteis:
        data_atual += timedelta(days=1)
        if data_atual.weekday() < 5:
            dias_adicionados += 1
    return data_atual


def buscar_cobrancas_boleto_do_dia():
    return buscar_parcelas_vencendo_hoje()


def buscar_todas_as_parcelas_pendentes():
    if not supabase: return []
    try:
        res = supabase.table("parcelas").select("*, apolices(cliente, numero_apolice)").eq("status", "Pendente").execute()
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