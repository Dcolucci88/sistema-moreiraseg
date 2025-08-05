#!/bin/bash

# Inicia o agendador de tarefas em segundo plano
echo "Iniciando o Agendador de Tarefas (scheduler.py)..."
python scheduler.py &

# Inicia o dashboard do Streamlit em segundo plano
# Usamos a porta 8501, que é o padrão do Streamlit
echo "Iniciando o Dashboard Streamlit (app.py)..."
streamlit run app.py --server.port=8501 --server.address=0.0.0.0 &

# Inicia a API FastAPI como o processo principal (em primeiro plano)
# Isso mantém o contêiner rodando
echo "Iniciando a API FastAPI (api.py)..."
uvicorn api:app --host 0.0.0.0 --port 8080
