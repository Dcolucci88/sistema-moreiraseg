# Salve como check_models.py
import os
from dotenv import load_dotenv
import google.generativeai as genai

# Carrega as variáveis do .env
load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    print("❌ ERRO: Chave GEMINI_API_KEY não encontrada no arquivo .env")
else:
    print(f"🔑 Chave carregada: {api_key[:5]}... (Oculta)")

    try:
        genai.configure(api_key=api_key)
        print("\n📡 Conectando ao Google para listar modelos disponíveis...")

        print("\n=== MODELOS DISPONÍVEIS PARA SUA CHAVE ===")
        found = False
        for m in genai.list_models():
            # Filtra apenas modelos que geram texto (chat)
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ {m.name}")
                found = True

        if not found:
            print("⚠️ Nenhum modelo de geração de conteúdo encontrado.")

    except Exception as e:
        print(f"\n❌ Erro ao conectar na API: {e}")