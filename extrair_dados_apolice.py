import pypdf
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field


# Estrutura que garante que a IA não "invente" campos
class DadosApolice(BaseModel):
    seguradora: str = Field(description="Nome da seguradora (ex: KOVR, ESSOR)")
    numero: str = Field(
        description=(
            "Número da apólice. "
            "Na apólice KOVR é o valor do campo 'Apólice Número' (ex: 1002300081517). "
            "Não use o campo 'Ramo' ou 'Número da Proposta'."
        )
    )
    cliente: str = Field(description="Nome completo do segurado")
    placa: str = Field(description="Placa/Licença do veículo, se houver")
    vigencia: str = Field(
        description="Data de início da vigência (a primeira data do período 'Das 24:00 h do dia ...') em DD/MM/AAAA"
    )
    valor_parcela: float = Field(
        description="Valor de cada parcela (coluna 'Demais' no quadro de parcelamento)"
    )


def extrair_dados_apolice(arquivo_pdf):
    # 1. Leitura do PDF
    leitor = pypdf.PdfReader(arquivo_pdf)
    texto_completo = "".join([pagina.extract_text() for pagina in leitor.pages])

    # 2. Configuração com gpt-4o-mini
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    parser = JsonOutputParser(pydantic_object=DadosApolice)

    template = """
    Você é o Agente Moreira, assistente da MoreiraSeg.
    Leia cuidadosamente a apólice abaixo e preencha os campos do JSON seguindo estas regras:

    - "seguradora": nome da seguradora (ex: KOVR Seguradora S.A).
    - "numero": número da APÓLICE. Use o valor do campo "Apólice Número"
      (ex: 1002300081517). NÃO use os campos "Ramo", "Número da Proposta" ou "Endosso".
    - "cliente": nome do segurado.
    - "placa": valor do campo "Licença" do veículo (se existir, senão deixe vazio).
    - "vigencia": data de início da vigência (primeira data do período "Das 24:00 h do dia ... até ...").
    - "valor_parcela": valor em reais da coluna "Demais" do quadro de parcelamento.

    Retorne somente o JSON válido.

    TEXTO DA APÓLICE:
    {texto}
    {format_instructions}
    """

    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm | parser

    # Retorna o JSON validado para o Streamlit
    return chain.invoke({
        "texto": texto_completo,
        "format_instructions": parser.get_format_instructions()
    })