import os
import streamlit as st
import requests
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

try:
    if "supabase_url" in st.secrets:
        SUPABASE_URL = st.secrets["supabase_url"]
        SUPABASE_KEY = st.secrets["supabase_key"]
except Exception:
    pass

if not SUPABASE_URL:
    load_dotenv()
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Erro Supabase: {e}")
        supabase = None
else:
    pass


# ============================================================
# 2. FUNÇÕES DO AGENTE (INTELIGÊNCIA NOVA)
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
        print(f"Erro buscar_parcelas_vencendo_hoje: {e}")
        return []


def buscar_parcela_atual(numero_apolice: str, mes_referencia: int = None) -> Union[Dict[str, Any], None]:
    """
    Busca parcelas.
    - Se 'mes_referencia' for informado (ex: 12), busca EXATAMENTE aquele mês.
    - Se não, busca a MAIS ANTIGA pendente (regra de cobrança).
    """
    if not supabase: return None

    try:
        # 1. Pega dados da apólice
        res_apolice = supabase.table("apolices") \
            .select("id, caminho_pdf_boletos, cliente, seguradora") \
            .eq("numero_apolice", numero_apolice) \
            .execute()

        if not res_apolice.data: return None
        apolice_data = res_apolice.data[0]
        apolice_id = apolice_data['id']

        # 2. Busca TODAS as pendentes ordenadas
        res_parcelas = supabase.table("parcelas") \
            .select("*") \
            .eq("apolice_id", apolice_id) \
            .eq("status", "Pendente") \
            .order("data_vencimento", desc=False) \
            .execute()

        if not res_parcelas.data: return None

        lista_parcelas = res_parcelas.data
        parcela_escolhida = None

        # --- LÓGICA DE SELEÇÃO INTELIGENTE ---
        if mes_referencia and mes_referencia > 0:
            # Tenta encontrar o mês pedido pelo usuário
            for p in lista_parcelas:
                try:
                    # Extrai o mês da data 'YYYY-MM-DD'
                    mes_vencimento = int(p['data_vencimento'].split('-')[1])
                    if mes_vencimento == mes_referencia:
                        parcela_escolhida = p
                        break
                except:
                    continue

            # Se não achou o mês exato, pega a primeira (fallback)
            if not parcela_escolhida:
                parcela_escolhida = lista_parcelas[0]
        else:
            # Se não pediu mês, pega a mais antiga (Regra Padrão)
            parcela_escolhida = lista_parcelas[0]

        # 3. Monta o retorno
        if parcela_escolhida:
            parcela_escolhida['caminho_pdf_boletos'] = apolice_data.get('caminho_pdf_boletos')
            parcela_escolhida['seguradora'] = apolice_data.get('seguradora')
            parcela_escolhida['data_vencimento_atual'] = parcela_escolhida['data_vencimento']
            parcela_escolhida['apolices'] = {'cliente': apolice_data['cliente']}
            return parcela_escolhida

        return None

    except Exception as e:
        print(f"Erro buscar_parcela_atual: {e}")
        return None


def baixar_pdf_bytes(caminho_ou_url: str) -> Union[bytes, None]:
    if not caminho_ou_url: return None
    try:
        if str(caminho_ou_url).startswith("http"):
            response = requests.get(caminho_ou_url, timeout=15)
            return response.content if response.status_code == 200 else None
        else:
            bucket_name = "moreiraseg-apolices-pdfs-2025"
            return supabase.storage.from_(bucket_name).download(caminho_ou_url)
    except Exception:
        return None


def atualizar_status_pagamento(numero_apolice: str, data_vencimento: date) -> bool:
    if not supabase: return False
    try:
        res = supabase.table("apolices").select("id").eq("numero_apolice", numero_apolice).execute()
        if not res.data: return False
        apolice_id = res.data[0]['id']
        data_str = data_vencimento.isoformat() if isinstance(data_vencimento, date) else data_vencimento

        supabase.table("parcelas").update({
            "status": "Pago", "data_pagamento": date.today().isoformat()
        }).eq("apolice_id", apolice_id).eq("data_vencimento", data_str).execute()
        return True
    except:
        return False


def buscar_apolice_inteligente(termo: str) -> List[Dict[str, Any]]:
    """
    CORRIGIDO: Ordena por 'data_inicio_vigencia' para evitar erro de coluna inexistente.
    """
    if not supabase: return []
    try:
        termo_limpo = termo.strip()
        response = supabase.table('apolices').select(
            "cliente, numero_apolice, placa, seguradora, data_inicio_vigencia, status"
        ).or_(f"placa.ilike.%{termo_limpo}%,cliente.ilike.%{termo_limpo}%") \
            .order("data_inicio_vigencia", desc=True) \
            .limit(5).execute()
        return response.data
    except Exception as e:
        # Retorna lista vazia em caso de erro para não quebrar o fluxo
        print(f"Erro busca inteligente: {str(e)}")
        return []


# ============================================================
# 3. FUNÇÕES LEGADO (RESTAURADAS PARA O DASHBOARD FUNCIONAR)
# ============================================================

def adicionar_dias_uteis(data_inicial: date, dias_uteis: int) -> date:
    """Calcula data útil futura (usada no cadastro de apólices)"""
    dias_adicionados = 0
    data_atual = data_inicial
    while dias_adicionados < dias_uteis:
        data_atual += timedelta(days=1)
        if data_atual.weekday() < 5:
            dias_adicionados += 1
    return data_atual


def buscar_cobrancas_boleto_do_dia():
    """Alias para manter compatibilidade com código antigo"""
    return buscar_parcelas_vencendo_hoje()


def buscar_todas_as_parcelas_pendentes():
    """RESTAURADA: Popula os cards de 'Parcelas Pendentes' no Dashboard"""
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
    """RESTAURADA: Popula a tabela principal e contadores do Dashboard"""
    if not supabase: return pd.DataFrame()
    try:
        query = supabase.table('apolices').select("*").order('id', desc=True)
        if search_term:
            term = f"%{search_term}%"
            query = query.or_(f"numero_apolice.ilike.{term},cliente.ilike.{term},placa.ilike.{term}")
        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            # Conversão e cálculos de datas
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
    """RESTAURADA: Popula a aba de Sinistros"""
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