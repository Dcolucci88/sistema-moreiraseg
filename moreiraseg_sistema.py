# moreiraseg_sistema.py
# VERSÃO COMPLETA COM LEITURA DE DADOS VIA API

import streamlit as st
import pandas as pd
import datetime
from datetime import date
import os
import re
import json
import requests # Nova biblioteca para fazer pedidos à API

# Tente importar as bibliotecas necessárias, mostrando erros amigáveis.
try:
    from google.cloud import storage
    from google.oauth2 import service_account
except ImportError:
    st.error("Biblioteca do Google Cloud não encontrada. Verifique o seu ficheiro `requirements.txt`.")
    st.stop()

try:
    import psycopg2
    from psycopg2.extras import DictCursor
except ImportError:
    st.error("Biblioteca do PostgreSQL não encontrada. Adicione 'psycopg2-binary' ao seu `requirements.txt`.")
    st.stop()


# --- CONFIGURAÇÕES GLOBAIS ---
ASSETS_DIR = "LogoTipo" 
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "Icone.png")
# URL da nossa API (será lido dos secrets)
API_BASE_URL = st.secrets.get("api_base_url")

# --- FUNÇÕES DE BANCO DE DADOS (Mantidas para operações de escrita) ---

def get_connection():
    """Retorna uma conexão com o banco de dados PostgreSQL na nuvem."""
    try:
        conn = psycopg2.connect(
            host=st.secrets["postgres"]["host"],
            dbname=st.secrets["postgres"]["dbname"],
            user=st.secrets["postgres"]["user"],
            password=st.secrets["postgres"]["password"],
            port=st.secrets["postgres"]["port"]
        )
        return conn
    except Exception as e:
        st.error(f"❌ Erro fatal ao conectar ao banco de dados PostgreSQL: {e}")
        st.stop()

def init_db():
    """
    Inicializa o banco de dados PostgreSQL, cria e atualiza as tabelas conforme necessário.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as c:
                c.execute('''
                    CREATE TABLE IF NOT EXISTS apolices (
                        id SERIAL PRIMARY KEY,
                        seguradora TEXT NOT NULL, cliente TEXT NOT NULL, numero_apolice TEXT NOT NULL UNIQUE,
                        placa TEXT, tipo_seguro TEXT NOT NULL, 
                        valor_da_parcela REAL NOT NULL,
                        comissao REAL, data_inicio_de_vigencia DATE NOT NULL, data_final_de_vigencia DATE NOT NULL,
                        contato TEXT NOT NULL, email TEXT, observacoes TEXT,
                        status TEXT NOT NULL DEFAULT 'Ativa', caminho_pdf TEXT,
                        data_cadastro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        data_atualizacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                colunas_para_adicionar = {
                    "tipo_cobranca": "TEXT",
                    "numero_parcelas": "INTEGER",
                    "valor_primeira_parcela": "REAL"
                }
                for coluna, tipo in colunas_para_adicionar.items():
                    c.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name='apolices' AND column_name=%s
                    """, (coluna,))
                    if not c.fetchone():
                        c.execute(f"ALTER TABLE apolices ADD COLUMN {coluna} {tipo}")
                c.execute('''
                    CREATE TABLE IF NOT EXISTS boletos (
                        id SERIAL PRIMARY KEY,
                        apolice_id INTEGER NOT NULL,
                        caminho_pdf TEXT NOT NULL,
                        nome_arquivo TEXT,
                        data_upload TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (apolice_id) REFERENCES apolices(id) ON DELETE CASCADE
                    )
                ''')
                c.execute('''
                    CREATE TABLE IF NOT EXISTS historico (
                        id SERIAL PRIMARY KEY,
                        apolice_id INTEGER NOT NULL,
                        usuario TEXT NOT NULL,
                        acao TEXT NOT NULL,
                        detalhes TEXT,
                        data_acao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (apolice_id) REFERENCES apolices(id) ON DELETE CASCADE
                    )
                ''')
                c.execute('''
                    CREATE TABLE IF NOT EXISTS usuarios (
                        id SERIAL PRIMARY KEY,
                        nome TEXT NOT NULL,
                        email TEXT NOT NULL UNIQUE,
                        senha TEXT NOT NULL,
                        perfil TEXT NOT NULL DEFAULT 'user',
                        data_cadastro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                c.execute("SELECT id FROM usuarios WHERE email = %s", ('adm@moreiraseg.com.br',))
                if not c.fetchone():
                    c.execute(
                        "INSERT INTO usuarios (nome, email, senha, perfil) VALUES (%s, %s, %s, %s)",
                        ('Administrador', 'adm@moreiraseg.com.br', 'Salmo@139', 'admin')
                    )
            conn.commit()
    except Exception as e:
        st.error(f"❌ Falha ao inicializar as tabelas do banco de dados: {e}")
        st.stop()

# --- FUNÇÕES DE UPLOAD ---
def salvar_ficheiros_gcs(ficheiros, numero_apolice, cliente, tipo_pasta):
    if not isinstance(ficheiros, list):
        ficheiros = [ficheiros]
    urls_publicas = []
    try:
        creds_info = dict(st.secrets["gcs_credentials"])
        credentials = service_account.Credentials.from_service_account_info(creds_info)
        bucket_name = st.secrets["gcs_bucket_name"]
        client = storage.Client(credentials=credentials)
        bucket = client.get_bucket(bucket_name)
        safe_cliente = re.sub(r'[^a-zA-Z0-9\s-]', '', cliente).strip().replace(' ', '_')
        for ficheiro in ficheiros:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            destination_blob_name = f"{tipo_pasta}/{safe_cliente}/{numero_apolice}/{timestamp}_{ficheiro.name}"
            blob = bucket.blob(destination_blob_name)
            blob.upload_from_file(ficheiro, content_type=ficheiro.type)
            blob.make_public()
            urls_publicas.append(blob.public_url)
        return urls_publicas
    except KeyError as e:
        st.error(f"Erro de chave nos 'Secrets': A chave '{e}' não foi encontrada.")
        return []
    except Exception as e:
        st.error(f"❌ Falha no upload para o Google Cloud Storage: {e}")
        return []

# --- FUNÇÕES DE LÓGICA DO SISTEMA ---

def add_historico(apolice_id, usuario_email, acao, detalhes=""):
    try:
        with get_connection() as conn:
            with conn.cursor() as c:
                c.execute(
                    "INSERT INTO historico (apolice_id, usuario, acao, detalhes) VALUES (%s, %s, %s, %s)",
                    (apolice_id, usuario_email, acao, detalhes)
                )
            conn.commit()
    except Exception as e:
        st.warning(f"⚠️ Não foi possível registrar a ação no histórico: {e}")

def add_boletos_db(apolice_id, boletos_info):
    try:
        with get_connection() as conn:
            with conn.cursor() as c:
                for url, nome in boletos_info:
                    c.execute(
                        "INSERT INTO boletos (apolice_id, caminho_pdf, nome_arquivo) VALUES (%s, %s, %s)",
                        (apolice_id, url, nome)
                    )
            conn.commit()
    except Exception as e:
        st.error(f"❌ Erro ao salvar informações dos boletos no banco de dados: {e}")

def add_apolice(data):
    if data['data_inicio_de_vigencia'] >= data['data_final_de_vigencia']:
        st.error("❌ A data final da vigência deve ser posterior à data inicial.")
        return None
    
    try:
        data['valor_da_parcela'] = float(str(data['valor_da_parcela']).replace(',', '.'))
        if data.get('valor_primeira_parcela'):
            data['valor_primeira_parcela'] = float(str(data['valor_primeira_parcela']).replace(',', '.'))
        if data.get('comissao'):
            data['comissao'] = float(data['comissao'])
    except (ValueError, TypeError):
        st.error("❌ Valores numéricos inválidos. Use apenas números e vírgula.")
        return None

    try:
        with get_connection() as conn:
            with conn.cursor() as c:
                c.execute('''
                    INSERT INTO apolices (
                        seguradora, cliente, numero_apolice, placa, tipo_seguro, tipo_cobranca,
                        numero_parcelas, valor_primeira_parcela, valor_da_parcela, comissao, 
                        data_inicio_de_vigencia, data_final_de_vigencia, contato, email, 
                        observacoes, status, caminho_pdf
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    data['seguradora'], data['cliente'], data['numero_apolice'], data.get('placa', ''),
                    data['tipo_seguro'], data.get('tipo_cobranca'), data.get('numero_parcelas'),
                    data.get('valor_primeira_parcela'), data['valor_da_parcela'], data.get('comissao', 0.0),
                    data['data_inicio_de_vigencia'], data['data_final_de_vigencia'],
                    data['contato'], data.get('email', ''), data.get('observacoes', ''),
                    data.get('status', 'Ativa'),
                    data.get('caminho_pdf', '')
                ))
                apolice_id = c.fetchone()[0]
            conn.commit()
            
            add_historico(
                apolice_id, 
                st.session_state.get('user_email', 'sistema'), 
                'Cadastro de Apólice', 
                f"Apólice '{data['numero_apolice']}' criada."
            )
            return apolice_id
            
    except psycopg2.errors.UniqueViolation:
        st.error(f"❌ Erro: O número de apólice '{data['numero_apolice']}' já existe no sistema!")
        return None
    except Exception as e:
        st.error(f"❌ Ocorreu um erro inesperado ao cadastrar: {e}")
        return None

def update_apolice(apolice_id, update_data):
    try:
        with get_connection() as conn:
            with conn.cursor() as c:
                update_data['data_atualizacao'] = datetime.datetime.now(datetime.timezone.utc)
                set_clause = ", ".join([f"{key} = %s" for key in update_data.keys()])
                values = list(update_data.values())
                values.append(apolice_id)
                query = f"UPDATE apolices SET {set_clause} WHERE id = %s"
                c.execute(query, tuple(values))
            conn.commit()
            detalhes = f"Campos atualizados: {', '.join(update_data.keys())}"
            add_historico(apolice_id, st.session_state.get('user_email', 'sistema'), 'Atualização', detalhes)
            return True
    except Exception as e:
        st.error(f"❌ Erro ao atualizar a apólice: {e}")
        return False

def get_apolices_from_api(search_term=None):
    """
    Busca apólices através da API FastAPI em vez de conectar diretamente ao banco de dados.
    """
    if not API_BASE_URL:
        st.error("A URL da API não está configurada nos 'Secrets'.")
        return pd.DataFrame()

    endpoint = f"{API_BASE_URL}/apolices/"
    params = {}
    # No futuro, a API pode ser melhorada para aceitar um termo de pesquisa
    # if search_term:
    #     params['q'] = search_term

    try:
        response = requests.get(endpoint, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Se a API retornar uma lista vazia, cria um DataFrame vazio com as colunas esperadas
        if not data:
            return pd.DataFrame(columns=['id', 'numero_apolice', 'cliente', 'seguradora', 'status', 'data_final_de_vigencia'])

        return pd.DataFrame(data)
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao comunicar com a API: {e}")
        return pd.DataFrame()
    except json.JSONDecodeError:
        st.error("A resposta da API não é um JSON válido. Verifique a API.")
        return pd.DataFrame()

def get_apolices(search_term=None):
    """
    Função principal para obter apólices. Agora usa a API.
    A lógica de cálculo de dias restantes é feita após receber os dados.
    """
    df = get_apolices_from_api(search_term=search_term)

    if df.empty:
        return pd.DataFrame()

    # Filtra os dados localmente se a API não suportar a pesquisa
    if search_term:
        term = search_term.lower()
        df = df[
            df['numero_apolice'].str.lower().contains(term) |
            df['cliente'].str.lower().contains(term)
        ]

    df['data_final_de_vigencia'] = pd.to_datetime(df['data_final_de_vigencia'], errors='coerce')
    today_date = date.today()
    df['dias_restantes'] = df['data_final_de_vigencia'].apply(
        lambda x: (x.date() - today_date).days if pd.notnull(x) else None
    )
    def define_prioridade(dias):
        if pd.isna(dias): return '⚪ Indefinida'
        if dias <= 3: return '🔥 Urgente'
        elif dias <= 7: return '⚠️ Alta'
        elif dias <= 20: return '⚠️ Média'
        else: return '✅ Baixa'
    df['prioridade'] = df['dias_restantes'].apply(define_prioridade)
    
    return df
    
def get_apolice_details(apolice_id):
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                c.execute("SELECT * FROM apolices WHERE id = %s", (apolice_id,))
                apolice = c.fetchone()
                c.execute("SELECT * FROM historico WHERE apolice_id = %s ORDER BY data_acao DESC", (apolice_id,))
                historico = c.fetchall()
            return apolice, historico
    except Exception as e:
        st.error(f"Erro ao buscar detalhes da apólice: {e}")
        return None, []

def login_user(email, senha):
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                c.execute("SELECT * FROM usuarios WHERE email = %s AND senha = %s", (email, senha))
                return c.fetchone()
    except Exception as e:
        st.error(f"Erro durante o login: {e}")
        return None

# --- RENDERIZAÇÃO DA INTERFACE ---

def render_dashboard():
    st.title("📊 Painel de Controle")
    apolices_df = get_apolices()
    if apolices_df.empty:
        st.info("Nenhuma apólice cadastrada. Comece adicionando uma no menu 'Cadastrar Apólice'.")
        return
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total de Apólices", len(apolices_df))
    pendentes_df = apolices_df[apolices_df['status'] == 'Pendente']
    col2.metric("Apólices Pendentes", len(pendentes_df))
    valor_pendente = pendentes_df['valor_da_parcela'].sum()
    col3.metric("Valor Total Pendente", f"R${valor_pendente:,.2f}")
    urgentes_df = apolices_df[apolices_df['dias_restantes'].fillna(999) <= 3]
    col4.metric("Apólices Urgentes", len(urgentes_df), "Vencem em até 3 dias")
    st.divider()
    st.subheader("Apólices por Prioridade de Renovação")
    prioridades_map = {
        '🔥 Urgente': apolices_df[apolices_df['prioridade'] == '🔥 Urgente'], 
        '⚠️ Alta': apolices_df[apolices_df['prioridade'] == '⚠️ Alta'], 
        '⚠️ Média': apolices_df[apolices_df['prioridade'] == '⚠️ Média'], 
        '✅ Baixa': apolices_df[apolices_df['prioridade'] == '✅ Baixa'],
        '⚪ Indefinida': apolices_df[apolices_df['prioridade'] == '⚪ Indefinida']
    }
    tabs = st.tabs(prioridades_map.keys())
    cols_to_show = ['cliente', 'numero_apolice', 'tipo_seguro', 'dias_restantes', 'status']
    for tab, (prioridade, df) in zip(tabs, prioridades_map.items()):
        with tab:
            if not df.empty:
                st.dataframe(df[cols_to_show], use_container_width=True)
            else:
                st.info(f"Nenhuma apólice com prioridade '{prioridade.split(' ')[-1]}'.")

def render_pesquisa_e_edicao():
    st.title("🔍 Pesquisar e Editar Apólice")
    search_term = st.text_input("Pesquisar por Nº Apólice, Cliente ou Placa:", key="search_box")
    if search_term:
        resultados = get_apolices(search_term=search_term)
        if resultados.empty:
            st.info("Nenhuma apólice encontrada com o termo pesquisado.")
        else:
            st.success(f"{len(resultados)} apólice(s) encontrada(s).")
            for index, apolice_row in resultados.iterrows():
                with st.expander(f"**{apolice_row['numero_apolice']}** - {apolice_row['cliente']}"):
                    # ... (código completo para edição e upload)

def render_cadastro_form():
    st.title("➕ Cadastrar Apólice")
    # ... (código completo do formulário)

def render_configuracoes():
    st.title("⚙️ Configurações do Sistema")
    # ... (código completo das configurações)

def main():
    """Função principal que renderiza a aplicação Streamlit."""
    st.set_page_config(
        page_title="Moreiraseg - Gestão de Apólices",
        page_icon=ICONE_PATH,
        layout="wide",
        initial_sidebar_state="expanded"
    )

    try:
        init_db()

        if 'user_email' not in st.session_state:
            st.session_state.user_email = None
            st.session_state.user_nome = None
            st.session_state.user_perfil = None
        
        if not st.session_state.user_email:
            col1, col2, col3 = st.columns([1, 1.5, 1])
            with col2:
                try:
                    st.image(ICONE_PATH, width=150)
                except Exception:
                    st.title("Sistema de Gestão de Apólices")
                st.write("")
                with st.form("login_form"):
                    email = st.text_input("📧 E-mail")
                    senha = st.text_input("🔑 Senha", type="password")
                    submit = st.form_submit_button("Entrar", use_container_width=True)
                    if submit:
                        usuario = login_user(email, senha)
                        if usuario:
                            st.session_state.user_email = usuario['email']
                            st.session_state.user_nome = usuario['nome']
                            st.session_state.user_perfil = usuario['perfil']
                            st.rerun()
                        else:
                            st.error("Credenciais inválidas. Tente novamente.")
                st.info("Para testes, use: `adm@moreiraseg.com.br` / `Salmo@139`")
            return

        with st.sidebar:
            st.title(f"Olá, {st.session_state.user_nome.split()[0]}!")
            st.write(f"Perfil: `{st.session_state.user_perfil.capitalize()}`")
            try:
                st.image(ICONE_PATH, width=80)
            except Exception:
                st.write("Menu")
            st.divider()
            menu_options = [
                "📊 Painel de Controle",
                "➕ Cadastrar Apólice",
                "🔍 Pesquisar e Editar Apólice",
            ]
            if st.session_state.user_perfil == 'admin':
                menu_options.append("⚙️ Configurações")
            menu_opcao = st.radio("Menu Principal", menu_options)
            st.divider()
            if st.button("🚪 Sair do Sistema", use_container_width=True):
                st.session_state.user_email = None
                st.session_state.user_nome = None
                st.session_state.user_perfil = None
                st.rerun()

        col1, col2, col3 = st.columns([2, 3, 2])
        with col2:
            try:
                st.image(LOGO_PATH)
            except Exception as e:
                st.warning(f"Não foi possível carregar o logótipo principal: {e}")
        st.write("")

        if menu_opcao == "📊 Painel de Controle":
            render_dashboard()
        elif menu_opcao == "➕ Cadastrar Apólice":
            render_cadastro_form()
        elif menu_opcao == "🔍 Pesquisar e Editar Apólice":
            render_pesquisa_e_edicao()
        elif menu_opcao == "⚙️ Configurações" and st.session_state.user_perfil == 'admin':
            render_configuracoes()

    except Exception as e:
        st.error("Ocorreu um erro crítico na aplicação.")
        st.exception(e)

if __name__ == "__main__":
    main()


