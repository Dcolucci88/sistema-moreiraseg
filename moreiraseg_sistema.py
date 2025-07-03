# moreiraseg_sistema.py
# VERSÃO COM NOVOS CAMPOS DE CADASTRO E MELHORIAS

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
    
    Args:
        ficheiros (list): Lista de ficheiros do st.file_uploader.
        numero_apolice (str): Número da apólice para organizar.
        cliente (str): Nome do cliente.
        tipo_pasta (str): 'apolices' ou 'boletos'.

    Returns:
        list: Lista de URLs públicas dos ficheiros.
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

# ... (outras funções de lógica como update_apolice, get_apolices, etc.)

# --- RENDERIZAÇÃO DA INTERFACE ---

def render_cadastro_form():
    """Renderiza o formulário para cadastrar uma nova apólice com as novas melhorias."""
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
            data_fim = st.date_input("📅 Fim de Vigência*", min_value=data_inicio + datetime.timedelta(days=1) if data_inicio else date.today(), format="DD/MM/YYYY")

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

            apolice_data = {
                'seguradora': seguradora, 'cliente': cliente, 'numero_apolice': numero_apolice,
                'placa': placa, 'tipo_seguro': tipo_seguro, 'tipo_cobranca': tipo_cobranca,
                'numero_parcelas': numero_parcelas, 'valor_primeira_parcela': valor_primeira_parcela, 
                'valor_da_parcela': valor_demais_parcelas, 'comissao': comissao, 
                'data_inicio_de_vigencia': data_inicio, 'data_final_de_vigencia': data_fim, 
                'contato': contato, 'email': email, 'observacoes': observacoes, 
                'status': 'Pendente', 'caminho_pdf': caminho_pdf_apolice if caminho_pdf_apolice else ""
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

# --- FUNÇÃO PRINCIPAL ---
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
            # ... (código da barra lateral inalterado)

        # ... (código do logótipo principal inalterado)

        # Bloco de execução principal
        # ... (código de roteamento de páginas inalterado)
        menu_options = [
            "📊 Painel de Controle",
            "➕ Cadastrar Apólice",
            "🔍 Consultar Apólices",
            "🔄 Gerenciar Apólices",
        ]
        if st.session_state.get('user_perfil') == 'admin':
            menu_options.append("⚙️ Configurações")

        with st.sidebar:
             st.title(f"Olá, {st.session_state.user_nome.split()[0]}!")
             st.write(f"Perfil: `{st.session_state.user_perfil.capitalize()}`")
             try:
                 st.image(ICONE_PATH, width=80)
             except Exception:
                 st.write("Menu")
             st.divider()
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
        # Adicione as outras chamadas de renderização aqui
        # else:
        #     st.write("Página em construção.")

    except Exception as e:
        st.error("Ocorreu um erro crítico na aplicação.")
        st.exception(e)

if __name__ == "__main__":
    main()
