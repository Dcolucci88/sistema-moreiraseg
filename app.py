import streamlit as st
from scheduler import executar_fluxo_de_cobranca

# DEVE SER O PRIMEIRO COMANDO STREAMLIT
st.set_page_config(
    page_title="MOREIRASEG - Corretora Inteligente",
    page_icon="assets/Icone.png",
    layout="wide"
)
import pandas as pd
import gspread
import datetime
from datetime import date, timedelta, timezone
import os
import re
import calendar
from dateutil.relativedelta import relativedelta
import ast
from supabase import create_client, Client
from utils.supabase_client import get_apolices
import threading # <-- NOVO IMPORT PARA O AGENDADOR
import time # <-- NOVO IMPORT PARA O AGENDADOR
# Tenta importar a lógica de extração (IA) com proteção contra erros
try:
    from extrair_dados_apolice import extrair_dados_apolice
except ImportError as e:
    st.error(f"⚠️ O módulo de IA não pôde ser carregado no servidor: {e}")
    def extrair_dados_apolice(arquivo):
        return {
            "seguradora": "",
            "numero": "",
            "cliente": "",
            "placa": "",
            "vigencia": date.today()
        }
# --- IMPORTAÇÕES EXTRAS (AGENDADOR E AGENTE) ---
import schedule  # Biblioteca para rodar o robô as 09:00

# Tenta importar a lógica do Agente (O CÉREBRO QUE CRIAMOS)
try:
    from agent_logic import executar_agente
except ImportError:
    # Cria uma função falsa apenas para o app não quebrar se o arquivo sumir
    def executar_agente(cmd): return f"Erro: agent_logic.py não encontrado."

# Tenta importar as funções do banco de dados
try:
    from utils.supabase_client import (
        supabase,
        get_apolices,
        buscar_todas_as_parcelas_pendentes,
        buscar_parcelas_vencendo_hoje,
        atualizar_status_pagamento
    )
except ImportError as e:
    st.error(f"Erro crítico de importação: {e}")
    st.stop()

# --- VERIFICAÇÃO DE CONEXÃO OBRIGATÓRIA ---
from utils.supabase_client import supabase

if supabase is None:
    st.error("ERRO CRÍTICO DE CONEXÃO: O cliente Supabase não pôde ser inicializado.")
    st.info("Verifique se suas 'Secrets' no Streamlit Cloud estão corretas (formato TOML) e reinicie o app.")
    st.stop()
# --- FIM DA VERIFICAÇÃO ---

# --- INICIALIZAÇÃO DO AGENDADOR EM THREAD SEPARADA ---
# A função de loop do agendador (do arquivo scheduler.py) será movida para cá.

def agendador_loop():
    """Função que roda o loop de verificação do agendamento (schedule)"""
    # Garante que a tarefa de cobrança seja configurada
    schedule.every().day.at("09:00").do(executar_fluxo_de_cobranca)
    print("Agendador de threads: Tarefa de cobrança configurada.")

    # Loop infinito para manter o agendador ativo
    while True:
        # Verifica se há tarefas pendentes e as executa
        schedule.run_pending()
        # Não precisa ser muito rápido, 60 segundos é suficiente
        time.sleep(60)

    # Verifica se o agendador já foi inicializado na sessão


if 'scheduler_thread' not in st.session_state:
    st.session_state['scheduler_thread_stop'] = False  # Variável de controle (opcional)

    # Cria e inicia a thread
    scheduler_thread = threading.Thread(target=agendador_loop, daemon=True)  # Daemon=True permite que o app encerre
    scheduler_thread.start()
    st.session_state['scheduler_thread'] = scheduler_thread
    print("Thread do Agendador de Cobrança iniciada com sucesso.")

# --- CONFIGURAÇÕES GLOBAIS ---
ASSETS_DIR = "assets"


# --- FIM DA ESTRUTURA PRINCIPAL ---
# ... (o restante do seu código Streamlit, como exibição de dados ou gráficos) ...

# --- CONFIGURAÇÕES GLOBAIS ---
ASSETS_DIR = "assets"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "Icone.png")


# --- FUNÇÕES DE LÓGICA DO SISTEMA (Refatoradas para usar o cliente 'supabase') ---

def salvar_ficheiros_supabase(ficheiro, numero_referencia, cliente, tipo_pasta):
    """Salva um único ficheiro no Supabase Storage."""
    try:
        # --- VERSÃO CORRIGIDA ---
        # Direciona cada tipo de arquivo para o seu respectivo bucket.
        if tipo_pasta in ['apolices', 'boletos']:
            bucket_name = "moreiraseg-apolices-pdfs-2025"
        elif tipo_pasta == 'sinistros':
            bucket_name = "sinistros"
        else:
            # Lógica segura para qualquer outro tipo de arquivo futuro
            bucket_name = os.environ.get(f"BUCKET_{tipo_pasta.upper()}", tipo_pasta)
        # --- FIM DA CORREÇÃO ---

        safe_cliente = re.sub(r'[^a-zA-Z0-9\s-]', '', cliente).strip().replace(' ', '_')
        file_bytes = ficheiro.getvalue()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # O caminho de destino agora usa o numero_referencia (pode ser apólice ou sinistro)
        destination_path = f"{safe_cliente}/{numero_referencia}/{timestamp}_{ficheiro.name}"

        supabase.storage.from_(bucket_name).upload(path=destination_path, file=file_bytes,
                                                   file_options={"content-type": ficheiro.type})
        public_url = supabase.storage.from_(bucket_name).get_public_url(destination_path)
        return public_url
    except Exception as e:
        st.error(f"❌ Falha no upload para o Supabase Storage: {e}")
        return None


def salvar_multiplos_ficheiros_supabase(ficheiros, numero_sinistro, cliente, tipo_pasta):
    """Salva múltiplos ficheiros no Supabase Storage e retorna uma lista de URLs."""
    urls = []
    if not ficheiros:
        return urls
    for ficheiro in ficheiros:
        url = salvar_ficheiros_supabase(ficheiro, numero_sinistro, cliente, tipo_pasta)
        if url:
            urls.append(url)
    return urls


def add_historico(apolice_id, usuario_email, acao, detalhes=""):
    """Adiciona um registro de ação na tabela 'historico'."""
    try:
        supabase.table('historico').insert({
            'apolice_id': apolice_id, 'usuario': usuario_email, 'acao': acao, 'detalhes': detalhes
        }).execute()
    except Exception as e:
        st.warning(f"⚠️ Não foi possível registrar a ação no histórico: {e}")


def add_historico_sinistro(sinistro_id, usuario_email, status_anterior, status_novo, observacao=""):
    """Adiciona um registro de ação na tabela 'historico_sinistros'."""
    try:
        supabase.table('historico_sinistros').insert({
            'sinistro_id': sinistro_id,
            'usuario': usuario_email,
            'status_anterior': status_anterior,
            'status_novo': status_novo,
            'observacao': observacao
        }).execute()
    except Exception as e:
        st.warning(f"⚠️ Não foi possível registrar a atualização do sinistro no histórico: {e}")


def get_parcelas_da_apolice(apolice_id):
    """Busca as parcelas de uma apólice específica e converte a data."""
    try:
        response = supabase.table('parcelas').select("*").eq('apolice_id', apolice_id).order('numero_parcela').execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data_vencimento'] = pd.to_datetime(df['data_vencimento']).dt.date
        return df
    except Exception as e:
        st.error(f"Erro ao carregar as parcelas: {e}")
        return pd.DataFrame()


def get_sinistros():
    """Busca todos os sinistros cadastrados."""
    try:
        response = supabase.table('sinistros').select("*").order('data_ultima_atualizacao', desc=True).execute()
        if response.data:
            return pd.DataFrame(response.data)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar os sinistros: {e}")
        return pd.DataFrame()


# SUBSTITUA SUA FUNÇÃO ANTIGA POR ESTA

def login_user(email, senha):
    """Tenta autenticar o usuário usando o Supabase Auth."""
    try:
        auth_response = supabase.auth.sign_in_with_password({
            "email": email.strip(),
            "password": senha.strip()
        })

        usuario = auth_response.user

        # --- ESTA É A CORREÇÃO ---
        # Agora estamos lendo o perfil 'admin' DIRETAMENTE dos metadados
        # que definimos no banco de dados (no Passo 1).
        perfil_do_usuario = usuario.user_metadata.get('perfil', 'user')
        nome_do_usuario = usuario.user_metadata.get('nome_completo', usuario.email.split('@')[0])
        # --- FIM DA CORREÇÃO ---

        return {
            'email': usuario.email,
            'nome': nome_do_usuario,
            'perfil': perfil_do_usuario  # Agora usamos o perfil correto
        }

    except Exception as e:
        st.error("E-mail ou senha inválidos. Verifique as credenciais.")
        return None


def update_apolice(apolice_id, update_data):
    """Salva as alterações de uma apólice e recria suas parcelas."""
    try:
        update_data['data_atualizacao'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        dados_apolice_update = {k: v for k, v in update_data.items() if
                                k not in ['vencimento_primeira_parcela', 'dia_vencimento_demais']}
        supabase.table('apolices').update(dados_apolice_update).eq('id', apolice_id).execute()
        supabase.table('parcelas').delete().eq('apolice_id', apolice_id).execute()

        quantidade_parcelas = update_data['quantidade_parcelas']
        valor_parcela = update_data['valor_parcela']
        vencimento_primeira_parcela = pd.to_datetime(update_data['vencimento_primeira_parcela']).date()
        dia_vencimento_demais = update_data['dia_vencimento_demais']
        lista_parcelas_para_db = []
        for i in range(quantidade_parcelas):
            if i == 0:
                vencimento_calculado = vencimento_primeira_parcela
            else:
                data_base_demais = vencimento_primeira_parcela + relativedelta(months=i)
                last_day = calendar.monthrange(data_base_demais.year, data_base_demais.month)[1]
                valid_day = min(dia_vencimento_demais, last_day)
                vencimento_calculado = date(data_base_demais.year, data_base_demais.month, valid_day)
            lista_parcelas_para_db.append({
                "apolice_id": apolice_id, "numero_parcela": i + 1,
                "data_vencimento": vencimento_calculado.isoformat(), "valor": valor_parcela, "status": "Pendente"
            })
        if lista_parcelas_para_db:
            supabase.table('parcelas').insert(lista_parcelas_para_db).execute()
        add_historico(apolice_id, st.session_state.get('user_email', 'sistema'), 'Atualização de Apólice',
                      f"Apólice atualizada e {quantidade_parcelas} parcelas recriadas.")
        return True
    except Exception as e:
        st.error(f"❌ Erro ao atualizar a apólice: {e}")
        return False

def sincronizar_google_sheets(dados):
    """Envia os dados reais da MoreiraSeg para a planilha FECHAMENTO RCO."""
    try:
        # Usa as credenciais que validamos com SUCESSO TOTAL
        gc = gspread.service_account(filename='credentials.json')
        sh = gc.open("FECHAMENTO RCO")

        # Identifica a aba pelo mês (ex: JAN-2026)
        nome_aba = datetime.datetime.now().strftime("%b-%Y").upper().replace('.', '')

        try:
            worksheet = sh.worksheet(nome_aba)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.get_worksheet(1)  # Fallback para a primeira aba de dados

        nova_linha = [
            dados.get('seguradora', ''),
            dados.get('numero_apolice', ''),
            dados.get('cliente', ''),
            dados.get('placa', ''),
            dados.get('tipo_seguro', ''),
            dados.get('data_inicio_vigencia', ''),
            dados.get('valor_parcela', 0),
            dados.get('comissao', 0)
        ]

        worksheet.append_row(nova_linha)
        return True
    except Exception as e:
        st.error(f"⚠️ Erro ao sincronizar com Google Sheets: {e}")
        return False

# --- RENDERIZAÇÃO DA INTERFACE ---

def render_dashboard():
    st.title("📊 Painel de Controle")
    tab_parcelas, tab_renovacoes = st.tabs(["📊 Controle de Parcelas", "🔥 Controle de Renovações"])

    with tab_parcelas:
        st.subheader("Visão Financeira (Parcelas)")
        try:
            todas_parcelas_pendentes = buscar_todas_as_parcelas_pendentes()
            response_total = supabase.table('apolices').select('id', count='exact').execute()
            total_apolices = response_total.count
        except Exception as e:
            st.error(f"Erro ao carregar dados do Supabase para o painel de parcelas: {e}")
            st.stop()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total de Apólices Ativas", total_apolices)

        if todas_parcelas_pendentes:
            parcelas_df = pd.DataFrame(todas_parcelas_pendentes)
            parcelas_df['data_vencimento'] = pd.to_datetime(parcelas_df['data_vencimento']).dt.date

            col2.metric("Parcelas Pendentes", len(parcelas_df))

            # ATUALIZAÇÃO: Verifica se o usuário é admin para mostrar o valor pendente
            if st.session_state.user_perfil == 'admin':
                valor_pendente = parcelas_df['valor'].sum()
                col3.metric("Valor Total Pendente", f"R${valor_pendente:,.2f}")

            today = date.today()
            start_of_week = today - timedelta(days=(today.weekday() + 1) % 7)
            end_of_week = start_of_week + timedelta(days=6)

            parcelas_da_semana_df = parcelas_df[
                (parcelas_df['data_vencimento'] >= start_of_week) &
                (parcelas_df['data_vencimento'] <= end_of_week)
                ]
            col4.metric("Parcelas na Semana", len(parcelas_da_semana_df),
                        f"{start_of_week.strftime('%d/%m')} a {end_of_week.strftime('%d/%m')}")

            st.divider()
            st.subheader("Detalhes das Parcelas a Vencer na Semana (Domingo a Sábado)")

            if not parcelas_da_semana_df.empty:
                cols_to_show = ['cliente', 'numero_apolice', 'numero_parcela', 'data_vencimento', 'valor']
                display_df = parcelas_da_semana_df.sort_values(by='data_vencimento').copy()
                display_df['data_vencimento'] = pd.to_datetime(display_df['data_vencimento']).dt.strftime('%d/%m/%Y')
                st.dataframe(display_df[cols_to_show], use_container_width=True)
            else:
                st.info("Nenhuma parcela pendente com vencimento nesta semana.")
        else:
            col2.metric("Parcelas Pendentes", 0)

            # ATUALIZAÇÃO: Verifica se o usuário é admin para mostrar o valor pendente
            if st.session_state.user_perfil == 'admin':
                col3.metric("Valor Total Pendente", "R$ 0,00")

            col4.metric("Parcelas na Semana", 0)
            st.info("Nenhuma parcela pendente encontrada no sistema.")

    with tab_renovacoes:
        apolices_df = get_apolices()
        st.subheader("Visão de Renovação de Apólices")
        if not apolices_df.empty:
            col1, col2, col3 = st.columns(3)
            col1.metric("Total de Apólices Ativas", len(apolices_df))
            a_renovar_df = apolices_df[apolices_df['dias_restantes'].between(0, 60)]
            col2.metric("Apólices a Renovar", len(a_renovar_df), "Próximos 60 dias")
            expiradas_df = apolices_df[apolices_df['dias_restantes'] < 0]
            col3.metric("Apólices Expiradas", len(expiradas_df))
            st.divider()
            st.subheader("Apólices por Prioridade de Renovação")
            prioridades_map = {
                '🔥 Urgente': apolices_df[apolices_df['prioridade'] == '🔥 Urgente'],
                '⚠️ Alta': apolices_df[apolices_df['prioridade'] == '⚠️ Alta'],
                '⚠️ Média': apolices_df[apolices_df['prioridade'] == '⚠️ Média'],
                '✅ Baixa': apolices_df[apolices_df['prioridade'] == '✅ Baixa'],
                '⚪ Expirada': expiradas_df
            }
            tabs_renovacao = st.tabs(list(prioridades_map.keys()))
            cols_to_show_renovacao = ['cliente', 'numero_apolice', 'tipo_seguro', 'data_final_de_vigencia',
                                      'dias_restantes']
            for tab, (prioridade, df) in zip(tabs_renovacao, prioridades_map.items()):
                with tab:
                    if not df.empty:
                        df_display = df.copy()
                        df_display['data_final_de_vigencia'] = pd.to_datetime(
                            df_display['data_final_de_vigencia']).dt.strftime('%d/%m/%Y')
                        st.dataframe(df_display[cols_to_show_renovacao], use_container_width=True)
                    else:
                        st.info(f"Nenhuma apólice com prioridade '{prioridade.split(' ')[-1]}'.")
        else:
            st.info("Nenhuma apólice cadastrada para analisar as renovações.")


def render_cadastro_form():
    st.title("➕ Cadastrar Nova Apólice")

    # 1. INICIALIZAÇÃO DO ESTADO (Para o Agente Moreira e Lógica de Frota)
    if 'dados_extraidos' not in st.session_state:
        st.session_state.dados_extraidos = {
            "seguradora": "", "numero": "", "cliente": "",
            "placa": "", "vigencia": date.today()
        }
    if 'is_frota' not in st.session_state: st.session_state.is_frota = False

    # 2. AGENTE MOREIRA (Upload fora do formulário para disparar a extração imediata)
    with st.expander("🤖 Agente Moreira - Preenchimento Automático", expanded=True):
        arquivo_ia = st.file_uploader("📂 Suba a Apólice (PDF) para análise", type=["pdf"], key="ia_uploader")

        if arquivo_ia and st.button("Executar Agente Moreira"):
            with st.spinner("Agente Moreira lendo apólice..."):
                # Chama a função que está no seu outro arquivo
                resultado = extrair_dados_apolice(arquivo_ia)

                # Atualiza o formulário com os dados reais extraídos pela IA
                st.session_state.dados_extraidos.update(resultado)
                st.success("O Agente Moreira concluiu a análise! Verifique os campos abaixo.")

    # 3. FORMULÁRIO DE CADASTRO ÚNICO
    with st.form("form_cadastro", clear_on_submit=False):
        st.subheader("Dados da Apólice")
        st.session_state.is_frota = st.toggle("É uma apólice de Frota?", key="toggle_frota",
                                              value=st.session_state.is_frota)

        col1, col2 = st.columns(2)
        with col1:
            seguradora = st.text_input("Seguradora*", value=st.session_state.dados_extraidos['seguradora'],
                                       max_chars=50)
            numero_apolice = st.text_input("Número da Apólice*", value=st.session_state.dados_extraidos['numero'],
                                           max_chars=50)
            tipo_seguro = st.selectbox("Tipo de Seguro*", ["Automóvel", "RCO", "Vida", "Residencial", "Outro"])
            opcoes_cobranca = ["Boleto", "Boleto a Vista", "Faturamento", "Cartão de Crédito", "Débito em Conta"]
            tipo_cobranca_selecionado = st.selectbox("Tipo de Cobrança*", options=opcoes_cobranca)

        with col2:
            cliente = st.text_input("Cliente*", value=st.session_state.dados_extraidos['cliente'], max_chars=100)
            if st.session_state.is_frota:
                placas_input = st.text_area("Placas da Frota (uma por linha)*", height=105)
                placa_unica_input = ""
            else:
                placa_unica_input = st.text_input("🚗 Placa do Veículo (Opcional)",
                                                  value=st.session_state.dados_extraidos['placa'], max_chars=10)
                placas_input = ""

        st.subheader("Vigência e Parcelamento")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            data_inicio = st.date_input("📅 Início de Vigência*",
                                        value=st.session_state.dados_extraidos.get('vigencia', date.today()),
                                        format="DD/MM/YYYY")
        with c2:
            vencimento_primeira_parcela = st.date_input("📅 Vencimento da 1ª Parcela*", format="DD/MM/YYYY")
        with c3:
            dia_vencimento_demais = st.number_input("Dia Venc. Demais Parcelas*", min_value=1, max_value=31, value=23)
        with c4:
            # Lógica de travas baseada no tipo de frota ou cobrança
            default_parcelas = 12 if st.session_state.is_frota else 10
            quantidade_parcelas = st.number_input("Quantidade de Parcelas*", min_value=1, max_value=24,
                                                  value=default_parcelas)

        st.subheader("Valores e Comissão")
        v1, v2 = st.columns(2)
        with v1:
            valor_inicial = (
                f"{st.session_state.dados_extraidos.get('valor_parcela', 0):.2f}".replace('.', ',')
                if 'valor_parcela' in st.session_state.dados_extraidos
                else "0,00"
            )
            valor_parcela_str = st.text_input("💰 Valor de Cada Parcela (R$)*", value=valor_inicial)
        with v2:
            comissao = st.number_input("💼 Comissão (%)*", min_value=0.0, max_value=100.0, value=10.0, step=0.5,
                                       format="%.2f")

        st.subheader("Dados de Contato e Anexos")
        contato = st.text_input("📱 Contato do Cliente*", max_chars=100)
        email = st.text_input("📧 E-mail do Cliente", max_chars=100)
        observacoes = st.text_area("📝 Observações", height=100)

        pdf_apolice_file = st.file_uploader("📎 Anexar PDF da Apólice (Opcional)", type=["pdf"])
        pdf_boletos_file = st.file_uploader("📎 Anexar Carnê de Boletos (PDF único, opcional)", type=["pdf"])

        # BOTÃO ÚNICO DE SUBMISSÃO
        submitted = st.form_submit_button("💾 Salvar Apólice e Sincronizar Sistema", use_container_width=True)

        if submitted:
            # Validações Iniciais
            valor_parcela = float(valor_parcela_str.replace(',', '.')) if valor_parcela_str else 0.0
            placa_final = ", ".join([p.strip() for p in placas_input.split('\n') if
                                     p.strip()]) if st.session_state.is_frota else placa_unica_input

            if not all([seguradora, cliente, numero_apolice, contato, valor_parcela > 0]):
                st.error(
                    "Por favor, preencha todos os campos obrigatórios (*) e garanta que o valor seja maior que zero.")
            else:
                try:
                    # 1. SALVAMENTO SUPABASE (Storage e Banco)
                    caminho_pdf_apolice_url = salvar_ficheiros_supabase(pdf_apolice_file, numero_apolice, cliente,
                                                                        'apolices') if pdf_apolice_file else None
                    caminho_pdf_boletos_url = salvar_ficheiros_supabase(pdf_boletos_file, numero_apolice, cliente,
                                                                        'boletos') if pdf_boletos_file else None

                    apolice_data = {
                        'seguradora': seguradora, 'cliente': cliente, 'numero_apolice': numero_apolice,
                        'placa': placa_final, 'tipo_seguro': tipo_seguro, 'tipo_cobranca': tipo_cobranca_selecionado,
                        'valor_parcela': valor_parcela, 'comissao': comissao,
                        'data_inicio_vigencia': data_inicio.isoformat(), 'quantidade_parcelas': quantidade_parcelas,
                        'dia_vencimento': dia_vencimento_demais, 'contato': contato, 'email': email,
                        'observacoes': observacoes, 'status': 'Ativa',
                        'caminho_pdf_apolice': caminho_pdf_apolice_url, 'caminho_pdf_boletos': caminho_pdf_boletos_url
                    }

                    # Inserção da Apólice e Parcelas (Lógica original mantida)
                    res = supabase.table('apolices').insert(apolice_data).execute()
                    apolice_id = res.data[0]['id']

                    # 2. SINCRONIZAÇÃO GOOGLE SHEETS
                    # Esta função deve ser criada para mapear as colunas da imagem_236380
                    sincronizar_google_sheets(apolice_data)

                    st.success(f"🎉 Apólice '{numero_apolice}' salva e sincronizada com sucesso!")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")


def render_pesquisa_e_edicao():
    st.title("🔍 Pesquisar e Editar Apólice")
    search_term = st.text_input("Pesquisar por Nº Apólice, Cliente ou Placa:", key="search_box")
    if search_term:
        resultados = get_apolices(search_term=search_term)
        if resultados.empty:
            st.info("Nenhuma apólice encontrada com o termo pesquisado.")
        else:
            st.success(f"{len(resultados)} apólice(s) encontrada(s).")
            for index, apolice_row in resultados.iterrows():
                apolice_id = apolice_row['id']
                with st.expander(f"**{apolice_row['numero_apolice']}** - {apolice_row['cliente']}"):
                    st.subheader("Situação das Parcelas")
                    parcelas_df = get_parcelas_da_apolice(apolice_id)
                    if not parcelas_df.empty:
                        df_display = parcelas_df.copy()
                        df_display['data_vencimento'] = pd.to_datetime(df_display['data_vencimento']).dt.strftime(
                            '%d/%m/%Y')
                        df_display['valor'] = df_display['valor'].apply(lambda x: f"R$ {x:,.2f}")
                        st.dataframe(df_display[['numero_parcela', 'data_vencimento', 'valor', 'status']],
                                     use_container_width=True)
                    else:
                        st.warning(
                            "Nenhuma parcela encontrada para esta apólice. Preencha e salve o formulário abaixo para gerá-las.")
                    st.divider()
                    st.subheader("📝 Editar Informações e Gerar Parcelas")
                    with st.form(f"edit_form_{apolice_id}", clear_on_submit=False):
                        is_frota_atual = "Faturamento" == apolice_row.get('tipo_cobranca')
                        edit_is_frota = st.toggle("É uma apólice de Frota?", value=is_frota_atual,
                                                  key=f"frota_{apolice_id}")
                        col1, col2 = st.columns(2)
                        with col1:
                            seguradora = st.text_input("Seguradora*", value=apolice_row['seguradora'],
                                                       key=f"seg_{apolice_id}")
                            numero_apolice = st.text_input("Número da Apólice*", value=apolice_row['numero_apolice'],
                                                           key=f"num_{apolice_id}")
                            tipo_seguro = st.selectbox("Tipo de Seguro*",
                                                       ["Automóvel", "RCO", "Vida", "Residencial", "Empresarial",
                                                        "Saúde", "Viagem", "Fiança", "Outro"],
                                                       index=["Automóvel", "RCO", "Vida", "Residencial", "Empresarial",
                                                              "Saúde", "Viagem", "Fiança", "Outro"].index(
                                                           apolice_row['tipo_seguro']), key=f"tipo_{apolice_id}")
                        with col2:
                            cliente = st.text_input("Cliente*", value=apolice_row['cliente'], key=f"cli_{apolice_id}")
                            if edit_is_frota:
                                placas_input = st.text_area("Placas da Frota (uma por linha)*",
                                                            value=apolice_row.get('placa', '').replace(', ', '\n'),
                                                            height=105, key=f"placas_{apolice_id}")
                                placa_unica_input = ""
                            else:
                                placa_unica_input = st.text_input("🚗 Placa do Veículo (Opcional)",
                                                                  value=apolice_row.get('placa', ''), max_chars=10,
                                                                  key=f"placa_unica_{apolice_id}")
                                placas_input = ""
                            opcoes_cobranca = ["Boleto", "Boleto a Vista", "Faturamento", "Cartão de Crédito",
                                               "Débito em Conta"]
                            tipo_cobranca_atual = apolice_row.get('tipo_cobranca', 'Boleto')
                            if edit_is_frota:
                                tipo_cobranca_selecionado = "Faturamento"
                                qtd_parcelas_valor = 12
                                campos_travados = True
                            elif st.session_state.get(f'cobranca_{apolice_id}') == "Boleto a Vista":
                                tipo_cobranca_selecionado = "Boleto a Vista"
                                qtd_parcelas_valor = 1
                                campos_travados = True
                            else:
                                tipo_cobranca_selecionado = tipo_cobranca_atual
                                qtd_parcelas_valor = int(apolice_row.get('quantidade_parcelas', 10))
                                campos_travados = False
                            tipo_cobranca = st.selectbox("Tipo de Cobrança*", options=opcoes_cobranca,
                                                         index=opcoes_cobranca.index(tipo_cobranca_selecionado),
                                                         key=f"cobranca_{apolice_id}", disabled=edit_is_frota)
                        st.subheader("Vigência e Parcelamento")
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            data_inicio = st.date_input("📅 Início de Vigência*", value=pd.to_datetime(
                                apolice_row['data_inicio_vigencia']).date(), format="DD/MM/YYYY",
                                                        key=f"inicio_{apolice_id}")
                        with col2:
                            primeira_parcela_existente = parcelas_df['data_vencimento'].iloc[
                                0] if not parcelas_df.empty else datetime.date.today()
                            vencimento_primeira_parcela = st.date_input("📅 Vencimento da 1ª Parcela*",
                                                                        value=pd.to_datetime(
                                                                            primeira_parcela_existente),
                                                                        format="DD/MM/YYYY", key=f"venc1_{apolice_id}")
                        with col3:
                            dia_vencimento_demais = st.number_input("Dia Venc. Demais Parcelas*", min_value=1,
                                                                    max_value=31,
                                                                    value=int(apolice_row.get('dia_vencimento', 10)),
                                                                    key=f"dia_demais_{apolice_id}")
                        with col4:
                            quantidade_parcelas = st.number_input("Quantidade de Parcelas*", min_value=1, max_value=24,
                                                                  value=qtd_parcelas_valor, disabled=campos_travados,
                                                                  key=f"qtd_parc_{apolice_id}")
                        st.subheader("Valores e Comissão")
                        col1, col2 = st.columns(2)
                        with col1:
                            valor_parcela_str = st.text_input("💰 Valor de Cada Parcela (R$)*",
                                                              value=f"{apolice_row.get('valor_parcela', 0.0):.2f}".replace(
                                                                  '.', ','), key=f"valor_{apolice_id}")
                        with col2:
                            comissao = st.number_input("💼 Comissão (%)", min_value=0.0,
                                                       value=float(apolice_row.get('comissao', 10.0)),
                                                       key=f"comissao_{apolice_id}")
                        st.subheader("Dados de Contato e Anexos")
                        contato = st.text_input("📱 Contato do Cliente*", value=apolice_row.get('contato', ''),
                                                key=f"contato_{apolice_id}")
                        email = st.text_input("📧 E-mail do Cliente", value=apolice_row.get('email', ''),
                                              key=f"email_{apolice_id}")
                        observacoes = st.text_area("📝 Observações", value=apolice_row.get('observacoes', ''),
                                                   key=f"obs_{apolice_id}")
                        pdf_apolice_file = st.file_uploader("Substituir PDF da Apólice (Opcional)", type=["pdf"],
                                                            key=f"pdf_apolice_{apolice_id}")
                        pdf_boletos_file = st.file_uploader("Substituir Carnê de Boletos (Opcional)", type=["pdf"],
                                                            key=f"pdf_boletos_{apolice_id}")
                        submitted = st.form_submit_button("💾 Salvar Alterações", use_container_width=True)
                        if submitted:
                            if edit_is_frota:
                                placa_final = ", ".join([p.strip() for p in placas_input.split('\n') if p.strip()])
                            else:
                                placa_final = placa_unica_input
                            update_data = {
                                'seguradora': seguradora, 'cliente': cliente, 'numero_apolice': numero_apolice,
                                'placa': placa_final, 'tipo_seguro': tipo_seguro, 'tipo_cobranca': tipo_cobranca,
                                'valor_parcela': float(valor_parcela_str.replace(',', '.')),
                                'comissao': float(comissao),
                                # --- CORREÇÃO 2 INICIADA ---
                                # Converte o objeto 'date' para string para evitar erro de serialização JSON.
                                'data_inicio_vigencia': data_inicio.isoformat(),
                                # --- CORREÇÃO 2 FINALIZADA ---
                                'quantidade_parcelas': quantidade_parcelas,
                                'dia_vencimento': dia_vencimento_demais,
                                'contato': contato, 'email': email, 'observacoes': observacoes,
                                'vencimento_primeira_parcela': vencimento_primeira_parcela,
                                'dia_vencimento_demais': dia_vencimento_demais
                            }
                            if pdf_apolice_file:
                                st.info("Fazendo upload da nova apólice...")
                                update_data['caminho_pdf_apolice'] = salvar_ficheiros_supabase(pdf_apolice_file,
                                                                                               numero_apolice, cliente,
                                                                                               'apolices')
                            if pdf_boletos_file:
                                st.info("Fazendo upload do novo carnê...")
                                update_data['caminho_pdf_boletos'] = salvar_ficheiros_supabase(pdf_boletos_file,
                                                                                               numero_apolice, cliente,
                                                                                               'boletos')
                            if update_apolice(apolice_id, update_data):
                                st.success("Apólice atualizada com sucesso!")
                                st.rerun()


# --- NOVO: FUNÇÕES PARA RENDERIZAR A PÁGINA DE SINISTROS (COM ATUALIZAÇÕES) ---
def render_sinistros():
    """Função principal que renderiza a página de gestão de sinistros."""
    st.title("🚨 Gestão de Sinistros")

    tab_acompanhamento, tab_cadastro = st.tabs(["Acompanhamento de Sinistros", "➕ Cadastrar Novo Sinistro"])

    with tab_acompanhamento:
        render_acompanhamento_sinistros()

    with tab_cadastro:
        render_cadastro_sinistro_form()


def render_acompanhamento_sinistros():
    """Renderiza a lista de sinistros, alertas e formulários de atualização."""
    st.subheader("Acompanhamento e Alertas")

    try:
        sinistros_df = get_sinistros()
    except Exception as e:
        if 'does not exist' in str(e):
            try:
                response = supabase.table('sinistros').select("*").execute()
                sinistros_df = pd.DataFrame(response.data) if response.data else pd.DataFrame()
                st.warning(
                    "A coluna 'data_ultima_atualizacao' não foi encontrada na tabela 'sinistros'. Os resultados não serão ordenados por data de atualização.")
            except Exception as inner_e:
                st.error(f"Erro ao carregar os sinistros (tentativa 2): {inner_e}")
                return
        else:
            st.error(f"Erro ao carregar os sinistros: {e}")
            return

    if sinistros_df.empty:
        st.info("Nenhum sinistro cadastrado ainda.")
        return

    # --- Lógica de Alertas ---
    alertas_status = []
    alertas_vistoria = []
    agora = datetime.datetime.now(timezone.utc)

    # ATUALIZAÇÃO: Adicionada verificação para a coluna 'status'
    if 'data_ultima_atualizacao' in sinistros_df.columns and 'status' in sinistros_df.columns:
        for index, row in sinistros_df.iterrows():
            # ATUALIZAÇÃO: Adicionado .get() para segurança
            if row.get('data_ultima_atualizacao') and row.get('status'):
                # NOVA VERIFICAÇÃO: Ignorar linhas sem dados essenciais
                if not row.get('numero_sinistro') or not row.get('segurado'):
                    continue

                data_ultima_att = pd.to_datetime(row['data_ultima_atualizacao']).replace(tzinfo=timezone.utc)
                if (agora - data_ultima_att) > timedelta(hours=24):
                    if row['status'] not in ['Finalizado', 'Negado']:
                        alertas_status.append(row)

            if pd.isna(row.get('data_vistoria')) or not row.get('data_vistoria'):
                if row.get('data_abertura'):
                    data_abertura = pd.to_datetime(row['data_abertura']).replace(tzinfo=timezone.utc)
                    if (agora - data_abertura) > timedelta(hours=24):
                        alertas_vistoria.append(row)

    # --- Exibição dos Alertas ---
    if alertas_status or alertas_vistoria:
        with st.container(border=True):
            st.error("‼️ ATENÇÃO: HÁ PENDÊNCIAS IMPORTANTES!")
            if alertas_status:
                st.write("**Sinistros com Status Desatualizado (há mais de 24h):**")
                for s in alertas_status:
                    st.warning(
                        f"**Sinistro Segurado nº {s.get('numero_sinistro', 'N/A')}** (Segurado: {s.get('segurado', 'N/A')}) - Status: **{s.get('status', 'N/A')}**. Requer atualização.")

            if alertas_vistoria:
                st.write("**Sinistros aguardando agendamento de vistoria (há mais de 24h):**")
                for s in alertas_vistoria:
                    st.warning(
                        f"**Sinistro Segurado nº {s.get('numero_sinistro', 'N/A')}** (Segurado: {s.get('segurado', 'N/A')}) - Cobrar agendamento da vistoria da seguradora.")
    else:
        st.success("✅ Nenhum alerta de acompanhamento no momento.")

    st.divider()

    # --- Lista de Todos os Sinistros ---
    st.subheader("Todos os Sinistros Cadastrados")
    status_options = ["Comunicado", "Agendado", "Vistoriado", "Aguardando Autorização", "Autorizado", "Negado",
                      "Finalizado", "Acordo", "Pendente"]

    for index, row in sinistros_df.iterrows():
        # ATUALIZAÇÃO: Adicionada verificação de segurança para a coluna 'id'
        sinistro_id = row.get('id')
        if not sinistro_id:
            continue

        # ATUALIZAÇÃO: Uso de .get() para acesso seguro aos dados
        status_display = row.get('status', 'Status Indefinido')
        with st.expander(
                f"**Sinistro Segurado nº {row.get('numero_sinistro', 'N/A')}** | Segurado: **{row.get('segurado', 'N/A')}** | Status: **{status_display}**"):

            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown(f"**Seguradora:** {row.get('seguradora', 'N/A')}")
                st.markdown(f"**Apólice:** {row.get('numero_apolice', 'N/A')}")
                st.markdown(f"**Placa:** {row.get('placa_segurado', 'N/A')}")
                st.markdown(f"**Tipo Ramo:** {row.get('tipo_ramo', row.get('tipo_sinistro', 'N/A'))}")
            with col2:
                st.markdown(f"**Sinistro Terceiro:** {row.get('numero_sinistro_terceiro', 'N/A')}")
                data_abertura_str = pd.to_datetime(row.get('data_abertura')).strftime('%d/%m/%Y') if pd.notna(
                    row.get('data_abertura')) else "N/A"
                st.markdown(f"**Abertura:** {data_abertura_str}")
                data_vistoria_str = pd.to_datetime(row.get('data_vistoria')).strftime('%d/%m/%Y') if pd.notna(
                    row.get('data_vistoria')) else "Não agendada"
                st.markdown(f"**Vistoria:** {data_vistoria_str}")
                st.markdown(f"**Terceiro:** {row.get('nome_terceiro', 'N/A')}")
            with col3:
                st.markdown(f"**Contato Terceiro:** {row.get('contato_terceiro', 'N/A')}")
                if row.get('caminho_bo'): st.link_button("Ver B.O.", row['caminho_bo'])
                if row.get('caminho_cnh_motorista'): st.link_button("Ver CNH Motorista", row['caminho_cnh_motorista'])
                if row.get('caminho_cnh_terceiro'): st.link_button("Ver CNH Terceiro", row['caminho_cnh_terceiro'])
                if row.get('caminho_crlv_segurado'): st.link_button("Ver CRLV Segurado", row['caminho_crlv_segurado'])
                if row.get('caminho_crlv_terceiro'): st.link_button("Ver CRLV Terceiro", row['caminho_crlv_terceiro'])

            if row.get('caminhos_imagens_batida'):
                st.write("**Imagens da Batida:**")
                image_urls = row.get('caminhos_imagens_batida')
                if isinstance(image_urls, str):
                    try:
                        image_urls = ast.literal_eval(image_urls)
                    except:
                        image_urls = []

                if image_urls:
                    st.image(image_urls, width=150)

            st.divider()

            with st.form(key=f"update_form_{sinistro_id}"):
                st.subheader("Atualizar Acompanhamento")

                col1_form, col2_form, col3_form = st.columns(3)

                with col1_form:
                    novo_numero_sinistro_terceiro = st.text_input(
                        "Nº Sinistro Terceiro",
                        value=row.get('numero_sinistro_terceiro', ''),
                        key=f"sin_terceiro_{sinistro_id}"
                    )

                with col2_form:
                    contatou_terceiro_options = ["Não", "Sim"]
                    current_contatou_index = 1 if row.get('contatou_terceiro') else 0
                    novo_contatou_terceiro = st.selectbox(
                        "Contatou Terceiro?",
                        options=contatou_terceiro_options,
                        index=current_contatou_index,
                        key=f"contatou_{sinistro_id}"
                    )

                with col3_form:
                    current_status = row.get('status')
                    current_status_index = status_options.index(
                        current_status) if current_status in status_options else 0
                    novo_status = st.selectbox(
                        "Alterar Status para:",
                        options=status_options,
                        index=current_status_index,
                        key=f"status_update_{sinistro_id}"
                    )

                nova_data_vistoria_valor = None
                if novo_status == 'Agendado':
                    data_vistoria_atual = pd.to_datetime(row.get('data_vistoria')).date() if pd.notna(
                        row.get('data_vistoria')) else None
                    nova_data_vistoria_valor = st.date_input(
                        "Data Vistoria",
                        value=data_vistoria_atual,
                        format="DD/MM/YYYY",
                        key=f"data_vistoria_{sinistro_id}"
                    )

                observacao = st.text_area("Adicionar Observação/Histórico:", key=f"obs_{sinistro_id}")

                submitted = st.form_submit_button("💾 Salvar Atualização", use_container_width=True)
                if submitted:
                    update_payload = {
                        'data_ultima_atualizacao': datetime.datetime.now(timezone.utc).isoformat(),
                        'numero_sinistro_terceiro': novo_numero_sinistro_terceiro,
                        'contatou_terceiro': True if novo_contatou_terceiro == "Sim" else False,
                    }

                    if novo_status == 'Agendado':
                        update_payload[
                            'data_vistoria'] = nova_data_vistoria_valor.isoformat() if nova_data_vistoria_valor else None

                    if novo_status != row.get('status'):
                        update_payload['status'] = novo_status
                        add_historico_sinistro(sinistro_id, st.session_state.user_email, row.get('status', 'N/A'),
                                               novo_status, observacao)

                    try:
                        supabase.table('sinistros').update(update_payload).eq('id', sinistro_id).execute()
                        st.success(f"Sinistro nº {row.get('numero_sinistro', 'N/A')} atualizado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao atualizar o sinistro: {e}")


def render_cadastro_sinistro_form():
    """Renderiza o formulário para cadastrar um novo sinistro."""
    st.subheader("Formulário de Cadastro de Sinistro")

    status_options = ["Comunicado", "Agendado", "Vistoriado", "Aguardando Autorização", "Autorizado", "Negado",
                      "Finalizado", "Pendente"]
    ramos_options = ["Automóvel", "RCO", "Vida", "Residencial", "Empresarial", "Saúde", "Viagem", "Fiança", "Outro"]

    with st.form("form_cadastro_sinistro", clear_on_submit=True):
        st.subheader("Dados do Sinistro")
        col1, col2 = st.columns(2)
        with col1:
            segurado = st.text_input("Segurado*", max_chars=100)
            seguradora = st.text_input("Seguradora*", max_chars=50)
            numero_sinistro_segurado = st.text_input("Nº de Sinistro Segurado*", max_chars=50)
            numero_sinistro_terceiro = st.text_input("Nº de Sinistro Terceiro (se houver)", max_chars=50)
            tipo_ramo = st.selectbox("Tipo Ramo*", options=ramos_options)
            numero_apolice = st.text_input("Nº de Apólice*", max_chars=50)
        with col2:
            placa_segurado = st.text_input("Placa Segurado*", max_chars=10)
            nome_terceiro = st.text_input("Nome do Terceiro (se houver)", max_chars=100)
            contato_terceiro = st.text_input("Contato Terceiro (se houver)", max_chars=50)
            contatou_terceiro = st.selectbox("Já contatou o Terceiro?", ["Não", "Sim"])
            data_abertura = st.date_input("Data de Abertura do Sinistro*", format="DD/MM/YYYY")
            data_vistoria = st.date_input("Data Vistoria (se já agendada)", value=None, format="DD/MM/YYYY")
            status = st.selectbox("Status*", options=status_options)

        st.divider()
        st.subheader("Upload de Documentos")
        bo_file = st.file_uploader("Upload do BO (PDF)", type="pdf")
        cnh_motorista_file = st.file_uploader("Upload CNH Motorista (PDF ou Imagem)",
                                              type=["pdf", "png", "jpg", "jpeg"])
        cnh_terceiro_file = st.file_uploader("Upload CNH Terceiro (PDF ou Imagem)", type=["pdf", "png", "jpg", "jpeg"])
        crlv_segurado_file = st.file_uploader("Upload CRLV - Segurado (PDF ou Imagem)",
                                              type=["pdf", "png", "jpg", "jpeg"])
        crlv_terceiro_file = st.file_uploader("Upload CRLV - Terceiro (PDF ou Imagem)",
                                              type=["pdf", "png", "jpg", "jpeg"])
        imagens_batida_files = st.file_uploader("Upload Imagens da Batida (uma ou mais)",
                                                type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

        submitted = st.form_submit_button("🚨 Cadastrar Sinistro", use_container_width=True, type="primary")

        if submitted:
            if not all([segurado, seguradora, numero_sinistro_segurado, tipo_ramo, numero_apolice, placa_segurado]):
                st.error("Por favor, preencha todos os campos obrigatórios (*).")
                return

            with st.spinner("Salvando informações e fazendo upload dos arquivos..."):
                sinistro_data = {
                    'segurado': segurado,
                    'seguradora': seguradora,
                    'numero_sinistro': numero_sinistro_segurado,
                    'numero_sinistro_terceiro': numero_sinistro_terceiro,
                    'tipo_ramo': tipo_ramo,
                    'numero_apolice': numero_apolice,
                    'placa_segurado': placa_segurado,
                    'nome_terceiro': nome_terceiro,
                    'contato_terceiro': contato_terceiro,
                    'contatou_terceiro': True if contatou_terceiro == "Sim" else False,
                    'data_abertura': data_abertura.isoformat(),
                    'data_vistoria': data_vistoria.isoformat() if data_vistoria else None,
                    'status': status,
                    'data_ultima_atualizacao': datetime.datetime.now(timezone.utc).isoformat(),
                    'usuario_cadastro': st.session_state.user_email
                }

                # ATUALIZAÇÃO: Adiciona os caminhos dos ficheiros apenas se eles existirem
                if bo_file:
                    sinistro_data['caminho_bo'] = salvar_ficheiros_supabase(bo_file, numero_sinistro_segurado, segurado,
                                                                            'sinistros')
                if cnh_motorista_file:
                    sinistro_data['caminho_cnh_motorista'] = salvar_ficheiros_supabase(cnh_motorista_file,
                                                                                       numero_sinistro_segurado,
                                                                                       segurado, 'sinistros')
                if cnh_terceiro_file:
                    sinistro_data['caminho_cnh_terceiro'] = salvar_ficheiros_supabase(cnh_terceiro_file,
                                                                                      numero_sinistro_segurado,
                                                                                      segurado, 'sinistros')
                if crlv_segurado_file:
                    sinistro_data['caminho_crlv_segurado'] = salvar_ficheiros_supabase(crlv_segurado_file,
                                                                                       numero_sinistro_segurado,
                                                                                       segurado, 'sinistros')
                if crlv_terceiro_file:
                    sinistro_data['caminho_crlv_terceiro'] = salvar_ficheiros_supabase(crlv_terceiro_file,
                                                                                       numero_sinistro_segurado,
                                                                                       segurado, 'sinistros')
                if imagens_batida_files:
                    sinistro_data['caminhos_imagens_batida'] = salvar_multiplos_ficheiros_supabase(imagens_batida_files,
                                                                                                   numero_sinistro_segurado,
                                                                                                   segurado,
                                                                                                   'sinistros')

                try:
                    supabase.table('sinistros').insert(sinistro_data).execute()
                    st.success(f"🎉 Sinistro nº {numero_sinistro_segurado} cadastrado com sucesso!")
                    st.balloons()
                except Exception as e:
                    if 'duplicate key value violates unique constraint "sinistros_numero_sinistro_key"' in str(e):
                        st.error(
                            f"❌ Erro: O número de sinistro do segurado '{numero_sinistro_segurado}' já existe no sistema.")
                    else:
                        st.error(f"❌ Ocorreu um erro inesperado ao salvar o sinistro: {e}")


def render_configuracoes():
    """
    Renderiza a página de configurações, agora integrada com o Supabase Auth
    para gerenciamento de usuários.
    """
    st.title("⚙️ Configurações do Sistema")
    tab1, tab2 = st.tabs(["Gerenciar Usuários", "Backup e Restauração"])

    # --- ABA 1: GERENCIAR USUÁRIOS (VERSÃO ATUALIZADA) ---
    with tab1:
        st.subheader("Usuários Cadastrados no Sistema")
        st.info("Esta lista mostra todos os usuários registrados no sistema de autenticação.")

        try:
            # --- CORREÇÃO 1: CRIAR CLIENTE ADMIN SEGURO ---
            admin_url = st.secrets["supabase_url"]
            admin_key = st.secrets["supabase_service_key"]
            supabase_admin: Client = create_client(admin_url, admin_key)

            # 1. BUSCAR USUÁRIOS (usando o cliente admin)
            response = supabase_admin.auth.admin.list_users()

            # --- ESTA É A CORREÇÃO ---
            # A resposta 'response' JÁ É a lista de usuários.
            users_list = response
            # --- FIM DA CORREÇÃO ---

            if users_list:
                # Processa a lista de usuários para exibição em um DataFrame
                processed_users = []
                # (O loop 'for user in users_list' agora funciona)
                for user in users_list:
                    processed_users.append({
                        'Nome Completo': user.user_metadata.get('nome_completo', 'N/A'),
                        'E-mail': user.email,
                        'Perfil': user.user_metadata.get('perfil', 'user'),
                        'Data de Cadastro': pd.to_datetime(user.created_at).strftime('%d/%m/%Y %H:%M'),
                        'ID': user.id
                    })

                usuarios_df = pd.DataFrame(processed_users)
                st.dataframe(usuarios_df[['Nome Completo', 'E-mail', 'Perfil', 'Data de Cadastro']],
                             use_container_width=True)
            else:
                st.write("Nenhum usuário encontrado no sistema de autenticação.")

        except Exception as e:
            st.error(f"Erro ao listar usuários do Supabase Auth: {e}")
            st.info("Verifique se a 'supabase_service_key' está configurada corretamente nos 'Secrets' do Streamlit.")

        # --- Formulário para Adicionar Novo Usuário (VERSÃO ATUALIZADA) ---
        with st.expander("➕ Adicionar Novo Usuário"):
            with st.form("form_novo_usuario", clear_on_submit=True):
                st.write("Crie um novo login para um funcionário acessar o sistema.")
                nome = st.text_input("Nome Completo*")
                email = st.text_input("E-mail*")
                senha = st.text_input("Senha Provisória*", type="password")
                perfil = st.selectbox("Perfil*", ["user", "admin"])

                submitted = st.form_submit_button("Criar Usuário no Sistema")

                if submitted:
                    if not all([nome, email, senha, perfil]):
                        st.warning("Todos os campos são obrigatórios.")
                    else:
                        try:
                            # 2. CRIAR USUÁRIO (usando o cliente admin, que já foi criado)
                            if 'supabase_admin' not in locals():
                                admin_url = st.secrets["supabase_url"]
                                admin_key = st.secrets["supabase_service_key"]
                                supabase_admin: Client = create_client(admin_url, admin_key)

                            user_response = supabase_admin.auth.admin.create_user({
                                "email": email,
                                "password": senha,
                                "email_confirm": True,
                                "user_metadata": {
                                    "nome_completo": nome,
                                    "perfil": perfil
                                }
                            })
                            st.success(f"✅ Usuário '{nome}' criado com sucesso!")
                            st.rerun()

                        except Exception as e:
                            st.error(f"❌ Erro ao criar usuário: {e}")

    # --- ABA 2: BACKUP (COM CORREÇÕES) ---
    with tab2:
        st.subheader("Backup de Dados (Exportar)")
        st.info("Exporte um arquivo CSV com todas as apólices ativas no sistema.")
        try:
            all_data_df = get_apolices()
            if not all_data_df.empty:
                csv_data = all_data_df.to_csv(index=False).encode('utf-8')

                st.download_button(
                    label="📥 Exportar Backup de Apólices (CSV)",
                    data=csv_data,
                    file_name=f"backup_apolices_{date.today()}.csv",
                    mime="text/csv",
                    key="download_backup_csv"
                )
            else:
                st.info("Nenhuma apólice para exportar.")
        except Exception as e:
            st.error(f"Não foi possível gerar o backup: {e}")


def render_agente_ia():
    """
    Nova interface de chat para o Agente MoreiraSeg.
    """
    st.title("🤖 Assistente Moreiraseg (IA)")
    st.caption("Seu copiloto para cobranças, consultas e gestão.")

    # --- BOTÃO DE AÇÃO (Movido para cá) ---
    with st.sidebar:
        st.divider()
        st.header("⚡ Ações Rápidas IA")

        if st.button("▶️ Executar Fluxo de Cobrança Agora", use_container_width=True):
            with st.spinner("O Agente está verificando todas as cobranças..."):
                try:
                    # Chama o agente para rodar o fluxo completo
                    res = executar_agente(
                        "Execute o fluxo de trabalho de cobrança e envie os lembretes de vencimento de hoje.")
                    st.success("Fluxo Executado!")
                    # Adiciona o resultado no chat para ficar registrado
                    st.session_state.messages.append(
                        {"role": "assistant", "content": f"✅ **Resultado do Fluxo Manual:**\n\n{res}"})
                except Exception as e:
                    st.error(f"Erro ao executar fluxo: {e}")

    # --- FIM DO BOTÃO ---

    # 1. Inicializar Histórico de Chat
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant",
             "content": "Olá! Sou a IA da Moreiraseg. Posso verificar cobranças do dia, consultar códigos de barras e te enviar. Como posso ajudar?"}
        ]

    # 2. Exibir Histórico
    for message in st.session_state.messages:
        avatar = "assets/Icone.png" if message["role"] == "assistant" else None
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])

    # 3. Campo de Entrada do Usuário
    if prompt := st.chat_input("Digite sua solicitação (ex: 'Qual o boleto da apólice 1002800150679?')..."):
        # Exibe msg usuario
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Processa a resposta da IA
        with st.chat_message("assistant", avatar="assets/Icone.png"):
            with st.spinner("Consultando dados..."):
                try:
                    # AQUI CHAMA O CÉREBRO (agent_logic.py)
                    resposta = executar_agente(prompt)

                    placeholder = st.empty()
                    full_response = ""
                    if len(resposta) > 500:
                        placeholder.markdown(resposta)
                    else:
                        for chunk in resposta.split(' '):
                            full_response += chunk + ' '
                            time.sleep(0.02)
                            placeholder.markdown(full_response + "▌")
                        placeholder.markdown(resposta)

                    st.session_state.messages.append({"role": "assistant", "content": resposta})
                except Exception as e:
                    erro_msg = f"❌ Ocorreu um erro técnico ao processar sua solicitação: {e}"
                    st.error(erro_msg)
                    st.session_state.messages.append({"role": "assistant", "content": erro_msg})


def main():
    st.set_page_config(page_title="Moreiraseg - Gestão de Apólices", page_icon=ICONE_PATH, layout="wide",
                       initial_sidebar_state="expanded")

    if 'user_email' not in st.session_state:
        st.session_state.user_email = None
        st.session_state.user_nome = None
        st.session_state.user_perfil = None

    if not st.session_state.user_email:
        # TELA DE LOGIN
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.image(ICONE_PATH, width=150)
            st.write("")
            with st.form("login_form"):
                email = st.text_input("📧 E-mail")
                senha = st.text_input("🔑 Senha", type="password")
                if st.form_submit_button("Entrar", use_container_width=True):
                    usuario = login_user(email, senha)
                    if usuario:
                        st.session_state.user_email = usuario['email']
                        st.session_state.user_nome = usuario['nome']
                        st.session_state.user_perfil = usuario['perfil']
                        st.rerun()
                    else:
                        st.error("Credenciais inválidas. Tente novamente.")
        return

    with st.sidebar:
        st.title(f"Olá, {st.session_state.user_nome.split()[0]}!")
        st.write(f"Perfil: `{st.session_state.user_perfil.capitalize()}`")
        st.image(ICONE_PATH, width=80)
        st.divider()

        menu_options = ["📊 Painel de Controle", "🚨 Sinistros", "➕ Cadastrar Apólice", "🔍 Pesquisar e Editar Apólice",
                        "🤖 Agente de IA"]
        if st.session_state.user_perfil == 'admin':
            menu_options.append("⚙️ Configurações")

        menu_opcao = st.radio("Menu Principal", menu_options)
        st.divider()

        # Botão manual para disparar o agente
        if st.button("⚡ Executar Cobrança Agora", help="Força o envio de mensagens para quem vence hoje",
                     use_container_width=True):
            with st.spinner("Ativando agente..."):
                res = executar_agente(
                    "Execute o fluxo de trabalho de cobrança e envie os lembretes de vencimento de hoje.")
                st.success("Comando enviado!")
                st.toast(res, icon="✅")
        # Na sua barra lateral (with st.sidebar:)
        if st.button("🚪 Sair do Sistema", use_container_width=True):
            try:
                # Linha crucial para invalidar o "crachá" no Supabase
                supabase.auth.sign_out()
            except Exception as e:
                print(f"Erro no sign out: {e}")  # Apenas para debug

            st.session_state.user_email = None
            st.session_state.user_nome = None
            st.session_state.user_perfil = None
            st.rerun()

    col1, col2, col3 = st.columns([2, 3, 2])
    with col2:
        st.image(LOGO_PATH)
    st.write("")

    if menu_opcao == "📊 Painel de Controle":
        render_dashboard()
    elif menu_opcao == "🚨 Sinistros":
        render_sinistros()
    elif menu_opcao == "➕ Cadastrar Apólice":
        render_cadastro_form()
    elif menu_opcao == "🔍 Pesquisar e Editar Apólice":
        render_pesquisa_e_edicao()
    elif menu_opcao == "🤖 Agente de IA":
        render_agente_ia()
    elif menu_opcao == "⚙️ Configurações" and st.session_state.user_perfil == 'admin':
        render_configuracoes()


if __name__ == "__main__":
    main()








