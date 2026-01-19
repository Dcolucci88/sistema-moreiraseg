import gspread
import json


def testar_conexao_real():
    try:
        # 1. Lê o e-mail do robô direto do seu arquivo de chaves
        with open('credentials.json') as f:
            dados_chave = json.load(f)
            email_robo = dados_chave.get('client_email')

        print(f"🤖 E-mail do seu Agente (robô): {email_robo}")

        # 2. Tenta conectar ao Google
        gc = gspread.service_account(filename='credentials.json')
        print("✅ Autenticação com o Google: OK!")

        # 3. Tenta abrir a planilha 'FECHAMENTO RCO'
        try:
            sh = gc.open("FECHAMENTO RCO")
            print(f"🏆 SUCESSO TOTAL! Conectado à planilha: {sh.title}")
            print(f"📋 Abas encontradas: {[w.title for w in sh.worksheets()]}")
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"\n⚠️  QUASE LÁ! O robô conectou, mas não achou a planilha 'FECHAMENTO RCO'.")
            print(
                f"👉 AÇÃO NECESSÁRIA: No Google Sheets, clique em 'Compartilhar' e adicione o e-mail {email_robo} como EDITOR.")

    except Exception as e:
        print(f"\n❌ Erro ao ler arquivo ou conectar: {e}")


if __name__ == "__main__":
    testar_conexao_real()