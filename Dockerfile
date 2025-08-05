# Usar uma imagem base oficial do Python
FROM python:3.11-slim

# Definir o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copiar o ficheiro de requisitos primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instalar as dependências
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código da aplicação
COPY . .

# Tornar o script start.sh executável
RUN chmod +x start.sh

# Expor as portas que os serviços usarão
EXPOSE 8080   # Porta da API FastAPI
EXPOSE 8501   # Porta do Dashboard Streamlit

# Comando para executar o script de inicialização quando o contêiner iniciar
CMD ["./start.sh"]
