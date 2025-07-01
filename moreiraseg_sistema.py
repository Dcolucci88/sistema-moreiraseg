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
    st.error("Biblioteca do Google Cloud não encontrada. Verifique o seu ficheiro `requirements.txt`.")
    st.stop()


# --- CONFIGURAÇÕES GLOBAIS ---

# Nome do arquivo do banco de dados (continuará local por enquanto)
DB_NAME = "moreiraseg.db"

# Caminhos relativos para os assets, usando o nome da sua pasta no GitHub
ASSETS_DIR = "LogoTipo" 
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "Icone.png")

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

# --- FUNÇÃO DE UPLOAD PARA O GOOGLE CLOUD STORAGE ---

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
        
        blob.upload_from_file(uploaded_file, content_type='application/pdf')
        
        blob.make_public()

        return blob.public_url

    except KeyError:
        st.error("Credenciais do Google Cloud Storage ou nome do bucket não configurados nos 'Secrets' do Streamlit.")
        st.info("Por favor, siga as instruções de configuração para adicionar 'gcs_credentials' e 'gcs_bucket_name' aos segredos do seu app.")
        return None
    except Exception as e:
        st.error(f"❌ Falha no upload para o Google Cloud Storage: {e}")
        return None

# --- FUNÇÕES DE LÓGICA DO SISTEMA ---

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

def update_apolice(apolice_id, update_data):
    """Atualiza os dados de uma apólice existente."""
    try:
        with get_connection() as conn:
            c = conn.cursor()
            set_clause = ", ".join([f"{key} = ?" for key in update_data.keys()])
            values = list(update_data.values())
            values.append(apolice_id)
            query = f"UPDATE apolices SET {set_clause} WHERE id = ?"
            c.execute(query, tuple(values))
            conn.commit()
            detalhes = f"Campos atualizados: {', '.join(update_data.keys())}"
            add_historico(apolice_id, st.session_state.get('user_email', 'sistema'), 'Atualização', detalhes)
            return True
    except Exception as e:
        st.error(f"❌ Erro ao atualizar a apólice: {e}")
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
    
def get_apolice_details(apolice_id):
    """Obtém detalhes e histórico de uma apólice específica."""
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM apolices WHERE id = ?", (apolice_id,))
            apolice = c.fetchone()
            c.execute("SELECT * FROM historico WHERE apolice_id = ? ORDER BY data_acao DESC", (apolice_id,))
            historico = c.fetchall()
            return apolice, historico
    except Exception as e:
        st.error(f"Erro ao buscar detalhes da apólice: {e}")
        return None, []

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

def render_dashboard():
    """Renderiza a página do Painel de Controle."""
    st.title("📊 Painel de Controle")
    try:
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
    except Exception as e:
        st.error(f"Ocorreu um erro ao renderizar o Painel de Controle: {e}")

def render_consulta_apolices():
    """Renderiza a página de consulta e filtro de apólices."""
    st.title("🔍 Consultar Apólices")
    try:
        apolices_df_raw = get_apolices()
        if apolices_df_raw.empty:
            st.info("Nenhuma apólice cadastrada no sistema.")
            return

        st.subheader("Filtros")
        col1, col2, col3 = st.columns(3)
        with col1:
            status_options = ["Todas"] + list(apolices_df_raw['status'].unique())
            filtro_status = st.selectbox("Status", status_options)
        with col2:
            seguradora_options = ["Todas"] + list(apolices_df_raw['seguradora'].unique())
            filtro_seguradora = st.selectbox("Seguradora", seguradora_options)
        with col3:
            tipo_options = ["Todos"] + list(apolices_df_raw['tipo_seguro'].unique())
            filtro_tipo = st.selectbox("Tipo de Seguro", tipo_options)

        apolices_df_filtrado = apolices_df_raw.copy()
        if filtro_status != "Todas":
            apolices_df_filtrado = apolices_df_filtrado[apolices_df_filtrado['status'] == filtro_status]
        if filtro_seguradora != "Todas":
            apolices_df_filtrado = apolices_df_filtrado[apolices_df_filtrado['seguradora'] == filtro_seguradora]
        if filtro_tipo != "Todos":
            apolices_df_filtrado = apolices_df_filtrado[apolices_df_filtrado['tipo_seguro'] == filtro_tipo]
        
        st.divider()

        if not apolices_df_filtrado.empty:
            cols_to_show = ['cliente', 'numero_apolice', 'seguradora', 'tipo_seguro', 'status', 'dias_restantes']
            st.dataframe(apolices_df_filtrado[cols_to_show], use_container_width=True)
            
            csv_data = apolices_df_filtrado.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Exportar para CSV",
                data=csv_data,
                file_name=f"relatorio_apolices_{date.today()}.csv",
                mime="text/csv",
            )
        else:
            st.info("Nenhuma apólice encontrada com os filtros selecionados.")
    except Exception as e:
        st.error(f"Ocorreu um erro ao renderizar a página de consulta: {e}")


def render_gerenciamento_apolices():
    """Renderiza a página para gerenciar uma apólice individualmente."""
    st.title("🔄 Gerenciar Apólices")
    try:
        apolices_df = get_apolices()
        if apolices_df.empty:
            st.info("Nenhuma apólice para gerenciar. Cadastre uma primeiro.")
            return

        apolice_options = {f"{row.get('numero_apolice', 'S/N')} - {row.get('cliente', '[Cliente não informado]')}": row['id'] for index, row in apolices_df.iterrows()}
        selecionada_label = st.selectbox("Selecione uma apólice para editar:", apolice_options.keys())

        if selecionada_label:
            apolice_id = apolice_options[selecionada_label]
            apolice, historico = get_apolice_details(apolice_id)
            if not apolice:
                st.error("Apólice não encontrada.")
                return
                
            st.subheader(f"Editando Apólice: {apolice['numero_apolice']}")
            
            with st.form(f"form_reupload_{apolice_id}"):
                st.write("Se esta apólice foi cadastrada sem um PDF, você pode adicioná-lo aqui.")
                pdf_file = st.file_uploader("📎 Anexar novo PDF da Apólice", type=["pdf"], key=f"uploader_{apolice_id}")
                submitted = st.form_submit_button("💾 Salvar PDF")
                if submitted and pdf_file:
                    st.info("Fazendo upload do novo PDF para a nuvem...")
                    novo_caminho_pdf = salvar_pdf_gcs(pdf_file, apolice['numero_apolice'], apolice['cliente'])
                    if novo_caminho_pdf:
                        update_data = {'caminho_pdf': novo_caminho_pdf}
                        if update_apolice(apolice_id, update_data):
                            st.success("PDF da apólice atualizado com sucesso!")
                            st.rerun()
                    else:
                        st.error("Falha ao fazer o upload do novo PDF.")
            
            st.divider()
            if apolice['caminho_pdf']:
                st.success("Esta apólice já possui um PDF na nuvem.")
                st.markdown(f"**Link:** [Abrir PDF]({apolice['caminho_pdf']})")
            else:
                st.warning("Esta apólice ainda não possui um PDF associado.")
    except Exception as e:
        st.error(f"Ocorreu um erro ao renderizar a página de gerenciamento: {e}")


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
    # ========== INÍCIO DA CORREÇÃO ========== (adicione estas linhas)
    hide_streamlit_style = """
        <style>
            footer {visibility: hidden;}
            .stDeployButton {display:none;}
        </style>
    """
    st.markdown(hide_streamlit_style, unsafe_allow_html=True)
    # ========== FIM DA CORREÇÃO ==========
    
    st.set_page_config(
        page_title="Moreiraseg - Gestão de Apólices",
        page_icon=ICONE_PATH,
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
    elif menu_opcao == "🔍 Consultar Apólices":
        render_consulta_apolices()
    elif menu_opcao == "🔄 Gerenciar Apólices":
        render_gerenciamento_apolices()
    # A página de configurações pode ser adicionada aqui se necessário
    # elif menu_opcao == "⚙️ Configurações" and st.session_state.user_perfil == 'admin':
    #     render_configuracoes()

if __name__ == "__main__":
    main()
