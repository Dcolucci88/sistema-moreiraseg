# api.py - Versão Robusta com Logging Melhorado
from fastapi import FastAPI, HTTPException
import psycopg2
from psycopg2.extras import DictCursor
import os
import logging

# Configuração do logging para vermos mensagens detalhadas no Cloud Run
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Moreiraseg API")

def get_db_connection():
    """Cria e retorna uma conexão com o banco de dados PostgreSQL."""
    try:
        # Lê as credenciais EXCLUSIVAMENTE das variáveis de ambiente configuradas no Cloud Run
        conn = psycopg2.connect(
            host=os.environ["DB_HOST"],
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASS"],
            port=os.environ.get("DB_PORT", 5432)
        )
        logger.info("Conexão com o banco de dados estabelecida com sucesso.")
        return conn
    except KeyError as e:
        logger.error(f"Variável de ambiente não encontrada: {e}")
        raise HTTPException(status_code=500, detail=f"Configuração do servidor incompleta: falta a variável {e}.")
    except Exception as e:
        logger.error(f"Erro ao conectar ao banco de dados: {e}")
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
    logger.info("Recebido pedido para /apolices/")
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Query atualizada para buscar todas as colunas que o Streamlit precisa
            cur.execute("""
                SELECT 
                    id, numero_apolice, cliente, seguradora, status, 
                    data_final_de_vigencia, placa, valor_da_parcela 
                FROM apolices 
                ORDER BY data_final_de_vigencia DESC;
            """)
            apolices = cur.fetchall()
            logger.info(f"Encontradas {len(apolices)} apólices no banco de dados.")
        conn.close()
        
        # Converte os resultados para uma lista de dicionários
        return [dict(row) for row in apolices]

    except Exception as e:
        # Este log irá mostrar o erro exato do banco de dados nos registos do Cloud Run
        logger.error(f"Erro ao executar a query de apólices: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno ao buscar dados das apólices.")
