import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import date, datetime
from typing import List, Dict, Any, Union
import requests  # Necessário para baixar via URL

# Carrega variáveis
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("ERRO CRÍTICO: Credenciais do Supabase não encontradas no .env")
    supabase = None
else:
    supabase: Client = create_client(url, key)


# --- FUNÇÕES DE BUSCA ---

def buscar_todas_as_parcelas_pendentes() -> List[Dict[str, Any]]:
    """Busca todas as parcelas com status Pendente."""
    try:
        response = supabase.table("parcelas") \
            .select("*, apolices(cliente, numero_apolice, contato, placa, email)") \
            .eq("status", "Pendente") \
            .execute()
        return response.data
    except Exception as e:
        print(f"Erro ao buscar todas parcelas: {e}")
        return []


def buscar_parcelas_vencendo_hoje() -> List[Dict[str, Any]]:
    """Busca parcelas que vencem na data de hoje (Servidor)."""
    hoje = date.today().isoformat()
    print(f"DEBUG: Buscando parcelas vencendo hoje: {hoje}")
    try:
        response = supabase.table("parcelas") \
            .select("*, apolices(cliente, numero_apolice, contato, placa)") \
            .eq("status", "Pendente") \
            .eq("data_vencimento", hoje) \
            .execute()
        print(f"DEBUG: Parcelas encontradas: {response.data}")
        return response.data
    except Exception as e:
        print(f"Erro ao buscar parcelas de hoje: {e}")
        return []


def buscar_parcela_atual(numero_apolice: str) -> Union[Dict[str, Any], None]:
    """
    Busca a próxima parcela pendente de uma apólice específica.
    Retorna os dados da parcela + o link do PDF da apólice.
    """
    try:
        # 1. Achar o ID da apólice pelo número
        res_apolice = supabase.table("apolices") \
            .select("id, caminho_pdf_boletos, cliente") \
            .eq("numero_apolice", numero_apolice) \
            .execute()

        if not res_apolice.data:
            print(f"Apólice {numero_apolice} não encontrada.")
            return None

        apolice_data = res_apolice.data[0]
        apolice_id = apolice_data['id']

        # 2. Achar a primeira parcela pendente dessa apólice (ordenada por vencimento)
        # Usamos gte (maior ou igual) hoje para pegar a próxima válida
        hoje = date.today().isoformat()

        res_parcela = supabase.table("parcelas") \
            .select("*") \
            .eq("apolice_id", apolice_id) \
            .eq("status", "Pendente") \
            .gte("data_vencimento", hoje) \
            .order("data_vencimento") \
            .limit(1) \
            .execute()

        # Se não achou futura, tenta pegar qualquer pendente (pode estar atrasada)
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
            # Injeta os dados da apólice junto para facilitar
            dados['caminho_pdf_boletos'] = apolice_data.get('caminho_pdf_boletos')
            dados['data_vencimento_atual'] = dados['data_vencimento']
            dados['apolices'] = {'cliente': apolice_data['cliente']}
            return dados

        return None

    except Exception as e:
        print(f"Erro ao buscar parcela atual para apólice {numero_apolice}: {e}")
        return None


def atualizar_status_pagamento(numero_apolice: str, data_vencimento: date) -> bool:
    """Dá baixa em uma parcela específica."""
    try:
        # Precisa achar o ID da apólice primeiro
        res_apolice = supabase.table("apolices").select("id").eq("numero_apolice", numero_apolice).execute()
        if not res_apolice.data: return False

        apolice_id = res_apolice.data[0]['id']

        data_str = data_vencimento.isoformat() if isinstance(data_vencimento, date) else data_vencimento

        response = supabase.table("parcelas") \
            .update({"status": "Pago", "data_pagamento": date.today().isoformat()}) \
            .eq("apolice_id", apolice_id) \
            .eq("data_vencimento", data_str) \
            .execute()

        return len(response.data) > 0
    except Exception as e:
        print(f"Erro ao atualizar pagamento: {e}")
        return False


def get_apolices(search_term=None):
    """Busca apólices para o painel (função legado do app.py)."""
    query = supabase.table('apolices').select('*')
    if search_term:
        query = query.or_(
            f"numero_apolice.ilike.%{search_term}%,cliente.ilike.%{search_term}%,placa.ilike.%{search_term}%")

    response = query.execute()

    import pandas as pd  # Import local para não quebrar scripts leves
    if response.data:
        df = pd.DataFrame(response.data)
        # Recalcula dias restantes
        df['data_final_de_vigencia'] = pd.to_datetime(df['data_inicio_vigencia']) + pd.to_timedelta(365, unit='D')
        df['dias_restantes'] = (df['data_final_de_vigencia'].dt.date - date.today()).apply(lambda x: x.days)

        def definir_prioridade(dias):
            if dias < 0:
                return '⚪ Expirada'
            elif dias <= 15:
                return '🔥 Urgente'
            elif dias <= 30:
                return '⚠️ Alta'
            elif dias <= 60:
                return '⚠️ Média'
            else:
                return '✅ Baixa'

        df['prioridade'] = df['dias_restantes'].apply(definir_prioridade)
        return df
    return pd.DataFrame()


# --- NOVA FUNÇÃO DE DOWNLOAD ROBUSTA ---

def baixar_pdf_bytes(caminho_ou_url: str) -> Union[bytes, None]:
    """
    Baixa o arquivo PDF.
    Inteligente: Detecta se é uma URL pública (http) ou um caminho interno.
    """
    if not caminho_ou_url:
        print("Erro: Caminho do PDF é vazio.")
        return None

    print(f"⬇️ Tentando baixar PDF de: {caminho_ou_url}")

    try:
        # CENÁRIO 1: É uma URL completa (Links Públicos gerados pelo seu App)
        if caminho_ou_url.startswith("http"):
            response = requests.get(caminho_ou_url, timeout=15)
            if response.status_code == 200:
                print("✅ Download via URL bem sucedido!")
                return response.content
            else:
                print(f"❌ Erro ao baixar via URL. Status: {response.status_code}")
                return None

        # CENÁRIO 2: É um caminho interno do Bucket (caso antigo)
        else:
            bucket_name = "moreiraseg-apolices-pdfs-2025"  # Seu bucket padrão
            data = supabase.storage.from_(bucket_name).download(caminho_ou_url)
            print("✅ Download via Storage interno bem sucedido!")
            return data

    except Exception as e:
        print(f"❌ Exceção ao baixar PDF: {e}")
        return None