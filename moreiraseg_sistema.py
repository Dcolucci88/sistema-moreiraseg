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

# Nome do arquivo do banco de dados (continuará local)
DB_NAME = "moreiraseg.db"

# Caminhos relativos para os assets
ASSETS_DIR = "assets"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "icone.png")

# --- FUNÇÕES DE BANCO DE DADOS (permanecem as mesmas) ---

def get_connection():
    """Retorna uma conexão com o banco de dados SQLite."""
    return sqlite3.connect(DB_NAME)

def init_db():
    """
    Inicializa o banco de dados, cria as tabelas se não existirem
    e executa a migração para garantir que todas as colunas estão presentes.
    """
    try:
        with get_connection() as conn:
            c = conn.cursor()
            # ... (O restante da função init_db permanece exatamente igual)
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

# --- NOVA FUNÇÃO DE UPLOAD PARA O GOOGLE CLOUD STORAGE ---

def salvar_pdf_gcs(uploaded_file, numero_apolice, cliente):
    """
    Faz o upload de um arquivo PDF para o Google Cloud Storage e retorna a URL pública.

    Args:
        uploaded_file: O arquivo carregado via st.file_uploader.
        numero_apolice (str): Número da apólice para nomear o arquivo.
        cliente (str): Nome do cliente para organizar na pasta.

    Returns:
        str: A URL pública do arquivo no GCS ou None se ocorrer um erro.
    """
    try:
        # Carrega as credenciais a partir dos "Secrets" do Streamlit
        # Isso é mais seguro do que deixar o arquivo JSON no repositório.
        creds_json_str = st.secrets["gcs_credentials"]
        creds_info = json.loads(creds_json_str)
        credentials = service_account.Credentials.from_service_account_info(creds_info)
        
        # Nome do seu bucket no Google Cloud Storage (deve ser criado previamente)
        bucket_name = st.secrets["gcs_bucket_name"]

        # Inicializa o cliente do GCS
        client = storage.Client(credentials=credentials)
        bucket = client.get_bucket(bucket_name)

        # Cria um nome de arquivo único e organizado
        safe_cliente = re.sub(r'[^a-zA-Z0-9\s-]', '', cliente).strip().replace(' ', '_')
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        destination_blob_name = f"apolices/{safe_cliente}/{numero_apolice}/{timestamp}_{uploaded_file.name}"

        # Faz o upload do arquivo
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_file(uploaded_file, content_type='application/pdf')

        # Retorna a URL pública do arquivo
        return blob.public_url

    except KeyError:
        st.error("Credenciais do Google Cloud Storage ou nome do bucket não configurados nos 'Secrets' do Streamlit.")
        st.info("Por favor, siga as instruções de configuração para adicionar 'gcs_credentials' e 'gcs_bucket_name' aos segredos do seu app.")
        return None
    except Exception as e:
        st.error(f"❌ Falha no upload para o Google Cloud Storage: {e}")
        return None


# --- FUNÇÕES RESTANTES DO SISTEMA (com a chamada para a nova função de salvar) ---

def add_apolice(data):
    """Adiciona uma nova apólice ao banco de dados."""
    # ... (validações iniciais permanecem as mesmas)
    if data['data_inicio_de_vigencia'] >= data['data_final_de_vigencia']:
        st.error("❌ A data final da vigência deve ser posterior à data inicial.")
        return False
    # ...

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
            
            # Adiciona ao histórico (código inalterado)
            return True
            
    except sqlite3.IntegrityError:
        st.error(f"❌ Erro: O número de apólice '{data['numero_apolice']}' já existe no sistema!")
        return False
    except Exception as e:
        st.error(f"❌ Ocorreu um erro inesperado ao cadastrar: {e}")
        return False

# A função render_cadastro_form agora chama a nova função de salvar
def render_cadastro_form():
    """Renderiza o formulário para cadastrar uma nova apólice."""
    st.title("➕ Cadastrar Nova Apólice")
    
    with st.form("form_cadastro", clear_on_submit=True):
        # ... (todos os campos do formulário permanecem os mesmos) ...
        seguradora = st.text_input("Seguradora*")
        cliente = st.text_input("Cliente*")
        numero_apolice = st.text_input("Número da Apólice*")
        # ... etc ...
        pdf_file = st.file_uploader("📎 Anexar PDF da Apólice (Opcional)", type=["pdf"])
        
        submitted = st.form_submit_button("💾 Salvar Apólice", use_container_width=True)
        if submitted:
            # ... (verificação de campos obrigatórios) ...
            
            # ATUALIZAÇÃO: Chama a nova função de upload para o GCS
            caminho_pdf = None
            if pdf_file:
                st.info("Fazendo upload do PDF para a nuvem... Isso pode levar alguns segundos.")
                caminho_pdf = salvar_pdf_gcs(pdf_file, numero_apolice, cliente)
            
            # Se o upload falhou, caminho_pdf será None e a apólice será salva sem o link.
            # O erro já terá sido exibido na tela pela função salvar_pdf_gcs.
            if pdf_file and not caminho_pdf:
                 st.error("Não foi possível salvar a apólice com o PDF devido a um erro no upload.")
                 return # Para a execução para não salvar uma apólice incompleta se o PDF for crucial

            apolice_data = {
                'seguradora': seguradora,
                'cliente': cliente,
                'numero_apolice': numero_apolice,
                # ... outros dados ...
                'caminho_pdf': caminho_pdf if caminho_pdf else "" # Garante que seja uma string vazia se não houver PDF
            }
            if add_apolice(apolice_data):
                st.success("🎉 Apólice cadastrada com sucesso!")
                if caminho_pdf:
                    st.success(f"PDF salvo na nuvem com sucesso! Link: {caminho_pdf}")
                st.balloons()

# O restante do seu código (main, get_apolices, etc.) permanece o mesmo.
# O sistema apenas precisa que o `caminho_pdf` seja uma URL válida para funcionar.
# A seguir, o código completo para referência.

def get_apolices(filtro_status=None):
    try:
        with get_connection() as conn:
            query = "SELECT * FROM apolices ORDER BY data_final_de_vigencia ASC"
            df = pd.read_sql_query(query, conn)
    except Exception as e: return pd.DataFrame()
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

# ... (todas as outras funções como `render_dashboard`, `render_consulta_apolices`, `main`, etc. devem ser incluídas aqui)
# Para economizar espaço, elas não foram repetidas, mas você deve mantê-las no seu arquivo final.

if __name__ == "__main__":
    # Esta parte é um exemplo de como a função principal seria chamada
    # Substitua pelo seu código main() completo.
    init_db() 
    st.title("Sistema Moreiraseg")
    # Exemplo de chamada
    render_cadastro_form()


