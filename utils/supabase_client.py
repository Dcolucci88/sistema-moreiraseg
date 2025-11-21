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
# 1. LÓGICA DE CONEXÃO (A MESMA DO SEU CÓDIGO ORIGINAL)
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

# 3. Cria o cliente
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Erro ao criar cliente Supabase: {e}")
        supabase = None
else:
    pass


# ============================================================
# 2. FUNÇÕES ATUALIZADAS (PARA O AGENTE E PDF FUNCIONAREM)
# ============================================================

def buscar_parcelas_vencendo_hoje() -> List[Dict[str, Any]]:
    """
    Busca parcelas vencendo HOJE na tabela 'parcelas'.
    """
    if not supabase: return []

    hoje_iso = date.today().isoformat()
    print(f"DEBUG: Buscando parcelas vencendo hoje: {hoje_iso}")

    try:
        # Consulta otimizada para o robô
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
    Busca a próxima parcela pendente e o LINK DO PDF no banco.
    """
    if not supabase: return None

    try:
        # 1. Pega dados da apólice (incluindo o link do PDF)
        res_apolice = supabase.table("apolices") \
            .select("id, caminho_pdf_boletos, cliente") \
            .eq("numero_apolice", numero_apolice) \
            .execute()

        if not res_apolice.data:
            print(f"Apólice {numero_apolice} não encontrada.")
            return None

        apolice_data = res_apolice.data[0]
        apolice_id = apolice_data['id']
        hoje = date.today().isoformat()

        # 2. Pega a próxima parcela pendente
        res_parcela = supabase.table("parcelas") \
            .select("*") \
            .eq("apolice_id", apolice_id) \
            .eq("status", "Pendente") \
            .gte("data_vencimento", hoje) \
            .order("data_vencimento") \
            .limit(1) \
            .execute()

        # Se não achar futura, pega qualquer pendente
        if not res_parcela.data:
            res_parcela = supabase.table("parcelas") \
                .select("*") \
                .eq("apolice_id", apolice_id) \
                .eq("status", "Pendente") \
                .order("data_vencimento") \
                .limit(1) \
                .execute()

        if res_parcela.data:
            dados = res_parcela.data[0]
            # INJETA O CAMINHO DO PDF PARA O AGENTE LER
            dados['caminho_pdf_boletos'] = apolice_data.get('caminho_pdf_boletos')
            dados['data_vencimento_atual'] = dados['data_vencimento']
            dados['apolices'] = {'cliente': apolice_data['cliente']}
            return dados

        return None

    except Exception as e:
        print(f"Erro buscar_parcela_atual: {e}")
        return None


def baixar_pdf_bytes(caminho_ou_url: str) -> Union[bytes, None]:
    """
    Baixa o PDF. Aceita Links de Internet (Novo) e Caminhos Internos (Antigo).
    """
    if not caminho_ou_url:
        print("Erro: Caminho do PDF é vazio.")
        return None

    print(f"⬇️ Baixando PDF: {caminho_ou_url}")

    try:
        # CENÁRIO 1: Link Público (http...)
        if str(caminho_ou_url).startswith("http"):
            response = requests.get(caminho_ou_url, timeout=15)
            if response.status_code == 200:
                return response.content
            else:
                print(f"❌ Erro ao baixar via URL. Status: {response.status_code}")
                return None

        # CENÁRIO 2: Caminho Interno (Legado)
        else:
            bucket_name = "moreiraseg-apolices-pdfs-2025"
            return supabase.storage.from_(bucket_name).download(caminho_ou_url)

    except Exception as e:
        print(f"❌ Exceção ao baixar PDF: {e}")
        return None


def atualizar_status_pagamento(numero_apolice: str, data_vencimento: date) -> bool:
    """Atualiza o pagamento na tabela nova e na antiga."""
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

        # Atualiza tabela apolices (legado)
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


# ============================================================
# 3. FUNÇÕES LEGADO (MANTIDAS PARA O DASHBOARD NÃO QUEBRAR)
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
    # Redireciona para a nova função melhorada
    return buscar_parcelas_vencendo_hoje()


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