# moreiraseg_sistema.py
# VERSÃO ADAPTADA PARA SUPABASE COM ST.CONNECTION

import streamlit as st
import pandas as pd
import datetime
from datetime import date, timedelta
import os
import re

# Tente importar as bibliotecas necessárias, mostrando erros amigáveis.
try:
    from google.cloud import storage
    from google.oauth2 import service_account
except ImportError:
    st.error("Biblioteca do Google Cloud não encontrada. Verifique o seu ficheiro `requirements.txt`.")
    st.stop()

try:
    import psycopg2
    from sqlalchemy import text # Necessário para o novo método de conexão
except ImportError:
    st.error("Bibliotecas do banco de dados não encontradas. Adicione 'psycopg2-binary' e 'SQLAlchemy' ao seu `requirements.txt`.")
    st.stop()

# --- CONFIGURAÇÕES GLOBAIS ---
ASSETS_DIR = "LogoTipo"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "Icone.png")

# --- CONEXÃO COM O BANCO DE DADOS (MÉTODO MODERNO) ---
# Inicializa a conexão com o banco de dados usando os segredos do Streamlit.
# O Streamlit automaticamente encontrará a seção [connections.postgresql] no seu secrets.toml
try:
    conn = st.connection("postgresql", type="sql")
except Exception as e:
    st.error(f"❌ Falha ao configurar a conexão com o banco de dados: {e}")
    st.info("Verifique se seu arquivo 'secrets.toml' está configurado corretamente com a URL de conexão do Supabase.")
    st.stop()


# --- FUNÇÕES DE BANCO DE DADOS (ATUALIZADAS PARA ST.CONNECTION) ---

def init_db():
    """
    Inicializa o banco de dados, cria e atualiza as tabelas conforme necessário.
    Usa conn.session para executar múltiplos comandos em uma transação.
    """
    try:
        with conn.session as s:
            s.execute(text('''
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
            '''))
            colunas_para_adicionar = {
                "tipo_cobranca": "TEXT",
                "numero_parcelas": "INTEGER",
                "valor_primeira_parcela": "REAL"
            }
            for coluna, tipo in colunas_para_adicionar.items():
                # Usa a sintaxe da SQLAlchemy para evitar SQL Injection
                check_col_query = text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='apolices' AND column_name=:col
                """)
                if not s.execute(check_col_query, {"col": coluna}).fetchone():
                    s.execute(text(f"ALTER TABLE apolices ADD COLUMN {coluna} {tipo}"))

            s.execute(text('''
                CREATE TABLE IF NOT EXISTS boletos (
                    id SERIAL PRIMARY KEY,
                    apolice_id INTEGER NOT NULL,
                    caminho_pdf TEXT NOT NULL,
                    nome_arquivo TEXT,
                    data_upload TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (apolice_id) REFERENCES apolices(id) ON DELETE CASCADE
                )
            '''))
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
            
            # Adiciona usuário administrador se não existir
            user_exists = s.execute(text("SELECT id FROM usuarios WHERE email = :email"), {'email': 'adm@moreiraseg.com.br'}).fetchone()
            if not user_exists:
                s.execute(
                    text("INSERT INTO usuarios (nome, email, senha, perfil) VALUES (:nome, :email, :senha, :perfil)"),
                    {'nome': 'Administrador', 'email': 'adm@moreiraseg.com.br', 'senha': 'Salmo@139', 'perfil': 'admin'}
                )
            s.commit()
    except Exception as e:
        st.error(f"❌ Falha ao inicializar as tabelas do banco de dados: {e}")
        st.stop()


# --- FUNÇÕES DE UPLOAD (Com indentação corrigida) ---
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
# --- FUNÇÕES DE LÓGICA DO SISTEMA (ATUALIZADAS) ---

def add_historico(apolice_id, usuario_email, acao, detalhes=""):
    try:
        conn.execute(
            'INSERT INTO historico (apolice_id, usuario, acao, detalhes) VALUES (:apolice_id, :usuario, :acao, :detalhes)',
            params={'apolice_id': apolice_id, 'usuario': usuario_email, 'acao': acao, 'detalhes': detalhes}
        )
    except Exception as e:
        st.warning(f"⚠️ Não foi possível registrar a ação no histórico: {e}")

def add_boletos_db(apolice_id, boletos_info):
    try:
        for url, nome in boletos_info:
            conn.execute(
                'INSERT INTO boletos (apolice_id, caminho_pdf, nome_arquivo) VALUES (:apolice_id, :caminho_pdf, :nome_arquivo)',
                params={'apolice_id': apolice_id, 'caminho_pdf': url, 'nome_arquivo': nome}
            )
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
        query = '''
            INSERT INTO apolices (
                seguradora, cliente, numero_apolice, placa, tipo_seguro, tipo_cobranca,
                numero_parcelas, valor_primeira_parcela, valor_da_parcela, comissao,
                data_inicio_de_vigencia, data_final_de_vigencia, contato, email,
                observacoes, status, caminho_pdf
            ) VALUES (
                :seguradora, :cliente, :numero_apolice, :placa, :tipo_seguro, :tipo_cobranca,
                :numero_parcelas, :valor_primeira_parcela, :valor_da_parcela, :comissao,
                :data_inicio_de_vigencia, :data_final_de_vigencia, :contato, :email,
                :observacoes, :status, :caminho_pdf
            )
            RETURNING id
        '''
        # .execute() retorna um objeto Result; .scalar_one() pega o primeiro valor da primeira linha.
        apolice_id = conn.execute(query, params=data).scalar_one()

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
        update_data['data_atualizacao'] = datetime.datetime.now(datetime.timezone.utc)
        set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
        query = f"UPDATE apolices SET {set_clause} WHERE id = :apolice_id"
        
        # Adiciona o apolice_id ao dicionário de parâmetros
        params = update_data.copy()
        params['apolice_id'] = apolice_id
        
        conn.execute(text(query), params=params)

        detalhes = f"Campos atualizados: {', '.join(update_data.keys())}"
        add_historico(apolice_id, st.session_state.get('user_email', 'sistema'), 'Atualização', detalhes)
        return True
    except Exception as e:
        st.error(f"❌ Erro ao atualizar a apólice: {e}")
        return False

def delete_apolice(apolice_id):
    try:
        conn.execute('DELETE FROM apolices WHERE id = :id', params={'id': apolice_id})
        return True
    except Exception as e:
        st.error(f"❌ Erro ao apagar a apólice: {e}")
        return False

def get_apolices(search_term=None):
    """Busca apólices usando o cache nativo do st.connection."""
    try:
        query = "SELECT * FROM apolices"
        params = {}
        if search_term:
            query += " WHERE numero_apolice ILIKE :term OR cliente ILIKE :term OR placa ILIKE :term"
            params['term'] = f"%{search_term}%"
        query += " ORDER BY data_final_de_vigencia ASC"
        
        # conn.query usa cache automaticamente. ttl=60 significa que os dados serão atualizados a cada 60 segundos.
        df = conn.query(query, params=params, ttl=60)
    except Exception as e:
        st.error(f"Erro ao carregar apólices: {e}")
        return pd.DataFrame()

    if not df.empty:
        df['data_final_de_vigencia'] = pd.to_datetime(df['data_final_de_vigencia'], errors='coerce')
        today = pd.to_datetime(date.today())
        df['dias_restantes'] = (df['data_final_de_vigencia'] - today).dt.days

        def define_prioridade(dias):
            if pd.isna(dias): return '⚪ Indefinida'
            if dias <= 15: return '🔥 Urgente'
            elif dias <= 30: return '⚠️ Alta'
            elif dias <= 60: return '⚠️ Média'
            else: return '✅ Baixa'
        df['prioridade'] = df['dias_restantes'].apply(define_prioridade)
        
        df.loc[df['dias_restantes'] <= 30, 'status'] = 'Pendente'
    return df

def get_apolice_details(apolice_id):
    try:
        # conn.query retorna um DataFrame. Pegamos a primeira linha.
        apolice_df = conn.query("SELECT * FROM apolices WHERE id = :id", params={'id': apolice_id}, ttl=10)
        historico_df = conn.query("SELECT * FROM historico WHERE apolice_id = :id ORDER BY data_acao DESC", params={'id': apolice_id}, ttl=10)
        
        apolice = apolice_df.to_dict('records')[0] if not apolice_df.empty else None
        historico = historico_df.to_dict('records') if not historico_df.empty else []
        
        return apolice, historico
    except Exception as e:
        st.error(f"Erro ao buscar detalhes da apólice: {e}")
        return None, []

def login_user(email, senha):
    try:
        # conn.query retorna um DataFrame. Pegamos a primeira linha.
        user_df = conn.query("SELECT * FROM usuarios WHERE email = :email AND senha = :senha", params={'email': email, 'senha': senha}, ttl=10)
        if not user_df.empty:
            return user_df.to_dict('records')[0]
        return None
    except Exception as e:
        st.error(f"Erro durante o login: {e}")
        return None

# --- RENDERIZAÇÃO DA INTERFACE (a maioria sem alterações) ---

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
    urgentes_df = apolices_df[apolices_df['dias_restantes'].fillna(999) <= 15]
    col4.metric("Apólices Urgentes", len(urgentes_df), "Vencem em até 15 dias")
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
                    apolice_id = apolice_row['id']
                    st.subheader("📝 Editar Informações da Apólice")
                    with st.form(f"edit_form_{apolice_id}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            novo_valor_parcelas = st.text_input("Valor das Demais Parcelas (R$)", value=f"{apolice_row.get('valor_da_parcela', 0.0):.2f}", key=f"valor_{apolice_id}")
                            novo_contato = st.text_input("Contato do Cliente", value=apolice_row.get('contato', ''), key=f"contato_{apolice_id}")
                            # Convertendo para objeto date se não for NaT
                            data_inicio_atual = apolice_row.get('data_inicio_de_vigencia')
                            if pd.isna(data_inicio_atual): data_inicio_atual = date.today()
                            nova_data_inicio = st.date_input("📅 Início de Vigência", value=data_inicio_atual, format="DD/MM/YYYY", key=f"data_inicio_{apolice_id}")
                        with col2:
                            novo_num_parcelas = st.number_input("Nº de Parcelas", min_value=1, max_value=12, value=int(apolice_row.get('numero_parcelas', 1)), key=f"parcelas_{apolice_id}")
                            novo_email = st.text_input("E-mail do Cliente", value=apolice_row.get('email', ''), key=f"email_{apolice_id}")
                            # Convertendo para objeto date se não for NaT
                            data_fim_atual = apolice_row.get('data_final_de_vigencia')
                            if pd.isna(data_fim_atual): data_fim_atual = date.today()
                            nova_data_fim = st.date_input("📅 Fim de Vigência", value=data_fim_atual, format="DD/MM/YYYY", key=f"data_fim_{apolice_id}")
                        edit_submitted = st.form_submit_button("Salvar Alterações")
                        if edit_submitted:
                            update_data = {
                                'valor_da_parcela': float(novo_valor_parcelas.replace(',', '.')),
                                'numero_parcelas': novo_num_parcelas,
                                'contato': novo_contato,
                                'email': novo_email,
                                'data_inicio_de_vigencia': nova_data_inicio,
                                'data_final_de_vigencia': nova_data_fim
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
                    st.divider()
                    st.subheader("Zona de Perigo")
                    with st.form(f"delete_form_{apolice_id}"):
                        st.warning("Atenção: Apagar uma apólice é uma ação permanente e não pode ser desfeita.")
                        delete_submitted = st.form_submit_button("🗑️ Apagar Apólice Permanentemente")
                        if delete_submitted:
                            if delete_apolice(apolice_id):
                                st.success("Apólice apagada com sucesso!")
                                st.rerun()

def render_cadastro_form():
    st.title("➕ Cadastrar Nova Apólice")
    with st.form("form_cadastro", clear_on_submit=True):
        st.subheader("Dados da Apólice")
        col1, col2 = st.columns(2)
        with col1:
            seguradora = st.text_input("Seguradora*", max_chars=50)
            numero_apolice = st.text_input("Número da Apólice*", max_chars=50)
            tipo_seguro = st.selectbox("Tipo de Seguro*", ["Automóvel", "RCO", "Vida", "Residencial", "Empresarial", "Saúde", "Viagem", "Fiança", "Outro"])
            data_inicio = st.date_input("📅 Início de Vigência*", format="DD/MM/YYYY")
        with col2:
            cliente = st.text_input("Cliente*", max_chars=100)
            placa = st.text_input("🚗 Placa do Veículo (Obrigatório para Auto/RCO)", max_chars=10)
            tipo_cobranca = st.selectbox("Tipo de Cobrança*", ["Boleto", "Faturamento", "Cartão de Crédito", "Débito em Conta"])
            data_fim_calculada = data_inicio + timedelta(days=365)
            st.date_input("📅 Fim de Vigência (Automático)", value=data_fim_calculada, format="DD/MM/YYYY", disabled=True)
        
        st.subheader("Valores e Comissão")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            valor_primeira_parcela = st.text_input("💰 Valor da 1ª Parcela (R$)", value="0,00")
        with col2:
            valor_demais_parcelas = st.text_input("💰 Valor das Demais Parcelas (R$)*", value="0,00")
        with col3:
            numero_parcelas = st.selectbox("Nº de Parcelas", options=list(range(1, 13)), index=0)
        with col4:
            comissao = st.number_input("💼 Comissão (%)", min_value=0.0, max_value=100.0, value=10.0, step=0.5, format="%.2f")
        st.subheader("Dados de Contato e Outros")
        contato = st.text_input("📱 Contato do Cliente*", max_chars=100)
        email = st.text_input("📧 E-mail do Cliente", max_chars=100)
        observacoes = st.text_area("📝 Observações", height=100)
        st.subheader("Anexos")
        pdf_file = st.file_uploader("📎 Anexar PDF da Apólice (Opcional)", type=["pdf"])
        boletos_files = st.file_uploader("📎 Anexar Boletos (Opcional)", type=["pdf"], accept_multiple_files=True)
        submitted = st.form_submit_button("💾 Salvar Apólice", use_container_width=True)
        if submitted:
            campos_obrigatorios = {
                "Seguradora": seguradora, "Cliente": cliente, "Número da Apólice": numero_apolice,
                "Valor das Demais Parcelas": valor_demais_parcelas, "Contato": contato
            }
            campos_vazios = [nome for nome, valor in campos_obrigatorios.items() if not valor]
            if tipo_seguro in ["Automóvel", "RCO"] and not placa:
                campos_vazios.append("Placa (obrigatória para Auto/RCO)")
            if campos_vazios:
                st.error(f"Por favor, preencha os seguintes campos obrigatórios: {', '.join(campos_vazios)}")
                return
            caminho_pdf_apolice = None
            if pdf_file:
                st.info("Fazendo upload do PDF da apólice...")
                urls = salvar_ficheiros_gcs([pdf_file], numero_apolice, cliente, 'apolices')
                if urls:
                    caminho_pdf_apolice = urls[0]
                else:
                    st.error("Falha no upload do PDF da apólice.")
                    return
            
            data_fim = data_inicio + timedelta(days=365)
            
            apolice_data = {
                'seguradora': seguradora, 'cliente': cliente, 'numero_apolice': numero_apolice,
                'placa': placa, 'tipo_seguro': tipo_seguro, 'tipo_cobranca': tipo_cobranca,
                'numero_parcelas': int(numero_parcelas), 'valor_primeira_parcela': valor_primeira_parcela,
                'valor_da_parcela': valor_demais_parcelas, 'comissao': comissao,
                'data_inicio_de_vigencia': data_inicio, 'data_final_de_vigencia': data_fim,
                'contato': contato, 'email': email, 'observacoes': observacoes,
                'status': 'Ativa', 'caminho_pdf': caminho_pdf_apolice if caminho_pdf_apolice else ""
            }
            apolice_id = add_apolice(apolice_data)
            if apolice_id:
                st.success(f"🎉 Apólice '{numero_apolice}' cadastrada com sucesso!")
                if caminho_pdf_apolice:
                    st.success("PDF da apólice salvo na nuvem!")
                if boletos_files:
                    st.info("Fazendo upload dos boletos...")
                    urls_boletos = salvar_ficheiros_gcs(boletos_files, numero_apolice, cliente, 'boletos')
                    if urls_boletos:
                        boletos_info = list(zip(urls_boletos, [f.name for f in boletos_files]))
                        add_boletos_db(apolice_id, boletos_info)
                        st.success(f"{len(urls_boletos)} boleto(s) salvo(s) na nuvem com sucesso!")
                    else:
                        st.warning("A apólice foi salva, mas ocorreu uma falha no upload dos boletos.")
                st.balloons()
            else:
                st.error("Falha ao salvar a apólice no banco de dados.")

def render_configuracoes():
    st.title("⚙️ Configurações do Sistema")
    tab1, tab2 = st.tabs(["Gerenciar Usuários", "Backup e Restauração"])
    with tab1:
        st.subheader("Usuários Cadastrados")
        try:
            # Atualizado para conn.query
            usuarios_df = conn.query("SELECT id, nome, email, perfil, data_cadastro FROM usuarios", ttl=10)
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
                            conn.execute(
                                "INSERT INTO usuarios (nome, email, senha, perfil) VALUES (:nome, :email, :senha, :perfil)",
                                params={'nome': nome, 'email': email, 'senha': senha, 'perfil': perfil}
                            )
                            st.success(f"Usuário '{nome}' adicionado com sucesso!")
                            st.rerun()
                        except psycopg2.errors.UniqueViolation:
                            st.error(f"Erro: O e-mail '{email}' já está cadastrado.")
                        except Exception as e:
                            st.error(f"Erro ao adicionar usuário: {e}")
    with tab2:
        st.subheader("Backup de Dados (Exportar)")
        # Atualizado para conn.query
        all_data_df = conn.query("SELECT * FROM apolices", ttl=10)
        csv_data = all_data_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Exportar Backup Completo (CSV)",
            data=csv_data,
            file_name=f"backup_completo_apolices_{date.today()}.csv",
            mime="text/csv"
        )

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
