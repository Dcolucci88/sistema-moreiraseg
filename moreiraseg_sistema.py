# moreiraseg_sistema.py
import streamlit as st
import sqlite3
import pandas as pd
import datetime
from datetime import date
import os
import re
import json # Importado para lidar com as credenciais

# Tente importar a biblioteca do Google Cloud, se não existir, mostre um erro amigável.
try:
    from google.cloud import storage
    from google.oauth2 import service_account
except ImportError:
    st.error("Biblioteca do Google Cloud não encontrada. Por favor, instale com: pip install google-cloud-storage google-auth")
    st.stop()


# --- CONFIGURAÇÕES GLOBAIS ---

# Nome do arquivo do banco de dados (continuará local por enquanto)
DB_NAME = "moreiraseg.db"

# Caminhos relativos para os assets
ASSETS_DIR = "assets"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "icone.png")

# --- FUNÇÕES DE BANCO DE DADOS ---

def get_connection():
    """Retorna uma conexão com o banco de dados SQLite."""
    return sqlite3.connect(DB_NAME, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)

def init_db():
    """
    Inicializa o banco de dados, cria as tabelas se não existirem.
    """
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS apolices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seguradora TEXT NOT NULL, cliente TEXT NOT NULL, numero_apolice TEXT NOT NULL UNIQUE,
                    placa TEXT, tipo_seguro TEXT NOT NULL, valor_da_parcela REAL NOT NULL,
                    comissao REAL, data_inicio_de_vigencia DATE NOT NULL, data_final_de_vigencia DATE NOT NULL,
                    contato TEXT NOT NULL, email TEXT, observacoes TEXT,
                    status TEXT NOT NULL DEFAULT 'Pendente', caminho_pdf TEXT,
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP, data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                CREATE TRIGGER IF NOT EXISTS update_apolices_timestamp
                AFTER UPDATE ON apolices FOR EACH ROW
                BEGIN UPDATE apolices SET data_atualizacao = CURRENT_TIMESTAMP WHERE id = OLD.id; END;
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, apolice_id INTEGER NOT NULL, usuario TEXT NOT NULL,
                    acao TEXT NOT NULL, detalhes TEXT, data_acao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (apolice_id) REFERENCES apolices(id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                    senha TEXT NOT NULL, perfil TEXT NOT NULL DEFAULT 'user',
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute("SELECT id FROM usuarios WHERE email = ?", ('adm@moreiraseg.com.br',))
            if not c.fetchone():
                c.execute(
                    "INSERT INTO usuarios (nome, email, senha, perfil) VALUES (?, ?, ?, ?)",
                    ('Administrador', 'adm@moreiraseg.com.br', 'Salmo@139', 'admin')
                )
            conn.commit()
    except Exception as e:
        st.error(f"❌ Falha ao inicializar o banco de dados: {e}")
        st.stop()

# --- FUNÇÃO DE UPLOAD PARA O GOOGLE CLOUD STORAGE (CORRIGIDA) ---

def salvar_pdf_gcs(uploaded_file, numero_apolice, cliente):
    """
    Faz o upload de um arquivo PDF para o Google Cloud Storage e retorna a URL pública.
    """
    try:
        creds_json_str = st.secrets["gcs_credentials"]
        creds_info = json.loads(creds_json_str)
        credentials = service_account.Credentials.from_service_account_info(creds_info)
        
        bucket_name = st.secrets["gcs_bucket_name"]

        client = storage.Client(credentials=credentials)
        bucket = client.get_bucket(bucket_name)

        safe_cliente = re.sub(r'[^a-zA-Z0-9\s-]', '', cliente).strip().replace(' ', '_')
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        destination_blob_name = f"apolices/{safe_cliente}/{numero_apolice}/{timestamp}_{uploaded_file.name}"

        blob = bucket.blob(destination_blob_name)
        
        # Faz o upload do arquivo
        blob.upload_from_file(uploaded_file, content_type='application/pdf')
        
        # **CORREÇÃO APLICADA AQUI**
        # Torna o arquivo publicamente legível para que o link funcione
        blob.make_public()

        # Retorna a URL pública do arquivo
        return blob.public_url

    except KeyError:
        st.error("Credenciais do Google Cloud Storage ou nome do bucket não configurados nos 'Secrets' do Streamlit.")
        st.info("Por favor, siga as instruções de configuração para adicionar 'gcs_credentials' e 'gcs_bucket_name' aos segredos do seu app.")
        return None
    except Exception as e:
        st.error(f"❌ Falha no upload para o Google Cloud Storage: {e}")
        return None

# --- FUNÇÕES RESTANTES DO SISTEMA ---

def add_historico(apolice_id, usuario_email, acao, detalhes=""):
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO historico (apolice_id, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                (apolice_id, usuario_email, acao, detalhes)
            )
            conn.commit()
    except Exception as e:
        st.warning(f"⚠️ Não foi possível registrar a ação no histórico: {e}")

def add_apolice(data):
    if data['data_inicio_de_vigencia'] >= data['data_final_de_vigencia']:
        st.error("❌ A data final da vigência deve ser posterior à data inicial.")
        return False
    
    try:
        data['valor_da_parcela'] = float(str(data['valor_da_parcela']).replace(',', '.'))
        if data.get('comissao'):
            data['comissao'] = float(str(data['comissao']).replace(',', '.'))
    except (ValueError, TypeError):
        st.error("❌ Valor da parcela ou comissão inválido. Use apenas números e vírgula.")
        return False

    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO apolices (
                    seguradora, cliente, numero_apolice, placa, tipo_seguro,
                    valor_da_parcela, comissao, data_inicio_de_vigencia,
                    data_final_de_vigencia, contato, email, observacoes, status, caminho_pdf
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['seguradora'], data['cliente'], data['numero_apolice'], data.get('placa', ''),
                data['tipo_seguro'], data['valor_da_parcela'], data.get('comissao', 0.0),
                data['data_inicio_de_vigencia'], data['data_final_de_vigencia'],
                data['contato'], data.get('email', ''), data.get('observacoes', ''),
                data.get('status', 'Pendente'), data.get('caminho_pdf', '')
            ))
            apolice_id = c.lastrowid
            conn.commit()
            
            add_historico(
                apolice_id, 
                st.session_state.get('user_email', 'sistema'), 
                'Cadastro de Apólice', 
                f"Apólice '{data['numero_apolice']}' criada."
            )
            return True
            
    except sqlite3.IntegrityError:
        st.error(f"❌ Erro: O número de apólice '{data['numero_apolice']}' já existe no sistema!")
        return False
    except Exception as e:
        st.error(f"❌ Ocorreu um erro inesperado ao cadastrar: {e}")
        return False

def get_apolices():
    try:
        with get_connection() as conn:
            df = pd.read_sql_query("SELECT * FROM apolices ORDER BY data_final_de_vigencia ASC", conn)
    except Exception as e:
        st.error(f"Erro ao carregar apólices: {e}")
        return pd.DataFrame()

    if not df.empty:
        df['data_final_de_vigencia_dt'] = pd.to_datetime(df['data_final_de_vigencia'], errors='coerce')
        df['dias_restantes'] = (df['data_final_de_vigencia_dt'] - pd.Timestamp.now()).dt.days
        def define_prioridade(dias):
            if pd.isna(dias): return '⚪ Indefinida'
            if dias <= 3: return '🔥 Urgente'
            elif dias <= 7: return '⚠️ Alta'
            elif dias <= 20: return '⚠️ Média'
            else: return '✅ Baixa'
        df['prioridade'] = df['dias_restantes'].apply(define_prioridade)
        df.drop(columns=['data_final_de_vigencia_dt'], inplace=True)
    return df

def login_user(email, senha):
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM usuarios WHERE email = ? AND senha = ?", (email, senha))
            return c.fetchone()
    except Exception as e:
        st.error(f"Erro durante o login: {e}")
        return None

# --- RENDERIZAÇÃO DA INTERFACE ---

def render_cadastro_form():
    """Renderiza o formulário para cadastrar uma nova apólice."""
    st.title("➕ Cadastrar Nova Apólice")
    
    with st.form("form_cadastro", clear_on_submit=True):
        st.subheader("Dados da Apólice")
        col1, col2 = st.columns(2)
        with col1:
            seguradora = st.text_input("Seguradora*", max_chars=50)
            numero_apolice = st.text_input("Número da Apólice*", max_chars=50)
            placa = st.text_input("🚗 Placa do Veículo (se aplicável)", max_chars=10)
            data_inicio = st.date_input("📅 Início de Vigência*")
        with col2:
            cliente = st.text_input("Cliente*", max_chars=100)
            tipo_seguro = st.selectbox("Tipo de Seguro*", ["Automóvel", "RCO", "Vida", "Residencial", "Empresarial", "Saúde", "Viagem", "Fiança", "Outro"])
            valor_parcela = st.text_input("💰 Valor da Parcela (R$)*", value="0,00")
            data_fim = st.date_input("📅 Fim de Vigência*", min_value=data_inicio + datetime.timedelta(days=1) if data_inicio else date.today())

        st.subheader("Dados de Contato e Outros")
        col1, col2 = st.columns(2)
        with col1:
            contato = st.text_input("📱 Contato do Cliente*", max_chars=100)
            comissao = st.text_input("💼 Comissão (R$)", value="0,00")
        with col2:
            email = st.text_input("📧 E-mail do Cliente", max_chars=100)

        observacoes = st.text_area("📝 Observações", height=100)
        pdf_file = st.file_uploader("📎 Anexar PDF da Apólice (Opcional)", type=["pdf"])

        submitted = st.form_submit_button("💾 Salvar Apólice", use_container_width=True)
        if submitted:
            if not all([seguradora, cliente, numero_apolice, valor_parcela, contato]):
                st.error("Preencha todos os campos obrigatórios (*).")
            else:
                caminho_pdf = None
                if pdf_file:
                    st.info("Fazendo upload do PDF para a nuvem... Isso pode levar alguns segundos.")
                    caminho_pdf = salvar_pdf_gcs(pdf_file, numero_apolice, cliente)
                
                if pdf_file and not caminho_pdf:
                     st.error("Não foi possível salvar a apólice com o PDF devido a um erro no upload.")
                     return

                apolice_data = {
                    'seguradora': seguradora, 'cliente': cliente, 'numero_apolice': numero_apolice,
                    'placa': placa, 'tipo_seguro': tipo_seguro, 'valor_da_parcela': valor_parcela,
                    'comissao': comissao, 'data_inicio_de_vigencia': data_inicio,
                    'data_final_de_vigencia': data_fim, 'contato': contato, 'email': email,
                    'observacoes': observacoes, 'status': 'Pendente', 
                    'caminho_pdf': caminho_pdf if caminho_pdf else ""
                }
                if add_apolice(apolice_data):
                    st.success("🎉 Apólice cadastrada com sucesso!")
                    if caminho_pdf:
                        st.success(f"PDF salvo na nuvem com sucesso!")
                        st.markdown(f"**Link:** [Abrir PDF]({caminho_pdf})")
                    st.balloons()

def main():
    """Função principal que renderiza a aplicação Streamlit."""
    st.set_page_config(
        page_title="Moreiraseg - Gestão de Apólices",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    init_db()

    if 'user_email' not in st.session_state:
        st.session_state.user_email = None
        st.session_state.user_nome = None
        st.session_state.user_perfil = None
    
    if not st.session_state.user_email:
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            if os.path.exists(LOGO_PATH):
                st.image(LOGO_PATH)
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
        if os.path.exists(ICONE_PATH):
            st.image(ICONE_PATH, width=80)
        st.title(f"Olá, {st.session_state.user_nome.split()[0]}!")
        st.write(f"Perfil: `{st.session_state.user_perfil.capitalize()}`")
        st.divider()

        menu_options = [
            "📊 Painel de Controle",
            "➕ Cadastrar Apólice",
            "🔍 Consultar Apólices",
            "🔄 Gerenciar Apólices",
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

    # Aqui você adicionaria as chamadas para as outras funções de renderização
    if menu_opcao == "➕ Cadastrar Apólice":
        render_cadastro_form()
    # Adicione as outras páginas aqui
    # elif menu_opcao == "📊 Painel de Controle":
    #     render_dashboard()
    # etc.

if __name__ == "__main__":
    main()
