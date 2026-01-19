import gspread
from datetime import datetime

def sincronizar_google_sheets(dados):
    """
    Sincroniza os dados da apólice com a planilha FECHAMENTO RCO.
    'dados' é o dicionário 'apolice_data' gerado no seu app.py.
    """
    try:
        # 1. Autenticação
        gc = gspread.service_account(filename='credentials.json')
        sh = gc.open("FECHAMENTO RCO")

        # 2. Mapeamento de Meses para garantir que o nome da aba bata exatamente (ex: JAN-2026)
        # Isso evita problemas com o ponto que o Python às vezes coloca (jan. vs JAN)
        meses_map = {
            1: "JAN", 2: "FEV", 3: "MAR", 4: "ABR", 5: "MAI", 6: "JUN",
            7: "JUL", 8: "AGO", 9: "SET", 10: "OUT", 11: "NOV", 12: "DEZ"
        }
        agora = datetime.now()
        nome_aba = f"{meses_map[agora.month]}-{agora.year}"  # Ex: JAN-2026

        try:
            worksheet = sh.worksheet(nome_aba)
        except gspread.exceptions.WorksheetNotFound:
            # Caso a aba do mês novo ainda não exista, ele avisa em vez de travar o sistema
            print(f"Erro: Aba {nome_aba} não encontrada na planilha.")
            return False

        # 3. Tratamento de Datas para o padrão da planilha (DD/MM/YYYY)
        # Seus dados no app.py estão em ISO (YYYY-MM-DD), precisamos converter
        def formatar_data(data_iso):
            if not data_iso: return ""
            return datetime.fromisoformat(data_iso).strftime("%d/%m/%Y")

        # 4. Montagem da Linha (Rigorosamente conforme image_236380.png)
        nova_linha = [
            dados.get('cliente', '').upper(),  # Coluna A: Segurado
            dados.get('numero_apolice', ''),  # Coluna B: numero da apolice
            dados.get('placa', '').upper(),  # Coluna C: Placa
            "1",  # Coluna D: Itens (app)
            formatar_data(dados.get('data_inicio_vigencia')),  # Coluna E: inicio Vigencia
            "AGENTE MOREIRA",  # Coluna F: VENDEDOR
            "NOVO",  # Coluna G: Tipo
            dados.get('tipo_seguro', 'RCO').upper(),  # Coluna H: Ramo
            dados.get('seguradora', '').upper(),  # Coluna I: SEGURADORA
            dados.get('quantidade_parcelas', ''),  # Coluna J: parcelas
            dados.get('tipo_cobranca', ''),  # Coluna K: Forma pgto
            formatar_data(dados.get('data_vencimento_1')),  # Coluna L: data 1º parcela
            dados.get('valor_parcela', 0),  # Coluna M: valor 1º parcela
            dados.get('valor_parcela', 0),  # Coluna N: valor demais parcelas
            f"{dados.get('comissao', 0)}%"  # Coluna O: % Com
        ]

        # 5. Envio dos dados
        worksheet.append_row(nova_linha, value_input_option='USER_ENTERED')
        return True

    except Exception as e:
        print(f"Erro crítico na sincronização: {e}")
        return False