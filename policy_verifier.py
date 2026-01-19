import asyncio
import os
from dotenv import load_dotenv

# Importações da IA (Não usadas na leitura direta, mas mantidas)
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

# Importação do Motor de Navegador
from playwright.async_api import async_playwright


class PolicyVerifier:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("⚠️ A chave OPENAI_API_KEY não foi encontrada.")

    async def executar_verificacao(self, login, senha, apolice_id):
        print("⚙️ Configurando...")

        print("🚀 Iniciando Navegador...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            # ==================================================================
            # FASE 1: LOGIN (MANTIDO)
            # ==================================================================
            print("🕵️ Fase 1: Login...")

            try:
                await page.goto("https://portal.kovr.com.br/Portal_Invest/Account/Index")

                # Usuário
                await page.focus("input[name='username']")
                await page.keyboard.type(login, delay=50)
                await page.evaluate("""
                    let field = document.querySelector("input[name='username']");
                    field.dispatchEvent(new Event('input', { bubbles: true }));
                    field.dispatchEvent(new Event('change', { bubbles: true }));
                """)

                # Senha
                await page.focus("input[name='password']")
                await page.keyboard.type(senha, delay=50)
                await page.evaluate("""
                    let field = document.querySelector("input[name='password']");
                    field.dispatchEvent(new Event('input', { bubbles: true }));
                    field.dispatchEvent(new Event('change', { bubbles: true }));
                    field.dispatchEvent(new Event('blur', { bubbles: true }));
                """)

                # Clicar Entrar
                botao = page.locator(".bnt-kovr").first
                if await botao.is_visible():
                    await botao.hover()
                    await botao.click(force=True)
                else:
                    await page.click("text=ENTRAR", force=True)

                print("⏳ Aguardando acesso...")
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(4)

                if "Account/Index" in page.url:
                    print("❌ Login falhou.")
                    await browser.close()
                    return "Login Falhou"

                print("✅ Login OK.")

            except Exception as e:
                print(f"❌ Erro Login: {e}")
                await browser.close()
                return "Erro no Login"

            # ==================================================================
            # FASE 2: NAVEGAÇÃO E BUSCA (MANTIDO)
            # ==================================================================
            try:
                print("🕵️ Fase 2: Navegando...")

                # 1. Clicar em "Impressão"
                await page.click("text=Impressão")
                await asyncio.sleep(0.5)

                # 2. Clicar em "Apólice"
                print("   > Clicando em 'Apólice'...")
                await page.get_by_role("link", name="Apólice", exact=True).click()

                print("⏳ Carregando busca...")
                await page.wait_for_load_state("networkidle")

                # 3. Preencher Apólice
                print(f"   > Buscando: {apolice_id}...")
                placeholder_apolice = "input[placeholder='Digite o numero da Apolice']"

                if await page.locator(placeholder_apolice).count() > 0:
                    await page.click(placeholder_apolice)
                    await page.fill(placeholder_apolice, apolice_id)
                else:
                    # Fallback
                    await page.keyboard.press("Tab")
                    await page.keyboard.press("Tab")
                    await page.keyboard.press("Tab")
                    await page.keyboard.press("Tab")
                    await page.keyboard.press("Tab")
                    await page.keyboard.press("Tab")
                    await page.keyboard.press("Tab")
                    await page.keyboard.type(apolice_id)

                # 4. PESQUISAR (3 TABS + ENTER)
                print("   > Acionando Pesquisar (Teclado)...")
                await page.keyboard.press("Tab")
                await asyncio.sleep(0.1)
                await page.keyboard.press("Tab")
                await asyncio.sleep(0.1)
                await page.keyboard.press("Tab")
                await asyncio.sleep(0.1)
                await page.keyboard.press("Enter")

                # Removemos pausas fixas longas, confiamos na Fase 3

            except Exception as e:
                print(f"❌ Erro Navegação: {e}")
                await page.screenshot(path="erro_navegacao.png")
                await browser.close()
                return "Erro Navegação"

            # ==================================================================
            # FASE 3: LEITURA ESTRUTURAL (CORRIGIDO)
            # ==================================================================
            print("🕵️ Fase 3: Extraindo Status (Modo Tabela)...")

            try:
                # 1. ESPERA A TABELA APARECER (Não o texto específico)
                # Esperamos qualquer linha de corpo de tabela (tbody tr)
                print("   > Aguardando carregamento da tabela (até 60s)...")
                await page.wait_for_selector("table tbody tr", timeout=120000)

                # 2. CAPTURA TODAS AS LINHAS
                # Isso nos permite varrer o que o site devolveu
                linhas = await page.locator("table tbody tr").all()
                print(f"   > Tabela carregada! Encontradas {len(linhas)} linhas.")

                status_final = "Não encontrado"

                # 3. PROCURA A APÓLICE
                for i, linha in enumerate(linhas):
                    texto_linha = await linha.inner_text()

                    # Verifica se o numero da apolice está nesta linha
                    if apolice_id in texto_linha:
                        print(f"   > Apólice localizada na linha {i + 1}!")

                        # Pega todas as colunas (células) dessa linha
                        colunas = linha.locator("td")
                        qtd_colunas = await colunas.count()

                        # A última coluna é o Status (baseado no seu print)
                        # Usamos -1 para pegar a última
                        celula_status = colunas.nth(qtd_colunas - 1)
                        status_final = await celula_status.inner_text()
                        status_final = status_final.strip()  # Limpa espaços
                        break

                if status_final == "Não encontrado":
                    print("   ⚠️ Apólice não encontrada na tabela visível.")
                    # Salva print para debug
                    await page.screenshot(path="debug_tabela_vazia.png")

                await browser.close()
                return status_final

            except Exception as e:
                print(f"❌ Erro na Leitura: {e}")
                await page.screenshot(path="erro_leitura.png")
                await browser.close()
                return "Erro Leitura"


if __name__ == "__main__":
    async def main():
        verifier = PolicyVerifier()
        # Atualizei com o ID do seu último print
        resultado = await verifier.executar_verificacao(
            login="222133607",
            senha="Grupscat!",
            apolice_id="1002300080797"
        )

        print("\n" + "=" * 40)
        print(f"📝 STATUS FINAL: {resultado}")
        print("=" * 40 + "\n")


    asyncio.run(main())