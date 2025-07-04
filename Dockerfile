# Usar uma imagem base oficial do Python
FROM python:3.11-slim

# Definir o diretório de trabalho dentro do contentor
WORKDIR /app

# Copiar o ficheiro de requisitos primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instalar as dependências
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código da aplicação
COPY . .

# Expor a porta que o Cloud Run irá usar
EXPOSE 8080

# Comando para executar a aplicação quando o contentor iniciar
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
