# api.py
from fastapi import FastAPI, HTTPException
import psycopg2
from psycopg2.extras import DictCursor
import os

# Carrega as credenciais a partir das variáveis de ambiente (ou de um ficheiro .env localmente)
# No futuro, iremos configurar isto no ambiente de hospedagem (ex: Google Cloud Run)
DB_HOST = os.getenv("DB_HOST", "34.95.160.234")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "Salmo@139")
DB_PORT = os.getenv("DB_PORT", "5432")

# Cria a aplicação FastAPI
app = FastAPI(title="Moreiraseg API")

def get_db_connection():
    """Cria e retorna uma conexão com o banco de dados PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        # Em um ambiente de produção, logaríamos este erro.
        print(f"Erro ao conectar ao banco de dados: {e}")
        raise HTTPException(status_code=500, detail="Não foi possível conectar ao banco de dados.")

@app.get("/")
def read_root():
    """Endpoint raiz para verificar se a API está online."""
    return {"status": "Moreiraseg API está online!"}

@app.get("/apolices/")
def get_todas_as_apolices():
    """
    Busca e retorna todas as apólices do banco de dados.
    """
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, numero_apolice, cliente, seguradora, status FROM apolices ORDER BY data_final_de_vigencia DESC;")
            apolices = cur.fetchall()
        conn.close()
        
        # Converte os resultados para uma lista de dicionários
        return [dict(row) for row in apolices]

    except Exception as e:
        print(f"Erro ao buscar apólices: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar dados das apólices.")
