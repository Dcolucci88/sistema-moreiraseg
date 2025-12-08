import os
from dotenv import load_dotenv
from supabase import create_client
import requests
import io
from pypdf import PdfReader

# 1. Configuração
load_dotenv()
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(URL, KEY)

# A apólice que deu erro no seu print
APOLICE_ALVO = "1002800146553"

print(f"--- INICIANDO DIAGNÓSTICO PARA: {APOLICE_ALVO} ---\n")

# 2. Buscar dados
print("1. Buscando dados no banco...")
res = supabase.table("apolices").select("id, caminho_pdf_boletos, cliente, seguradora").eq("numero_apolice",
                                                                                           APOLICE_ALVO).execute()

if not res.data:
    print("❌ ERRO: Apólice não encontrada no banco!")
    exit()

dados = res.data[0]
caminho = dados.get('caminho_pdf_boletos')
cliente = dados.get('cliente')

print(f"   ✅ Cliente: {cliente}")
print(f"   📂 Link no banco: '{caminho}'")

if not caminho:
    print("❌ CAUSA ENCONTRADA: O campo de PDF está VAZIO. Você precisa editar a apólice e anexar o boleto.")
    exit()

# 3. Baixar
print("\n2. Tentando baixar...")
try:
    if caminho.startswith("http"):
        response = requests.get(caminho)
        if response.status_code == 200:
            pdf_bytes = response.content
            print(f"   ✅ Download OK! Tamanho: {len(pdf_bytes)} bytes")
        else:
            print(f"   ❌ Erro de Download: Status {response.status_code}")
            exit()
    else:
        # Tenta storage interno
        pdf_bytes = supabase.storage.from_("moreiraseg-apolices-pdfs-2025").download(caminho)
        print(f"   ✅ Download interno OK!")
except Exception as e:
    print(f"   ❌ Erro fatal no download: {e}")
    exit()

# 4. Tentar Ler (O Teste Final)
print("\n3. Tentando ler o conteúdo do PDF...")
try:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    texto = ""
    for page in reader.pages:
        texto += page.extract_text() + "\n"

    print(f"   📖 Caracteres extraídos: {len(texto)}")

    if len(texto) < 50:
        print("   ⚠️ ALERTA: Pouquíssimo texto encontrado.")
        print("   ❌ CAUSA PROVÁVEL: O PDF é uma imagem escaneada. O robô não consegue ler imagens.")
    else:
        import re

        numeros = re.sub(r'\D', '', texto)
        match = re.search(r'\d{47}', numeros)
        if match:
            print(f"   ✅ SUCESSO: Código de barras encontrado: {match.group(0)}")
        else:
            print("   ❌ FALHA: Texto extraído, mas nenhum código de barras (47 dígitos) foi achado.")
            print("   -> Verifique se o boleto está legível.")

except Exception as e:
    print(f"   ❌ O arquivo não é um PDF válido ou está corrompido. Erro: {e}")

print("\n--- FIM ---")