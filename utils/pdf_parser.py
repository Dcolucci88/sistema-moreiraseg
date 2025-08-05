import pypdf
import re
from io import BytesIO

def extrair_codigo_de_barras(arquivo_pdf_bytes: bytes, data_vencimento_alvo: str) -> str:
    """
    Abre um arquivo PDF a partir de seu conteúdo em bytes, encontra o texto 
    e extrai o código de barras do boleto com a data de vencimento correta.

    Args:
        arquivo_pdf_bytes: O conteúdo do arquivo PDF em bytes.
        data_vencimento_alvo: A data de vencimento no formato 'dd/mm/yyyy' para localizar o boleto certo.

    Returns:
        O código de barras (linha digitável) encontrado ou uma mensagem de erro.
    """
    try:
        # Usa BytesIO para ler o conteúdo do PDF que está em memória
        pdf_file = BytesIO(arquivo_pdf_bytes)
        
        reader = pypdf.PdfReader(pdf_file)
        texto_completo = ""
        for page in reader.pages:
            texto_completo += page.extract_text()

        # Regex para encontrar um código de barras no formato de linha digitável.
        # Este padrão é robusto, mas pode precisar de ajustes dependendo do layout do seu boleto.
        padrao_codigo_barras = r'\d{5}\.\d{5}\s\d{5}\.\d{6}\s\d{5}\.\d{6}\s\d\s\d{14}'

        # Lógica para encontrar o boleto correto na página.
        # Muitos PDFs de carnê têm múltiplos boletos. Usamos a data de vencimento para achar o certo.
        # Dividimos o texto em blocos usando "Vencimento" como separador.
        blocos = re.split(r'(Vencimento)', texto_completo, flags=re.IGNORECASE)
        
        for i, bloco in enumerate(blocos):
            # Se a data de vencimento alvo estiver neste bloco de texto...
            if data_vencimento_alvo in bloco:
                # ...procuramos o código de barras neste mesmo bloco.
                codigo_encontrado = re.search(padrao_codigo_barras, bloco)
                
                if codigo_encontrado:
                    print(f"Código de barras encontrado para o vencimento {data_vencimento_alvo}.")
                    return codigo_encontrado.group(0)

        print(f"Não foi possível localizar um código de barras para a data {data_vencimento_alvo}.")
        return "Código de barras não localizado para o vencimento especificado."

    except Exception as e:
        print(f"Erro ao processar o arquivo PDF: {e}")
        return "Erro ao ler o arquivo PDF."
