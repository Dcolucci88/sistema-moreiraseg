import io
import re
from pypdf import PdfReader


def extrair_codigo_de_barras(pdf_bytes: bytes, data_vencimento: str = None) -> str:
    """
    Lê um PDF em memória e tenta encontrar a linha digitável do boleto.
    """
    try:
        # Cria um objeto de leitura de PDF a partir dos bytes
        pdf_file = io.BytesIO(pdf_bytes)
        reader = PdfReader(pdf_file)

        texto_completo = ""

        # Extrai texto de todas as páginas
        for page in reader.pages:
            texto_completo += page.extract_text() + "\n"

        # Limpeza básica para facilitar a busca
        texto_limpo = texto_completo.replace('\n', ' ').replace('  ', ' ')

        # --- ESTRATÉGIA 1: REGEX ESPECÍFICO (Boleto Formatado) ---
        # Procura por blocos de números comuns em boletos com pontuação
        padrao_linha_digitavel = r'\d{5}\.?\d{5} ?\d{5}\.?\d{6} ?\d{5}\.?\d{6} ?\d ?\d{14}'
        match = re.search(padrao_linha_digitavel, texto_limpo)

        if match:
            return match.group(0)

        # --- ESTRATÉGIA 2: BUSCA BRUTA (Sequência de 47/48 dígitos) ---
        # Remove tudo que não é número (pontos, espaços, letras)
        numeros = re.sub(r'\D', '', texto_completo)

        # Boletos bancários geralmente têm 47 ou 48 dígitos
        # Se encontrarmos uma "tripa" de números desse tamanho, é quase certeza que é o boleto
        if len(numeros) >= 47:
            # Tenta achar uma sequência contínua de 47 dígitos
            match_bruto = re.search(r'\d{47}', numeros)
            if match_bruto:
                c = match_bruto.group(0)
                # Formata para ficar legível (AAAAA.BBBBB CCCCC.DDDDD ...)
                # Essa formatação ajuda o cliente a ler e o app do banco a aceitar
                return f"{c[:5]}.{c[5:10]} {c[10:15]}.{c[15:21]} {c[21:26]}.{c[26:32]} {c[32]} {c[33:]}"

        return None

    except Exception as e:
        print(f"Erro ao ler PDF: {e}")
        return None
