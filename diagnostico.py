import browser_use
import browser_use.browser
import pkgutil
import inspect

print("🔍 INICIANDO DIAGNÓSTICO DE IMPORTAÇÃO...")
print(f"Versão instalada: {getattr(browser_use, '__version__', 'Desconhecida')}")

print("\n--- 1. O que tem dentro de 'browser_use'? ---")
# Tenta ver se Browser está na raiz
print([x for x in dir(browser_use) if 'Browser' in x])

print("\n--- 2. O que tem dentro de 'browser_use.browser'? ---")
# Tenta ver se Browser está dentro do subpacote browser
print([x for x in dir(browser_use.browser) if 'Browser' in x])

print("\n--- 3. Arquivos reais na pasta 'browser_use/browser/' ---")
# Lista os arquivos físicos (.py) para sabermos o nome correto do módulo
if hasattr(browser_use.browser, '__path__'):
    for importer, modname, ispkg in pkgutil.iter_modules(browser_use.browser.__path__):
        print(f"  📄 Encontrado arquivo: {modname}.py")

print("\n----------------------------------------------")