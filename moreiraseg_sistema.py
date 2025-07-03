# moreiraseg_sistema.py
# VERSÃO COM PESQUISA E EDIÇÃO INTEGRADA

import streamlit as st
import pandas as pd
import datetime
from datetime import date
import os
import re
import json

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

# --- FUNÇÕES DE BANCO DE DADOS (ATUALIZADAS PARA POSTGRESQL) ---

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
    Inicializa o banco de dados PostgreSQL, cria as tabelas se não existirem.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as c:
                # Adicionados os novos campos na tabela apolices
                c.execute('''
                    CREATE TABLE IF NOT EXISTS apolices (
                        id SERIAL PRIMARY KEY,
                        seguradora TEXT NOT NULL, cliente TEXT NOT NULL, numero_apolice TEXT NOT NULL UNIQUE,
                        placa TEXT, tipo_seguro TEXT NOT NULL, 
                        tipo_cobranca TEXT,
                        numero_parcelas INTEGER,
                        valor_primeira_parcela REAL,
                        valor_da_parcela REAL NOT NULL,
                        comissao REAL, data_inicio_de_vigencia DATE NOT NULL, data_final_de_vigencia DATE NOT NULL,
                        contato TEXT NOT NULL, email TEXT, observacoes TEXT,
                        status TEXT NOT NULL DEFAULT 'Pendente', caminho_pdf TEXT,
                        data_cadastro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        data_atualizacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
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
    """
    Faz o upload de uma lista de ficheiros para uma pasta específica no GCS.
    """
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
    """Adiciona os links dos boletos ao banco de dados."""
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
                    data.get('status', 'Pendente'), data.get('caminho_pdf', '')
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

def get_apolices(search_term=None):
    try:
        with get_connection() as conn:
            query = "SELECT * FROM apolices"
            params = []
            if search_term:
                query += " WHERE numero_apolice ILIKE %s OR cliente ILIKE %s OR placa ILIKE %s"
                like_term = f"%{search_term}%"
                params = [like_term, like_term, like_term]
            
            query += " ORDER BY data_final_de_vigencia ASC"
            df = pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        st.error(f"Erro ao carregar apólices: {e}")
        return pd.DataFrame()

    if not df.empty:
        df['data_final_de_vigencia_dt'] = pd.to_datetime(df['data_final_de_vigencia'], errors='coerce')
        df['dias_restantes'] = (df['data_final_de_vigencia_dt'] - pd.Timestamp.now(df['data_final_de_vigencia_dt'].dt.tz)).dt.days
        def define_prioridade(dias):
            if pd.isna(dias): return '⚪ Indefinida'
            if dias <= 3: return '🔥 Urgente'
            elif dias <= 7: return '⚠️ Alta'
            elif dias <= 20: return '⚠️ Média'
            else: return '✅ Baixa'
        df['prioridade'] = df['dias_restantes'].apply(define_prioridade)
        df.drop(columns=['data_final_de_vigencia_dt'], inplace=True)
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
    # ... (código inalterado)

def render_pesquisa_e_edicao():
    """Nova página que combina pesquisa e edição de apólices."""
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
                    apolice_id = apolice_row['id']
                    
                    st.subheader("📝 Editar Informações da Apólice")
                    with st.form(f"edit_form_{apolice_id}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            novo_valor_parcelas = st.text_input("Valor das Demais Parcelas (R$)", value=f"{apolice_row.get('valor_da_parcela', 0.0):.2f}")
                            novo_contato = st.text_input("Contato do Cliente", value=apolice_row.get('contato', ''))
                        with col2:
                            novo_num_parcelas = st.number_input("Nº de Parcelas", min_value=1, max_value=12, value=int(apolice_row.get('numero_parcelas', 1)))
                            novo_email = st.text_input("E-mail do Cliente", value=apolice_row.get('email', ''))
                        
                        edit_submitted = st.form_submit_button("Salvar Alterações")
                        if edit_submitted:
                            update_data = {
                                'valor_da_parcela': float(novo_valor_parcelas.replace(',', '.')),
                                'numero_parcelas': novo_num_parcelas,
                                'contato': novo_contato,
                                'email': novo_email
                            }
                            if update_apolice(apolice_id, update_data):
                                st.success("Informações da apólice atualizadas com sucesso!")
                                st.rerun()

                    st.divider()
                    st.subheader("📁 Gerenciar Anexos")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        with st.form(f"apolice_upload_form_{apolice_id}"):
                            st.write("**Atualizar Apólice (PDF)**")
                            apolice_pdf_file = st.file_uploader("Selecione a nova versão da apólice", type=["pdf"], key=f"apolice_pdf_{apolice_id}")
                            apolice_upload_submitted = st.form_submit_button("Substituir PDF da Apólice")
                            
                            if apolice_upload_submitted and apolice_pdf_file:
                                st.info("Fazendo upload da nova apólice...")
                                novo_caminho = salvar_ficheiros_gcs([apolice_pdf_file], apolice_row['numero_apolice'], apolice_row['cliente'], 'apolices')
                                if novo_caminho:
                                    if update_apolice(apolice_id, {'caminho_pdf': novo_caminho[0]}):
                                        st.success("PDF da apólice substituído com sucesso!")
                                        st.rerun()
                    
                    with col2:
                        with st.form(f"boleto_upload_form_{apolice_id}"):
                            st.write("**Anexar Novo Boleto**")
                            boleto_pdf_file = st.file_uploader("Selecione o novo boleto", type=["pdf"], key=f"boleto_pdf_{apolice_id}")
                            boleto_upload_submitted = st.form_submit_button("Anexar Boleto")

                            if boleto_upload_submitted and boleto_pdf_file:
                                st.info("Fazendo upload do boleto...")
                                novo_caminho_boleto = salvar_ficheiros_gcs([boleto_pdf_file], apolice_row['numero_apolice'], apolice_row['cliente'], 'boletos')
                                if novo_caminho_boleto:
                                    add_boletos_db(apolice_id, [(novo_caminho_boleto[0], boleto_pdf_file.name)])
                                    st.success("Novo boleto anexado com sucesso!")
                                    st.rerun()


def render_cadastro_form():
    # ... (código inalterado)

def render_configuracoes():
    # ... (código inalterado)

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
            # ... (código de login inalterado)
            return

        with st.sidebar:
            st.title(f"Olá, {st.session_state.user_nome.split()[0]}!")
            st.write(f"Perfil: `{st.session_state.user_perfil.capitalize()}`")
            try:
                st.image(ICONE_PATH, width=80)
            except Exception:
                st.write("Menu")
            st.divider()
            # Menu atualizado para refletir a nova página
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
