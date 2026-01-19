import pypdf
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field


# Estrutura que garante que a IA não "invente" campos
class DadosApolice(BaseModel):
    seguradora: str = Field(description="Nome da seguradora (ex: KOVR, ESSOR)")
    numero_apolice: str = Field(description="O número da apólice encontrado")
    cliente: str = Field(description="Nome completo do segurado")
    placa: str = Field(description="Placa do veículo se houver")
    vigencia_inicio: str = Field(description="Data de início da vigência DD/MM/AAAA")


def extrair_dados_apolice(arquivo_pdf):
    # 1. Leitura do PDF
    leitor = pypdf.PdfReader(arquivo_pdf)
    texto_completo = "".join([pagina.extract_text() for pagina in leitor.pages])

    # 2. Configuração com gpt-4o-mini
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    parser = JsonOutputParser(pydantic_object=DadosApolice)

    template = """
    Você é o Agente Moreira, assistente da MoreiraSeg. 
    Extraia com precisão os dados abaixo do texto da apólice:
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