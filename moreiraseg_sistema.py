# moreiraseg_sistema.py
# VERSÃO REATORADA COM GESTÃO DE PARCELAS AUTOMATIZADA

import streamlit as st
import pandas as pd
import datetime
from datetime import date
import os
import re

# Tente importar as bibliotecas necessárias, mostrando erros amigáveis.
try:
    from supabase import create_client, Client
except ImportError:
    st.error("Biblioteca do Supabase não encontrada. Verifique se 'supabase' está no seu `requirements.txt`.")
    st.stop()

try:
    import psycopg2
    from sqlalchemy import text
    from dateutil.relativedelta import relativedelta # NOVO: Para cálculo de datas
except ImportError:
    st.error("Bibliotecas essenciais não encontradas. Adicione 'psycopg2-binary', 'SQLAlchemy' e 'python-dateutil' ao seu `requirements.txt`.")
    st.stop()

# --- CONFIGURAÇÕES GLOBAIS ---
ASSETS_DIR = "LogoTipo"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "Icone.png")

# --- CONEXÃO COM O BANCO DE DADOS ---
try:
    conn = st.connection("postgresql", type="sql")
except Exception as e:
    st.error(f"❌ Falha ao configurar a conexão com o banco de dados: {e}")
    st.info("Verifique se seu arquivo 'secrets.toml' está configurado corretamente com a URL de conexão do Supabase.")
    st.stop()

# --- CONEXÃO COM O SUPABASE STORAGE ---
try:
    supabase_url = st.secrets["supabase"]["url"]
    supabase_key = st.secrets["supabase"]["service_key"]
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception as e:
    st.error(f"❌ Falha ao configurar a conexão com o Supabase Storage: {e}")
    st.info("Verifique se seu arquivo 'secrets.toml' está configurado com a seção [supabase] e as chaves 'url' e 'service_key'.")
    st.stop()

# --- REATORADO: INICIALIZAÇÃO DO BANCO DE DADOS ---
def init_db():
    """
    Inicializa o banco de dados, criando e atualizando as tabelas para o novo modelo de parcelas.
    """
    try:
        with conn.session as s:
            # Tabela de Apólices Simplificada
            s.execute(text('''
                CREATE TABLE IF NOT EXISTS apolices (
                    id SERIAL PRIMARY KEY,
                    seguradora TEXT NOT NULL,
                    cliente TEXT NOT NULL,
                    numero_apolice TEXT NOT NULL UNIQUE,
                    placa TEXT,
                    tipo_seguro TEXT NOT NULL,
                    valor_parcela REAL NOT NULL,
                    comissao REAL,
                    data_inicio_vigencia DATE NOT NULL,
                    quantidade_parcelas INTEGER NOT NULL,
                    dia_vencimento INTEGER NOT NULL, -- Apenas o dia (ex: 10)
                    contato TEXT NOT NULL,
                    email TEXT,
                    observacoes TEXT,
                    status TEXT NOT NULL DEFAULT 'Ativa',
                    caminho_pdf_apolice TEXT,
                    caminho_pdf_boletos TEXT,
                    data_cadastro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    data_atualizacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            '''))

            # NOVA Tabela de Parcelas
            s.execute(text('''
                CREATE TABLE IF NOT EXISTS parcelas (
                    id SERIAL PRIMARY KEY,
                    apolice_id INTEGER NOT NULL,
                    numero_parcela INTEGER NOT NULL,
                    data_vencimento DATE NOT NULL,
                    valor REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pendente', -- Pendente, Paga, Atrasada
                    data_pagamento DATE,
                    FOREIGN KEY (apolice_id) REFERENCES apolices(id) ON DELETE CASCADE
                )
            '''))

            # Tabela de Histórico (sem alterações)
            s.execute(text('''
                CREATE TABLE IF NOT EXISTS historico (
                    id SERIAL PRIMARY KEY,
                    apolice_id INTEGER NOT NULL,
                    usuario TEXT NOT NULL,
                    acao TEXT NOT NULL,
                    detalhes TEXT,
                    data_acao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (apolice_id) REFERENCES apolices(id) ON DELETE CASCADE
                )
            '''))

            # Tabela de Usuários (sem alterações)
            s.execute(text('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    nome TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    senha TEXT NOT NULL,
                    perfil TEXT NOT NULL DEFAULT 'user',
                    data_cadastro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            '''))

            # Cria usuário admin padrão se não existir
            user_exists = s.execute(text("SELECT id FROM usuarios WHERE email = :email"), {'email': 'adm@moreiraseg.com.br'}).fetchone()
            if not user_exists:
                s.execute(
                    text("INSERT INTO usuarios (nome, email, senha, perfil) VALUES (:nome, :email, :senha, :perfil)"),
                    {'nome': 'Administrador', 'email': 'adm@moreiraseg.com.br', 'senha': 'Salmo@139', 'perfil': 'admin'}
                )
            s.commit()
    except Exception as e:
        st.error(f"❌ Falha grave ao inicializar as tabelas do banco de dados: {e}")
        st.stop()

# --- FUNÇÕES DE LÓGICA DO SISTEMA (ATUALIZADAS) ---

def add_historico(apolice_id, usuario_email, acao, detalhes=""):
    try:
        with conn.session as s:
            s.execute(
                text('INSERT INTO historico (apolice_id, usuario, acao, detalhes) VALUES (:apolice_id, :usuario, :acao, :detalhes)'),
                {'apolice_id': apolice_id, 'usuario': usuario_email, 'acao': acao, 'detalhes': detalhes}
            )
            s.commit()
    except Exception as e:
        st.warning(f"⚠️ Não foi possível registrar a ação no histórico: {e}")

def salvar_ficheiros_supabase(ficheiro, numero_apolice, cliente, tipo_pasta):
    """Salva um único ficheiro no Supabase Storage."""
    try:
        bucket_name = st.secrets["buckets"][tipo_pasta]
        safe_cliente = re.sub(r'[^a-zA-Z0-9\s-]', '', cliente).strip().replace(' ', '_')
        file_bytes = ficheiro.getvalue()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        destination_path = f"{safe_cliente}/{numero_apolice}/{timestamp}_{ficheiro.name}"

        supabase.storage.from_(bucket_name).upload(
            path=destination_path,
            file=file_bytes,
            file_options={"content-type": ficheiro.type}
        )
        public_url = supabase.storage.from_(bucket_name).get_public_url(destination_path)
        return public_url
    except KeyError as e:
        st.error(f"Erro de chave nos 'Secrets': A chave '{e}' não foi encontrada.")
        return None
    except Exception as e:
        st.error(f"❌ Falha no upload para o Supabase Storage: {e}")
        return None

def get_apolices(search_term=None):
    """Busca apólices no banco de dados."""
    try:
        query = "SELECT * FROM apolices"
        params = {}
        if search_term:
            query += " WHERE numero_apolice ILIKE :term OR cliente ILIKE :term OR placa ILIKE :term"
            params['term'] = f"%{search_term}%"
        query += " ORDER BY data_cadastro DESC"
        df = conn.query(query, params=params, ttl=60)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar apólices: {e}")
        return pd.DataFrame()

def get_parcelas_da_apolice(apolice_id):
    """Busca todas as parcelas de uma apólice específica."""
    try:
        query = "SELECT * FROM parcelas WHERE apolice_id = :apolice_id ORDER BY numero_parcela ASC"
        df = conn.query(query, params={'apolice_id': apolice_id}, ttl=10)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar as parcelas: {e}")
        return pd.DataFrame()

# --- RENDERIZAÇÃO DA INTERFACE ---

def render_cadastro_form():
    """Renderiza o formulário de cadastro com a nova lógica de parcelas."""
    st.title("➕ Cadastrar Nova Apólice")
    with st.form("form_cadastro", clear_on_submit=False):
        st.subheader("Dados da Apólice")
        col1, col2 = st.columns(2)
        with col1:
            seguradora = st.text_input("Seguradora*", max_chars=50)
            numero_apolice = st.text_input("Número da Apólice*", max_chars=50)
            tipo_seguro = st.selectbox("Tipo de Seguro*", ["Automóvel", "RCO", "Vida", "Residencial", "Empresarial", "Saúde", "Viagem", "Fiança", "Outro"])
        with col2:
            cliente = st.text_input("Cliente*", max_chars=100)
            placa = st.text_input("🚗 Placa do Veículo (Obrigatório para Auto/RCO)", max_chars=10)
            tipo_cobranca = st.selectbox("Tipo de Cobrança*", ["Boleto", "Faturamento", "Cartão de Crédito", "Débito em Conta"])

        st.subheader("Vigência e Parcelamento")
        col1, col2, col3 = st.columns(3)
        with col1:
            data_inicio = st.date_input("📅 Início de Vigência*")
        with col2:
            # NOVO: Apenas o dia do vencimento
            dia_vencimento = st.number_input("Dia do Vencimento*", min_value=1, max_value=31, value=10)
        with col3:
            # NOVO: Quantidade de parcelas
            quantidade_parcelas = st.number_input("Quantidade de Parcelas*", min_value=1, max_value=24, value=10)

        st.subheader("Valores e Comissão")
        col1, col2 = st.columns(2)
        with col1:
            valor_parcela = st.text_input("💰 Valor de Cada Parcela (R$)*", value="0,00")
        with col2:
            comissao = st.number_input("💼 Comissão (%)", min_value=0.0, max_value=100.0, value=10.0, step=0.5, format="%.2f")

        st.subheader("Dados de Contato e Anexos")
        contato = st.text_input("📱 Contato do Cliente*", max_chars=100)
        email = st.text_input("📧 E-mail do Cliente", max_chars=100)
        observacoes = st.text_area("📝 Observações", height=100)
        pdf_apolice = st.file_uploader("📎 Anexar PDF da Apólice (Opcional)", type=["pdf"])
        pdf_boletos = st.file_uploader("📎 Anexar Carnê de Boletos (PDF único, opcional)", type=["pdf"])

        submitted = st.form_submit_button("💾 Salvar Apólice e Gerar Parcelas", use_container_width=True)

        if submitted:
            # --- VALIDAÇÃO DOS CAMPOS ---
            campos_obrigatorios = {
                "Seguradora": seguradora, "Cliente": cliente, "Número da Apólice": numero_apolice,
                "Contato": contato, "Valor de Cada Parcela": valor_parcela
            }
            if float(valor_parcela.replace(',', '.')) <= 0:
                st.error("O valor da parcela deve ser maior que zero.")
                return

            if any(not v for v in campos_obrigatorios.values()):
                st.error(f"Preencha todos os campos obrigatórios: {', '.join(k for k, v in campos_obrigatorios.items() if not v)}")
                return

            # --- LÓGICA DE UPLOAD ---
            caminho_pdf_apolice_url = None
            if pdf_apolice:
                st.info("Fazendo upload do PDF da apólice...")
                caminho_pdf_apolice_url = salvar_ficheiros_supabase(pdf_apolice, numero_apolice, cliente, 'apolices')
                if not caminho_pdf_apolice_url:
                    st.error("Falha no upload do PDF da apólice. O cadastro foi cancelado.")
                    return

            caminho_pdf_boletos_url = None
            if pdf_boletos:
                st.info("Fazendo upload do carnê de boletos...")
                caminho_pdf_boletos_url = salvar_ficheiros_supabase(pdf_boletos, numero_apolice, cliente, 'boletos')
                if not caminho_pdf_boletos_url:
                    st.error("Falha no upload do carnê de boletos. O cadastro foi cancelado.")
                    return

            # --- LÓGICA DE BANCO DE DADOS (TRANSAÇÃO) ---
            try:
                with conn.session as s:
                    # 1. INSERE A APÓLICE PRINCIPAL
                    apolice_data = {
                        'seguradora': seguradora, 'cliente': cliente, 'numero_apolice': numero_apolice,
                        'placa': placa, 'tipo_seguro': tipo_seguro,
                        'valor_parcela': float(valor_parcela.replace(',', '.')), 'comissao': comissao,
                        'data_inicio_vigencia': data_inicio, 'quantidade_parcelas': quantidade_parcelas,
                        'dia_vencimento': dia_vencimento, 'contato': contato, 'email': email,
                        'observacoes': observacoes, 'status': 'Ativa',
                        'caminho_pdf_apolice': caminho_pdf_apolice_url,
                        'caminho_pdf_boletos': caminho_pdf_boletos_url
                    }
                    query_apolice = text('''
                        INSERT INTO apolices (seguradora, cliente, numero_apolice, placa, tipo_seguro, valor_parcela, comissao, data_inicio_vigencia, quantidade_parcelas, dia_vencimento, contato, email, observacoes, status, caminho_pdf_apolice, caminho_pdf_boletos)
                        VALUES (:seguradora, :cliente, :numero_apolice, :placa, :tipo_seguro, :valor_parcela, :comissao, :data_inicio_vigencia, :quantidade_parcelas, :dia_vencimento, :contato, :email, :observacoes, :status, :caminho_pdf_apolice, :caminho_pdf_boletos)
                        RETURNING id
                    ''')
                    apolice_id = s.execute(query_apolice, apolice_data).scalar_one()

                    # 2. CALCULA E GERA AS PARCELAS
                    lista_parcelas_para_db = []
                    data_base = data_inicio
                    # Se o dia de vencimento for menor que o dia de início, a primeira parcela é no mês seguinte.
                    if dia_vencimento < data_inicio.day:
                        data_base += relativedelta(months=1)

                    for i in range(quantidade_parcelas):
                        # Constrói a data de vencimento para o mês corrente do cálculo
                        vencimento_calculado = date(data_base.year, data_base.month, dia_vencimento)
                        parcela = {
                            "apolice_id": apolice_id,
                            "numero_parcela": i + 1,
                            "data_vencimento": vencimento_calculado,
                            "valor": float(valor_parcela.replace(',', '.')),
                            "status": "Pendente"
                        }
                        lista_parcelas_para_db.append(parcela)
                        # Avança um mês para a próxima iteração
                        data_base += relativedelta(months=1)

                    # 3. INSERE TODAS AS PARCELAS DE UMA VEZ
                    if lista_parcelas_para_db:
                        query_parcelas = text('''
                            INSERT INTO parcelas (apolice_id, numero_parcela, data_vencimento, valor, status)
                            VALUES (:apolice_id, :numero_parcela, :data_vencimento, :valor, :status)
                        ''')
                        s.execute(query_parcelas, lista_parcelas_para_db)

                    s.commit() # Confirma a transação
                    add_historico(apolice_id, st.session_state.get('user_email', 'sistema'), 'Cadastro de Apólice', f"Apólice '{numero_apolice}' e {quantidade_parcelas} parcelas geradas.")
                    st.success(f"🎉 Apólice '{numero_apolice}' e suas {quantidade_parcelas} parcelas foram salvas com sucesso!")
                    st.balloons()

            except psycopg2.errors.UniqueViolation:
                st.error(f"❌ Erro: O número de apólice '{numero_apolice}' já existe no sistema!")
            except Exception as e:
                st.error(f"❌ Ocorreu um erro inesperado ao salvar no banco de dados: {e}")


def render_pesquisa_e_edicao():
    st.title("🔍 Pesquisar e Visualizar Apólices")
    search_term = st.text_input("Pesquisar por Nº Apólice, Cliente ou Placa:", key="search_box")
    resultados = get_apolices(search_term=search_term)

    if resultados.empty and search_term:
        st.info("Nenhuma apólice encontrada com o termo pesquisado.")
    elif not resultados.empty:
        st.success(f"{len(resultados)} apólice(s) encontrada(s).")
        for index, apolice_row in resultados.iterrows():
            with st.expander(f"**{apolice_row['numero_apolice']}** - {apolice_row['cliente']}"):
                apolice_id = apolice_row['id']
                st.subheader("Detalhes da Apólice")
                col1, col2, col3 = st.columns(3)
                col1.metric("Valor da Parcela", f"R$ {apolice_row.get('valor_parcela', 0.0):,.2f}")
                col2.metric("Quantidade de Parcelas", apolice_row.get('quantidade_parcelas', 0))
                col3.metric("Dia do Vencimento", f"Todo dia {apolice_row.get('dia_vencimento', 0)}")
                
                # Links para os PDFs
                if apolice_row.get('caminho_pdf_apolice'):
                    st.link_button("Ver PDF da Apólice", apolice_row['caminho_pdf_apolice'])
                if apolice_row.get('caminho_pdf_boletos'):
                    st.link_button("Ver Carnê de Boletos", apolice_row['caminho_pdf_boletos'])

                st.divider()
                st.subheader("Situação das Parcelas")
                parcelas_df = get_parcelas_da_apolice(apolice_id)

                if not parcelas_df.empty:
                    # Formatação para exibição
                    parcelas_df['data_vencimento'] = pd.to_datetime(parcelas_df['data_vencimento']).dt.strftime('%d/%m/%Y')
                    parcelas_df['valor'] = parcelas_df['valor'].apply(lambda x: f"R$ {x:,.2f}")
                    st.dataframe(parcelas_df[['numero_parcela', 'data_vencimento', 'valor', 'status']], use_container_width=True)
                else:
                    st.warning("Nenhuma parcela encontrada para esta apólice.")
                
                # Adicionar lógica de edição aqui se necessário no futuro


# --- FUNÇÃO PRINCIPAL E ROTEAMENTO ---
def main():
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
            # Layout da tela de login centralizada
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
                        # A função login_user precisa ser definida ou adaptada
                        # Por enquanto, usando um login simples para demonstração
                        with conn.session as s:
                            user_query = text("SELECT * FROM usuarios WHERE email = :email AND senha = :senha")
                            user_df = pd.read_sql(user_query, s, params={'email': email, 'senha': senha})
                        if not user_df.empty:
                            usuario = user_df.to_dict('records')[0]
                            st.session_state.user_email = usuario['email']
                            st.session_state.user_nome = usuario['nome']
                            st.session_state.user_perfil = usuario['perfil']
                            st.rerun()
                        else:
                            st.error("Credenciais inválidas. Tente novamente.")
            return

        with st.sidebar:
            st.title(f"Olá, {st.session_state.user_nome.split()[0]}!")
            st.write(f"Perfil: `{st.session_state.user_perfil.capitalize()}`")
            st.divider()
            menu_options = [
                # "📊 Painel de Controle", # Desabilitado por enquanto
                "➕ Cadastrar Apólice",
                "🔍 Pesquisar e Visualizar Apólices",
            ]
            if st.session_state.user_perfil == 'admin':
                # menu_options.append("⚙️ Configurações") # Desabilitado por enquanto
                pass
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

        if menu_opcao == "➕ Cadastrar Apólice":
            render_cadastro_form()
        elif menu_opcao == "🔍 Pesquisar e Visualizar Apólices":
            render_pesquisa_e_edicao()

    except Exception as e:
        st.error("Ocorreu um erro crítico na aplicação.")
        st.exception(e)

if __name__ == "__main__":
    main()
