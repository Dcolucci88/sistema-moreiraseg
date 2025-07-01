import streamlit as st
import sqlite3
import pandas as pd
import datetime
from datetime import date
import os
import re

# --- CONFIGURAÇÕES GLOBAIS ---

# Nome do arquivo do banco de dados
DB_NAME = "moreiraseg.db"

# Caminho absoluto para o diretório do script atual
BASE_DIR = os.path.dirname(__file__)
# Caminhos relativos para os assets, garantindo que a pasta 'LogoTipo' esteja no mesmo nível do script
ASSETS_DIR = os.path.join(BASE_DIR, "LogoTipo")  # CAMINHO ATUALIZADO PARA "LogoTipo"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "Icone.png")  # NOME DO ARQUIVO ATUALIZADO PARA "Icone.png" (com 'I' maiúsculo)


# --- FUNÇÕES DE BANCO DE DADOS ---

def get_connection():
    """Retorna uma conexão com o banco de dados SQLite."""
    # Garante que a conexão usa um row_factory para acessar colunas por nome
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # Essencial para acessar resultados por nome da coluna
    return conn


def _migrate_database(conn):
    """
    Função interna para adicionar TODAS as colunas faltantes na tabela de apólices.
    Garante que o banco de dados esteja sempre com a estrutura mais recente.
    """
    try:
        c = conn.cursor()
        c.execute("PRAGMA table_info(apolices)")
        existing_columns = [col[1] for col in c.fetchall()]

        # Dicionário completo de colunas e seus tipos
        required_columns = {
            'placa': 'TEXT',
            'comissao': 'REAL',
            'data_inicio_de_vigencia': 'DATE',
            'data_final_de_vigencia': 'DATE',
            'email': 'TEXT',
            'valor_da_parcela': 'REAL',
            'caminho_pdf': 'TEXT',
            'status': 'TEXT DEFAULT "Pendente"',
            'data_atualizacao': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
        }

        for col, col_type in required_columns.items():
            if col not in existing_columns:
                try:
                    c.execute(f"ALTER TABLE apolices ADD COLUMN {col} {col_type}")
                    print(f"Coluna '{col}' adicionada com sucesso!")

                    # Se for a coluna status, atualize os registros existentes
                    if col == 'status':
                        c.execute("UPDATE apolices SET status = 'Pendente' WHERE status IS NULL")
                except sqlite3.OperationalError as e:
                    # Pode acontecer em ambientes concorridos, mas geralmente é seguro ignorar
                    print(f"Aviso ao adicionar coluna '{col}': {e}")

        # Atualizar registros antigos com valores padrão
        c.execute("""
            UPDATE apolices SET
                data_inicio_de_vigencia = COALESCE(data_inicio_de_vigencia, '2023-01-01'),
                data_final_de_vigencia = COALESCE(data_final_de_vigencia, '2024-01-01'),
                valor_da_parcela = COALESCE(valor_da_parcela, 0.0),
                status = COALESCE(status, 'Pendente')
            WHERE data_inicio_de_vigencia IS NULL 
               OR data_final_de_vigencia IS NULL 
               OR valor_da_parcela IS NULL 
               OR status IS NULL
        """)

        conn.commit()
    except Exception as e:
        print(f"Erro crítico durante a migração do banco de dados: {e}")


def init_db():
    """
    Inicializa o banco de dados, cria as tabelas se não existirem
    e executa a migração para garantir que todas as colunas estão presentes.
    """
    try:
        # Tenta criar a pasta 'pdfs' se não existir
        os.makedirs("pdfs", exist_ok=True)

        with get_connection() as conn:
            c = conn.cursor()

            # Tabela principal de apólices com estrutura completa
            c.execute('''
                CREATE TABLE IF NOT EXISTS apolices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seguradora TEXT NOT NULL,
                    cliente TEXT NOT NULL,
                    numero_apolice TEXT NOT NULL UNIQUE,
                    placa TEXT,
                    tipo_seguro TEXT NOT NULL,
                    valor_da_parcela REAL NOT NULL,
                    comissao REAL,
                    data_inicio_de_vigencia DATE NOT NULL,
                    data_final_de_vigencia DATE NOT NULL,
                    contato TEXT NOT NULL,
                    email TEXT,
                    observacoes TEXT,
                    status TEXT NOT NULL DEFAULT 'Pendente',
                    caminho_pdf TEXT,
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Trigger para atualizar a data de modificação automaticamente
            c.execute('''
                CREATE TRIGGER IF NOT EXISTS update_apolices_timestamp
                AFTER UPDATE ON apolices
                FOR EACH ROW
                BEGIN
                    UPDATE apolices
                    SET data_atualizacao = CURRENT_TIMESTAMP
                    WHERE id = OLD.id;
                END;
            ''')

            # Tabela de histórico de ações
            c.execute('''
                CREATE TABLE IF NOT EXISTS historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apolice_id INTEGER NOT NULL,
                    usuario TEXT NOT NULL,
                    acao TEXT NOT NULL,
                    detalhes TEXT,
                    data_acao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (apolice_id) REFERENCES apolices(id)
                )
            ''')

            # Tabela de usuários
            c.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    senha TEXT NOT NULL,
                    perfil TEXT NOT NULL DEFAULT 'user',
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Criar usuário administrador padrão se não existir
            c.execute("SELECT id FROM usuarios WHERE email = ?", ('adm@moreiraseg.com.br',))
            if not c.fetchone():
                c.execute(
                    "INSERT INTO usuarios (nome, email, senha, perfil) VALUES (?, ?, ?, ?)",
                    ('Administrador', 'adm@moreiraseg.com.br', 'Salmo@139', 'admin')
                )

            conn.commit()

            # Executa a migração para garantir que tabelas antigas sejam atualizadas
            _migrate_database(conn)

    except Exception as e:
        st.error(f"❌ Falha ao inicializar o banco de dados: {e}")
        st.stop()


def add_historico(apolice_id, usuario_email, acao, detalhes=""):
    """
    Registra uma ação no histórico de uma apólice.

    Args:
        apolice_id (int): ID da apólice.
        usuario_email (str): Email do usuário que realizou a ação.
        acao (str): Descrição da ação (ex: 'Cadastro', 'Atualização').
        detalhes (str, optional): Detalhes adicionais da ação.
    """
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
    """
    Adiciona uma nova apólice ao banco de dados.

    Args:
        data (dict): Dicionário contendo os dados da apólice.

    Returns:
        bool: True se a apólice foi adicionada com sucesso, False caso contrário.
    """
    # Validações antes de conectar ao banco
    if data['data_inicio_de_vigencia'] >= data['data_final_de_vigencia']:
        st.error("❌ A data final da vigência deve ser posterior à data inicial.")
        return False

    if data.get('email') and not re.match(r"[^@]+@[^@]+\.[^@]+", data['email']):
        st.error("❌ O formato do e-mail é inválido.")
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

            # Adiciona ao histórico após sucesso
            add_historico(
                apolice_id,
                st.session_state.get('user_email', 'sistema'),
                'Cadastro de Apólice',
                f"Apólice '{data['numero_apolice']}' criada."
            )
            return True

    except sqlite3.IntegrityError:
        # Este erro ocorre se numero_apolice já existe devido à restrição UNIQUE
        st.error(f"❌ Erro: O número de apólice '{data['numero_apolice']}' já existe no sistema!")
        return False
    except Exception as e:
        st.error(f"❌ Ocorreu um erro inesperado ao cadastrar: {e}")
        return False


def update_apolice(apolice_id, update_data):
    """
    Atualiza os dados de uma apólice existente.

    Args:
        apolice_id (int): O ID da apólice a ser atualizada.
        update_data (dict): Dicionário com os campos e novos valores.

    Returns:
        bool: True se a atualização foi bem-sucedida, False caso contrário.
    """
    try:
        with get_connection() as conn:
            c = conn.cursor()

            # Monta a query de atualização dinamicamente
            set_clause = ", ".join([f"{key} = ?" for key in update_data.keys()])
            values = list(update_data.values())
            values.append(apolice_id)

            query = f"UPDATE apolices SET {set_clause} WHERE id = ?"

            c.execute(query, tuple(values))
            conn.commit()

            # Registra no histórico
            detalhes = f"Campos atualizados: {', '.join(update_data.keys())}"
            add_historico(apolice_id, st.session_state.get('user_email', 'sistema'), 'Atualização', detalhes)

            return True
    except Exception as e:
        st.error(f"❌ Erro ao atualizar a apólice: {e}")
        return False


def get_apolices():
    """
    Obtém TODAS as apólices do banco de dados.
    Calcula os dias restantes e a prioridade de renovação.
    Não aplica filtro de status aqui para permitir depuração e consulta completa.

    Returns:
        pd.DataFrame: DataFrame com os dados das apólices.
    """
    try:
        with get_connection() as conn:
            # Verificar se a tabela existe
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='apolices'")
            if not c.fetchone():
                return pd.DataFrame()  # Retorna DataFrame vazio se a tabela não existe

            # Não há necessidade de verificar colunas aqui novamente;
            # a função init_db e _migrate_database já garantem isso na inicialização.

            # Consulta principal para obter TODAS as apólices
            query = "SELECT * FROM apolices ORDER BY data_final_de_vigencia ASC"
            df = pd.read_sql_query(query, conn)

    except Exception as e:
        st.error(f"Erro ao carregar apólices: {e}")
        return pd.DataFrame()

    if not df.empty and 'data_final_de_vigencia' in df.columns:
        # Converte a coluna de data para o tipo datetime, tratando erros
        df['data_final_de_vigencia_dt'] = pd.to_datetime(df['data_final_de_vigencia'], errors='coerce')

        # Calcula os dias restantes até o vencimento
        df['dias_restantes'] = (df['data_final_de_vigencia_dt'] - pd.Timestamp.now()).dt.days

        def define_prioridade(dias):
            """Define a prioridade de renovação com base nos dias restantes."""
            if pd.isna(dias):
                return '⚪ Indefinida'  # Para datas inválidas ou nulas
            if dias <= 3:
                return '🔥 Urgente'
            elif dias <= 7:
                return '⚠️ Alta'
            elif dias <= 20:
                return '⚠️ Média'
            else:
                return '✅ Baixa'

        # Aplica a função de prioridade
        df['prioridade'] = df['dias_restantes'].apply(define_prioridade)
        # Remove a coluna temporária de datetime
        df.drop(columns=['data_final_de_vigencia_dt'], inplace=True)

    return df


def get_apolice_details(apolice_id):
    """Obtém detalhes e histórico de uma apólice específica."""
    try:
        with get_connection() as conn:
            # conn.row_factory já foi definido em get_connection()
            c = conn.cursor()

            c.execute("SELECT * FROM apolices WHERE id = ?", (apolice_id,))
            apolice = c.fetchone()  # Retorna um objeto Row que se comporta como dicionário

            c.execute("SELECT * FROM historico WHERE apolice_id = ? ORDER BY data_acao DESC", (apolice_id,))
            historico = c.fetchall()

            return apolice, historico
    except Exception as e:
        st.error(f"Erro ao buscar detalhes da apólice: {e}")
        return None, []


def login_user(email, senha):
    """Autentica um usuário e retorna seus dados se as credenciais estiverem corretas."""
    try:
        with get_connection() as conn:
            # conn.row_factory já foi definido em get_connection()
            c = conn.cursor()
            c.execute("SELECT * FROM usuarios WHERE email = ? AND senha = ?", (email, senha))
            return c.fetchone()
    except Exception as e:
        st.error(f"Erro durante o login: {e}")
        return None


def salvar_pdf(uploaded_file, numero_apolice, cliente):
    """Salva um arquivo PDF no sistema de arquivos e retorna o caminho."""
    try:
        # Sanitiza o nome do cliente para uso em caminho de arquivo
        safe_cliente = re.sub(r'[^a-zA-Z0-9\s-]', '', cliente).strip().replace(' ', '_')
        # Cria um diretório para cada cliente e número de apólice para organização
        save_dir = os.path.join("pdfs", safe_cliente, numero_apolice)
        os.makedirs(save_dir, exist_ok=True)

        # Gera um nome de arquivo único com timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"apolice_{numero_apolice}_{timestamp}.pdf"
        file_path = os.path.join(save_dir, filename)

        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        return file_path
    except Exception as e:
        st.error(f"❌ Erro ao salvar o PDF: {e}")
        return None


# --- INTERFACE PRINCIPAL DO STREAMLIT ---

def main():
    """Função principal que renderiza a aplicação Streamlit."""
    st.set_page_config(
        page_title="Moreiraseg - Gestão de Apólices",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    init_db()  # Inicializa o banco de dados e migra se necessário

    # Inicializa estados de sessão se não existirem
    if 'user_email' not in st.session_state:
        st.session_state.user_email = None
        st.session_state.user_nome = None
        st.session_state.user_perfil = None

    # Lógica de login
    if not st.session_state.user_email:
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            # Exibe a imagem icone.png na tela de login com width reduzido
            if os.path.exists(ICONE_PATH):
                st.image(ICONE_PATH, width=150)  # Reduzido o tamanho para 150px
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
                        st.rerun()  # Recarrega a página para entrar no sistema
                    else:
                        st.error("Credenciais inválidas. Tente novamente.")

            st.info("Para testes, use: `adm@moreiraseg.com.br` / `Salmo@139`")
        return  # Impede o restante da execução se não logado

    # Este bloco é executado APENAS se o usuário estiver logado
    # Exibe a logo azul centralizada no topo da área principal
    col_logo1, col_logo2, col_logo3 = st.columns([1, 2, 1])
    with col_logo2:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, use_container_width=True)  # Alterado para use_container_width
        else:
            st.warning("Logo azul não encontrada. Verifique o caminho da imagem.")
    st.divider()  # Adiciona uma linha divisória para separar o logo do restante do conteúdo

    with st.sidebar:
        # Manter um pequeno icone no sidebar, se desejado. Caso contrário, remova esta seção.
        if os.path.exists(ICONE_PATH):
            st.image(ICONE_PATH, width=80)
        st.title(f"Olá, {st.session_state.user_nome.split()[0]}!")
        st.write(f"Perfil: `{st.session_state.user_perfil.capitalize()}`")
        st.divider()

        menu_options = [
            "📊 Painel de Controle",
            "➕ Cadastrar Apólice",
            "🔍 Consultar Apólices",
            "🔄 Gerenciar Apólice",
        ]
        # Adiciona a opção de configurações apenas para administradores
        if st.session_state.user_perfil == 'admin':
            menu_options.append("⚙️ Configurações")

        menu_opcao = st.radio("Menu Principal", menu_options)

        st.divider()
        if st.button("🚪 Sair do Sistema", use_container_width=True):
            # Limpa o estado da sessão e recarrega para a tela de login
            st.session_state.user_email = None
            st.session_state.user_nome = None
            st.session_state.user_perfil = None
            st.rerun()

    # Renderiza a página selecionada pelo usuário
    if menu_opcao == "📊 Painel de Controle":
        render_dashboard()
    elif menu_opcao == "➕ Cadastrar Apólice":
        render_cadastro_form()
    elif menu_opcao == "🔍 Consultar Apólices":
        render_consulta_apolices()
    elif menu_opcao == "🔄 Gerenciar Apólice":
        render_gerenciamento_apolices()
    elif menu_opcao == "⚙️ Configurações" and st.session_state.user_perfil == 'admin':
        render_configuracoes()


def render_dashboard():
    """Renderiza a página do Painel de Controle."""
    st.title("📊 Painel de Controle")
    # Obtém todas as apólices, os filtros são aplicados depois
    apolices_df = get_apolices()

    if apolices_df.empty:
        st.info("Nenhuma apólice cadastrada. Comece adicionando uma no menu 'Cadastrar Apólice'.")
        return

    # Métricas principais
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total de Apólices", len(apolices_df))

    pendentes_df = apolices_df[apolices_df['status'] == 'Pendente']
    col2.metric("Apólices Pendentes", len(pendentes_df))

    valor_pendente = pendentes_df['valor_da_parcela'].sum()
    col3.metric("Valor Total Pendente", f"R${valor_pendente:,.2f}")

    # Filtra apólices urgentes (vencimento em até 3 dias)
    urgentes_df = apolices_df[apolices_df['dias_restantes'].fillna(999) <= 3]
    col4.metric("Apólices Urgentes", len(urgentes_df), "Vencem em até 3 dias")

    st.divider()

    st.subheader("Apólices por Prioridade de Renovação")
    # Mapeia as apólices por prioridade para exibição em abas
    prioridades_map = {
        '🔥 Urgente': apolices_df[apolices_df['prioridade'] == '🔥 Urgente'],
        '⚠️ Alta': apolices_df[apolices_df['prioridade'] == '⚠️ Alta'],
        '⚠️ Média': apolices_df[apolices_df['prioridade'] == '⚠️ Média'],
        '✅ Baixa': apolices_df[apolices_df['prioridade'] == '✅ Baixa'],
        '⚪ Indefinida': apolices_df[apolices_df['prioridade'] == '⚪ Indefinida']
    }

    tabs = st.tabs(list(prioridades_map.keys()))
    cols_to_show = ['cliente', 'numero_apolice', 'tipo_seguro', 'dias_restantes', 'status']

    for tab, (prioridade, df) in zip(tabs, prioridades_map.items()):
        with tab:
            if not df.empty:
                st.dataframe(df[cols_to_show], use_container_width=True)
            else:
                st.info(f"Nenhuma apólice com prioridade '{prioridade.split(' ')[-1]}'.")

    st.divider()

    # Gráficos de distribuição
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Distribuição por Status")
        status_count = apolices_df['status'].value_counts()
        st.bar_chart(status_count)
    with col2:
        st.subheader("Distribuição por Tipo de Seguro")
        tipo_count = apolices_df['tipo_seguro'].value_counts()
        st.bar_chart(tipo_count)


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
            tipo_seguro = st.selectbox("Tipo de Seguro*",
                                       ["Automóvel", "RCO", "Vida", "Residencial", "Empresarial", "Saúde", "Viagem",
                                        "Fiança", "Outro"])
            valor_parcela = st.text_input("💰 Valor da Parcela (R$)*", value="0,00")
            # Garante que a data final seja pelo menos 1 dia após a data inicial
            data_fim = st.date_input("📅 Fim de Vigência*", min_value=data_inicio + datetime.timedelta(
                days=1) if data_inicio else date.today() + datetime.timedelta(days=1))

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
                caminho_pdf = salvar_pdf(pdf_file, numero_apolice, cliente) if pdf_file else None
                apolice_data = {
                    'seguradora': seguradora, 'cliente': cliente, 'numero_apolice': numero_apolice,
                    'placa': placa, 'tipo_seguro': tipo_seguro, 'valor_da_parcela': valor_parcela,
                    'comissao': comissao, 'data_inicio_de_vigencia': data_inicio,
                    'data_final_de_vigencia': data_fim, 'contato': contato, 'email': email,
                    'observacoes': observacoes, 'status': 'Pendente', 'caminho_pdf': caminho_pdf
                }
                if add_apolice(apolice_data):
                    st.success("🎉 Apólice cadastrada com sucesso!")
                    st.balloons()


def render_consulta_apolices():
    """Renderiza a página de consulta e filtro de apólices."""
    st.title("🔍 Consultar Apólices")
    st.info("Esta tela agora exibe todas as colunas para ajudar a diagnosticar dados problemáticos das apólices.")

    apolices_df_raw = get_apolices()

    if apolices_df_raw.empty:
        st.info("Nenhuma apólice cadastrada no sistema.")
        return

    st.subheader("Filtros")
    col1, col2, col3 = st.columns(3)
    with col1:
        # Garante que 'Todas' é a primeira opção e inclui status únicos existentes
        status_options = ["Todas"] + sorted(apolices_df_raw['status'].unique().tolist())
        filtro_status = st.selectbox("Status", status_options)
    with col2:
        seguradora_options = ["Todas"] + sorted(apolices_df_raw['seguradora'].unique().tolist())
        filtro_seguradora = st.selectbox("Seguradora", seguradora_options)
    with col3:
        tipo_options = ["Todos"] + sorted(apolices_df_raw['tipo_seguro'].unique().tolist())
        filtro_tipo = st.selectbox("Tipo de Seguro", tipo_options)

    apolices_df_filtrado = apolices_df_raw.copy()
    # Aplica os filtros selecionados
    if filtro_status != "Todas":
        apolices_df_filtrado = apolices_df_filtrado[apolices_df_filtrado['status'] == filtro_status]
    if filtro_seguradora != "Todas":
        apolices_df_filtrado = apolices_df_filtrado[apolices_df_filtrado['seguradora'] == filtro_seguradora]
    if filtro_tipo != "Todos":
        apolices_df_filtrado = apolices_df_filtrado[apolices_df_filtrado['tipo_seguro'] == filtro_tipo]

    st.divider()

    if not apolices_df_filtrado.empty:
        # Exibe TODAS as colunas para depuração, conforme solicitado pelo usuário.
        # Isso ajudará a identificar se a "apólice fantasma" tem um status ou outro campo inesperado.
        st.dataframe(apolices_df_filtrado, use_container_width=True)

        csv_data = apolices_df_filtrado.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Exportar para CSV",
            data=csv_data,
            file_name=f"relatorio_apolices_{date.today()}.csv",
            mime="text/csv",
        )
    else:
        st.info("Nenhuma apólice encontrada com os filtros selecionados.")


def render_gerenciamento_apolices():
    """Renderiza a página para gerenciar uma apólice individualmente."""
    st.title("🔄 Gerenciar Apólice")
    apolices_df = get_apolices()  # Obtém todas as apólices

    if apolices_df.empty:
        st.info("Nenhuma apólice para gerenciar. Cadastre uma primeiro.")
        return

    # Constrói a lista de opções para o selectbox de forma segura,
    # garantindo que o número da apólice e o cliente existam.
    apolice_options = {
        f"{row.get('numero_apolice', 'S/N')} - {row.get('cliente', '[Cliente não informado]')}": row['id']
        for index, row in apolices_df.iterrows()
    }

    # Adiciona uma opção padrão se a lista não estiver vazia
    if apolice_options:
        selecionada_label = st.selectbox("Selecione uma apólice:", list(apolice_options.keys()))
    else:
        st.info("Nenhuma apólice disponível para seleção.")
        return

    if selecionada_label:
        apolice_id = apolice_options[selecionada_label]
        apolice, historico = get_apolice_details(apolice_id)

        if not apolice:
            st.error("Apólice não encontrada.")
            return

        dias_restantes = "N/A"
        if apolice['data_final_de_vigencia']:
            try:
                # Converte a data de string para datetime e calcula os dias restantes
                data_fim = pd.to_datetime(apolice['data_final_de_vigencia'])
                if pd.notna(data_fim):
                    dias_restantes = (data_fim - pd.Timestamp.now()).days
                else:
                    dias_restantes = "Data Inválida"
            except (ValueError, TypeError):
                dias_restantes = "Data Inválida"

        st.subheader(f"Detalhes da Apólice: {apolice['numero_apolice']}")
        col1, col2, col3 = st.columns(3)
        col1.metric("Status", apolice['status'])
        col2.metric("Vencimento em", f"{dias_restantes} dias" if isinstance(dias_restantes, int) else dias_restantes)
        col3.metric("Valor da Parcela", f"R$ {apolice['valor_da_parcela']:,.2f}")

        with st.expander("📝 Editar Informações e Ver Detalhes"):
            with st.form(f"form_edit_{apolice_id}"):
                st.subheader("Atualizar Dados")

                # Define valores padrão para as datas, garantindo que sejam objetos date
                try:
                    default_inicio = pd.to_datetime(apolice['data_inicio_de_vigencia']).date()
                except (ValueError, TypeError):
                    default_inicio = date.today()

                try:
                    default_fim = pd.to_datetime(apolice['data_final_de_vigencia']).date()
                except (ValueError, TypeError):
                    default_fim = date.today() + datetime.timedelta(days=365)  # Um ano no futuro como padrão

                col1, col2 = st.columns(2)
                with col1:
                    novo_status = st.selectbox(
                        "Status da Apólice",
                        ["Pendente", "Ativa", "Cancelada", "Renovada", "Vencida"],
                        index=["Pendente", "Ativa", "Cancelada", "Renovada", "Vencida"].index(apolice['status'])
                    )
                    nova_data_inicio = st.date_input("📅 Novo Início de Vigência", value=default_inicio)

                with col2:
                    novo_contato = st.text_input("Contato", value=apolice['contato'])
                    nova_data_fim = st.date_input("📅 Novo Fim de Vigência", value=default_fim)

                novas_obs = st.text_area("Observações", value=apolice['observacoes'])

                submitted = st.form_submit_button("Salvar Alterações")
                if submitted:
                    if nova_data_inicio >= nova_data_fim:
                        st.error("❌ A data final da vigência deve ser posterior à data inicial.")
                    else:
                        update_data = {
                            'status': novo_status,
                            'contato': novo_contato,
                            'observacoes': novas_obs,
                            'data_inicio_de_vigencia': nova_data_inicio,
                            'data_final_de_vigencia': nova_data_fim
                        }
                        if update_apolice(apolice_id, update_data):
                            st.success("Apólice atualizada com sucesso!")
                            st.rerun()  # Recarrega a página para exibir as mudanças

            st.divider()
            # Exibe o caminho do PDF e datas de cadastro/atualização
            st.write("**PDF Anexado:**", f"_{apolice['caminho_pdf']}_" if apolice['caminho_pdf'] else "Nenhum")
            st.write(f"**Cadastrado em:** {apolice['data_cadastro']}")
            st.write(f"**Última atualização:** {apolice['data_atualizacao']}")

        st.subheader("📜 Histórico de Ações")
        if historico:
            for acao in historico:
                # Formata a data e hora da ação
                data_formatada = datetime.datetime.strptime(acao['data_acao'], '%Y-%m-%d %H:%M:%S').strftime(
                    '%d/%m/%Y às %H:%M')
                st.info(f"**Ação:** {acao['acao']} por **{acao['usuario']}** em {data_formatada}")
                if acao['detalhes']:
                    st.caption(f"Detalhes: {acao['detalhes']}")
        else:
            st.info("Nenhuma ação registrada para esta apólice.")


def render_configuracoes():
    """Renderiza a página de configurações (somente para admin)."""
    st.title("⚙️ Configurações do Sistema")
    tab1, tab2 = st.tabs(["Gerenciar Usuários", "Backup e Restauração"])

    with tab1:
        st.subheader("Usuários Cadastrados")
        try:
            with get_connection() as conn:
                usuarios_df = pd.read_sql_query("SELECT id, nome, email, perfil, data_cadastro FROM usuarios", conn)
            st.dataframe(usuarios_df, use_container_width=True)
        except Exception as e:
            st.error(f"Erro ao listar usuários: {e}")

        with st.expander("Adicionar Novo Usuário"):
            with st.form("form_novo_usuario", clear_on_submit=True):
                nome = st.text_input("Nome Completo")
                email = st.text_input("E-mail")
                senha = st.text_input("Senha", type="password")
                perfil = st.selectbox("Perfil", ["user", "admin"])

                if st.form_submit_button("Adicionar Usuário"):
                    if not all([nome, email, senha, perfil]):
                        st.warning("Todos os campos são obrigatórios.")
                    else:
                        try:
                            with get_connection() as conn:
                                c = conn.cursor()
                                c.execute(
                                    "INSERT INTO usuarios (nome, email, senha, perfil) VALUES (?, ?, ?, ?)",
                                    (nome, email, senha, perfil)
                                )
                                conn.commit()
                            st.success(f"Usuário '{nome}' adicionado com sucesso!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error(f"❌ Erro: O e-mail '{email}' já está em uso.")
                        except Exception as e:
                            st.error(f"❌ Erro ao adicionar usuário: {e}")

        with st.expander("Remover Usuário"):
            try:
                with get_connection() as conn:
                    users_to_delete = pd.read_sql_query("SELECT id, nome, email FROM usuarios WHERE perfil != 'admin'",
                                                        conn)

                if not users_to_delete.empty:
                    user_options = {f"{row['nome']} ({row['email']})": row['id'] for index, row in
                                    users_to_delete.iterrows()}
                    selected_user_label = st.selectbox(
                        "Selecione o usuário para remover (admins não podem ser removidos aqui):",
                        list(user_options.keys()))

                    if selected_user_label:
                        user_id_to_delete = user_options[selected_user_label]
                        if st.button("Remover Usuário Selecionado", use_container_width=True):
                            try:
                                with get_connection() as conn:
                                    c = conn.cursor()
                                    c.execute("DELETE FROM usuarios WHERE id = ?", (user_id_to_delete,))
                                    conn.commit()
                                st.success(f"Usuário removido com sucesso!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao remover usuário: {e}")
                else:
                    st.info("Nenhum usuário não-administrador para remover.")

            except Exception as e:
                st.error(f"Erro ao carregar usuários para remoção: {e}")

    with tab2:
        st.subheader("Ferramentas de Backup e Restauração")
        st.warning("⚠️ Funcionalidades de backup e restauração não implementadas nesta versão.")
        st.info("Para realizar um backup manual, copie o arquivo `moreiraseg.db`.")

# Ponto de entrada da aplicação
if __name__ == "__main__":
    main()