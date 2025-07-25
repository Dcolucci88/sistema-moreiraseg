# moreiraseg_sistema.py
# VERSÃO FINAL: Gestão de Parcelas, Cadastro e Edição Inteligentes, Painel Híbrido e Correções Finais

import streamlit as st
import pandas as pd
import datetime
from datetime import date
import os
import re
import calendar

# Tente importar as bibliotecas necessárias, mostrando erros amigáveis.
try:
    from supabase import create_client, Client
except ImportError:
    st.error("Biblioteca do Supabase não encontrada. Verifique se 'supabase' está no seu `requirements.txt`.")
    st.stop()

try:
    import psycopg2
    from sqlalchemy import text
    from dateutil.relativedelta import relativedelta
except ImportError:
    st.error("Bibliotecas do banco de dados não encontradas. Adicione 'psycopg2-binary', 'SQLAlchemy' e 'python-dateutil' ao seu `requirements.txt`.")
    st.stop()

# --- CONFIGURAÇÕES GLOBAIS ---
ASSETS_DIR = "LogoTipo"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_azul.png")
ICONE_PATH = os.path.join(ASSETS_DIR, "Icone.png")

# --- CONEXÃO COM O BANCO DE DADOS (MÉTODO MODERNO) ---
try:
    conn = st.connection("postgresql", type="sql")
except Exception as e:
    st.error(f"❌ Falha ao configurar a conexão com o banco de dados: {e}")
    st.info("Verifique se seu arquivo 'secrets.toml' está configurado corretamente com a URL de conexão do Supabase.")
    st.stop()

# --- CONEXÃO COM O SUPABASE STORAGE ---
try:
    supabase_url = st.secrets["supabase"]["url"]
    supabase_key = st.secrets["supabase"]["service_key"]
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception as e:
    st.error(f"❌ Falha ao configurar a conexão com o Supabase Storage: {e}")
    st.info("Verifique se seu arquivo 'secrets.toml' está configurado com a seção [supabase] e as chaves 'url' e 'service_key'.")
    st.stop()

# --- FUNÇÃO DE INICIALIZAÇÃO DO BANCO DE DADOS ---
def init_db():
    try:
        with conn.session as s:
            s.execute(text('''
                CREATE TABLE IF NOT EXISTS apolices (
                    id SERIAL PRIMARY KEY, seguradora TEXT NOT NULL, cliente TEXT NOT NULL,
                    numero_apolice TEXT NOT NULL UNIQUE, placa TEXT, tipo_seguro TEXT NOT NULL,
                    valor_parcela REAL NOT NULL, comissao REAL, data_inicio_vigencia DATE NOT NULL,
                    quantidade_parcelas INTEGER NOT NULL, dia_vencimento INTEGER NOT NULL,
                    tipo_cobranca TEXT, contato TEXT NOT NULL, email TEXT, observacoes TEXT,
                    status TEXT NOT NULL DEFAULT 'Ativa', caminho_pdf_apolice TEXT, caminho_pdf_boletos TEXT,
                    data_cadastro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    data_atualizacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            s.execute(text('''
                CREATE TABLE IF NOT EXISTS parcelas (
                    id SERIAL PRIMARY KEY, apolice_id INTEGER NOT NULL, numero_parcela INTEGER NOT NULL,
                    data_vencimento DATE NOT NULL, valor REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pendente', data_pagamento DATE,
                    FOREIGN KEY (apolice_id) REFERENCES apolices(id) ON DELETE CASCADE
                )
            '''))
            s.execute(text('''
                CREATE TABLE IF NOT EXISTS historico (
                    id SERIAL PRIMARY KEY, apolice_id INTEGER NOT NULL, usuario TEXT NOT NULL,
                    acao TEXT NOT NULL, detalhes TEXT, data_acao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (apolice_id) REFERENCES apolices(id) ON DELETE CASCADE
                )
            '''))
            s.execute(text('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY, nome TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                    senha TEXT NOT NULL, perfil TEXT NOT NULL DEFAULT 'user',
                    data_cadastro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            user_exists = s.execute(text("SELECT id FROM usuarios WHERE email = :email"), {'email': 'adm@moreiraseg.com.br'}).fetchone()
            if not user_exists:
                s.execute(
                    text("INSERT INTO usuarios (nome, email, senha, perfil) VALUES (:nome, :email, :senha, :perfil)"),
                    {'nome': 'Administrador', 'email': 'adm@moreiraseg.com.br', 'senha': 'Salmo@139', 'perfil': 'admin'}
                )
            s.commit()
    except Exception as e:
        st.error(f"❌ Falha grave ao inicializar as tabelas do banco de dados: {e}")
        st.stop()

# --- FUNÇÕES DE LÓGICA DO SISTEMA ---

def salvar_ficheiros_supabase(ficheiro, numero_apolice, cliente, tipo_pasta):
    """Salva um único ficheiro no Supabase Storage."""
    try:
        bucket_name = st.secrets["buckets"][tipo_pasta]
        safe_cliente = re.sub(r'[^a-zA-Z0-9\s-]', '', cliente).strip().replace(' ', '_')
        file_bytes = ficheiro.getvalue()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        destination_path = f"{safe_cliente}/{numero_apolice}/{timestamp}_{ficheiro.name}"
        supabase.storage.from_(bucket_name).upload(path=destination_path, file=file_bytes, file_options={"content-type": ficheiro.type})
        public_url = supabase.storage.from_(bucket_name).get_public_url(destination_path)
        return public_url
    except Exception as e:
        st.error(f"❌ Falha no upload para o Supabase Storage: {e}")
        return None

def add_historico(apolice_id, usuario_email, acao, detalhes=""):
    try:
        with conn.session as s:
            s.execute(
                text('INSERT INTO historico (apolice_id, usuario, acao, detalhes) VALUES (:apolice_id, :usuario, :acao, :detalhes)'),
                {'apolice_id': apolice_id, 'usuario': usuario_email, 'acao': acao, 'detalhes': detalhes}
            )
            s.commit()
    except Exception:
        st.warning("⚠️ Não foi possível registrar a ação no histórico.")

def get_apolices(search_term=None):
    """Busca apólices e calcula a data final de vigência e os dias restantes para renovação."""
    try:
        query = "SELECT * FROM apolices"
        params = {}
        if search_term:
            query += " WHERE numero_apolice ILIKE :term OR cliente ILIKE :term OR placa ILIKE :term"
            params['term'] = f"%{search_term}%"
        query += " ORDER BY data_cadastro DESC"
        df = conn.query(query, params=params, ttl=60)
        if not df.empty:
            df['data_inicio_vigencia'] = pd.to_datetime(df['data_inicio_vigencia'])
            df['data_final_de_vigencia'] = df['data_inicio_vigencia'] + pd.DateOffset(years=1)
            today = pd.to_datetime(date.today())
            df['dias_restantes'] = (df['data_final_de_vigencia'] - today).dt.days
            def define_prioridade(dias):
                if pd.isna(dias) or dias < 0: return '⚪ Expirada'
                if dias <= 15: return '🔥 Urgente'
                elif dias <= 30: return '⚠️ Alta'
                elif dias <= 60: return '⚠️ Média'
                else: return '✅ Baixa'
            df['prioridade'] = df['dias_restantes'].apply(define_prioridade)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar apólices: {e}")
        return pd.DataFrame()

def get_parcelas_da_apolice(apolice_id):
    try:
        query = "SELECT * FROM parcelas WHERE apolice_id = :apolice_id ORDER BY numero_parcela ASC"
        df = conn.query(query, params={'apolice_id': apolice_id}, ttl=10)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar as parcelas: {e}")
        return pd.DataFrame()

def login_user(email, senha):
    try:
        user_df = conn.query("SELECT * FROM usuarios WHERE email = :email AND senha = :senha", params={'email': email, 'senha': senha}, ttl=10)
        return user_df.to_dict('records')[0] if not user_df.empty else None
    except Exception as e:
        st.error(f"Erro durante o login: {e}")
        return None

def update_apolice(apolice_id, update_data):
    """Salva as alterações de uma apólice e recria suas parcelas."""
    try:
        with conn.session as s:
            update_data['data_atualizacao'] = datetime.datetime.now(datetime.timezone.utc)
            dados_apolice_update = {k: v for k, v in update_data.items() if k not in ['vencimento_primeira_parcela', 'dia_vencimento_demais']}
            set_clause = ", ".join([f"{key} = :{key}" for key in dados_apolice_update.keys()])
            query_update = text(f"UPDATE apolices SET {set_clause} WHERE id = :apolice_id")
            params = dados_apolice_update.copy()
            params['apolice_id'] = apolice_id
            s.execute(query_update, params)
            query_delete_parcels = text("DELETE FROM parcelas WHERE apolice_id = :apolice_id")
            s.execute(query_delete_parcels, {'apolice_id': apolice_id})
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
                    "data_vencimento": vencimento_calculado, "valor": valor_parcela, "status": "Pendente"
                })
            if lista_parcelas_para_db:
                query_insert_parcels = text('INSERT INTO parcelas (apolice_id, numero_parcela, data_vencimento, valor, status) VALUES (:apolice_id, :numero_parcela, :data_vencimento, :valor, :status)')
                s.execute(query_insert_parcels, lista_parcelas_para_db)
            s.commit()
            add_historico(apolice_id, st.session_state.get('user_email', 'sistema'), 'Atualização de Apólice', f"Apólice atualizada e {quantidade_parcelas} parcelas recriadas.")
            return True
    except Exception as e:
        st.error(f"❌ Erro ao atualizar a apólice: {e}")
        return False

# --- RENDERIZAÇÃO DA INTERFACE ---

def render_dashboard():
    """FUNÇÃO ATUALIZADA: Painel de Controle com abas e filtro de datas futuras."""
    st.title("📊 Painel de Controle")
    tab_parcelas, tab_renovacoes = st.tabs(["📊 Controle de Parcelas", "🔥 Controle de Renovações"])
    
    with tab_parcelas:
        try:
            parcelas_df = conn.query("SELECT * FROM parcelas", ttl=60)
            total_apolices = conn.query("SELECT COUNT(id) as count FROM apolices", ttl=60)['count'][0]
        except Exception as e:
            st.error(f"Erro ao carregar dados para o dashboard de parcelas: {e}")
            return

        st.subheader("Visão Financeira (Parcelas)")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total de Apólices Ativas", total_apolices)
        
        if not parcelas_df.empty:
            today = pd.to_datetime(date.today()).tz_localize(None)
            parcelas_df['data_vencimento'] = pd.to_datetime(parcelas_df['data_vencimento'])
            pendentes_df = parcelas_df[parcelas_df['status'] == 'Pendente']
            col2.metric("Parcelas Pendentes", len(pendentes_df))
            valor_pendente = pendentes_df['valor'].sum()
            col3.metric("Valor Total Pendente", f"R${valor_pendente:,.2f}")
            urgentes_df = pendentes_df[(parcelas_df['data_vencimento'] >= today) & (parcelas_df['data_vencimento'] <= today + pd.Timedelta(days=15)) & (parcelas_df['status'] == 'Pendente')]
            col4.metric("Parcelas Urgentes", len(urgentes_df), "Vencem em até 15 dias")
        else:
            col2.metric("Parcelas Pendentes", 0)
            col3.metric("Valor Total Pendente", "R$ 0,00")
            col4.metric("Parcelas Urgentes", 0)
            
        st.divider()
        st.subheader("Situação das Próximas Parcelas a Vencer")
        # --- ALTERAÇÃO APLICADA AQUI ---
        if not parcelas_df.empty and 'id' in parcelas_df.columns:
            # Filtra para mostrar apenas parcelas pendentes com vencimento a partir de hoje
            hoje = pd.to_datetime(date.today())
            proximas_a_vencer = parcelas_df[(parcelas_df['status'] == 'Pendente') & (parcelas_df['data_vencimento'] >= hoje)].sort_values(by='data_vencimento').head(15)
            
            if not proximas_a_vencer.empty:
                apolice_info_df = conn.query("SELECT id, cliente, numero_apolice FROM apolices", ttl=60)
                proximas_a_vencer = pd.merge(proximas_a_vencer, apolice_info_df, left_on='apolice_id', right_on='id')
                cols_to_show = ['cliente', 'numero_apolice', 'numero_parcela', 'data_vencimento', 'valor']
                proximas_a_vencer['data_vencimento'] = proximas_a_vencer['data_vencimento'].dt.strftime('%d/%m/%Y')
                st.dataframe(proximas_a_vencer[cols_to_show], use_container_width=True)
            else:
                st.info("Nenhuma parcela pendente com vencimento futuro para exibir.")
        else:
            st.info("Nenhuma parcela cadastrada no sistema.")

    with tab_renovacoes:
        apolices_df = get_apolices()
        st.subheader("Visão de Renovação de Apólices")
        if apolices_df.empty:
            st.info("Nenhuma apólice cadastrada para analisar as renovações.")
            return
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
        cols_to_show_renovacao = ['cliente', 'numero_apolice', 'tipo_seguro', 'data_final_de_vigencia', 'dias_restantes']
        for tab, (prioridade, df) in zip(tabs_renovacao, prioridades_map.items()):
            with tab:
                if not df.empty:
                    df_display = df.copy()
                    df_display['data_final_de_vigencia'] = df_display['data_final_de_vigencia'].dt.strftime('%d/%m/%Y')
                    st.dataframe(df_display[cols_to_show_renovacao], use_container_width=True)
                else:
                    st.info(f"Nenhuma apólice com prioridade '{prioridade.split(' ')[-1]}'.")

# Substitua sua função render_dashboard por esta versão atualizada:

def render_dashboard():
    """FUNÇÃO ATUALIZADA: Painel de Controle com abas e filtro de datas futuras para os próximos 30 dias."""
    st.title("📊 Painel de Controle")
    tab_parcelas, tab_renovacoes = st.tabs(["📊 Controle de Parcelas", "🔥 Controle de Renovações"])
    
    with tab_parcelas:
        try:
            parcelas_df = conn.query("SELECT * FROM parcelas", ttl=60)
            total_apolices = conn.query("SELECT COUNT(id) as count FROM apolices", ttl=60)['count'][0]
        except Exception as e:
            st.error(f"Erro ao carregar dados para o dashboard de parcelas: {e}")
            return

        st.subheader("Visão Financeira (Parcelas)")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total de Apólices Ativas", total_apolices)
        
        if not parcelas_df.empty:
            today = pd.to_datetime(date.today()).tz_localize(None)
            parcelas_df['data_vencimento'] = pd.to_datetime(parcelas_df['data_vencimento'])
            pendentes_df = parcelas_df[parcelas_df['status'] == 'Pendente']
            col2.metric("Parcelas Pendentes", len(pendentes_df))
            valor_pendente = pendentes_df['valor'].sum()
            col3.metric("Valor Total Pendente", f"R${valor_pendente:,.2f}")
            
            # --- LÓGICA ALTERADA AQUI ---
            # O cálculo de "Parcelas Urgentes" agora também usa a nova regra de 30 dias
            data_limite_urgente = today + pd.Timedelta(days=30)
            urgentes_df = pendentes_df[
                (pendentes_df['data_vencimento'] >= today) & 
                (pendentes_df['data_vencimento'] <= data_limite_urgente)
            ]
            col4.metric("Parcelas Urgentes", len(urgentes_df), "Vencem nos próximos 30 dias")
        else:
            col2.metric("Parcelas Pendentes", 0)
            col3.metric("Valor Total Pendente", "R$ 0,00")
            col4.metric("Parcelas Urgentes", 0)
            
        st.divider()
        st.subheader("Situação das Parcelas a Vencer nos Próximos 30 Dias")
        
        if not parcelas_df.empty and 'id' in parcelas_df.columns:
            # --- LÓGICA ALTERADA AQUI ---
            # Filtra para mostrar apenas parcelas pendentes com vencimento entre hoje e os próximos 30 dias
            hoje_dt = pd.to_datetime(date.today())
            data_limite_30_dias = hoje_dt + pd.Timedelta(days=30)
            
            proximas_a_vencer = parcelas_df[
                (parcelas_df['status'] == 'Pendente') & 
                (parcelas_df['data_vencimento'] >= hoje_dt) &
                (parcelas_df['data_vencimento'] <= data_limite_30_dias)
            ].sort_values(by='data_vencimento')
            
            if not proximas_a_vencer.empty:
                apolice_info_df = conn.query("SELECT id, cliente, numero_apolice FROM apolices", ttl=60)
                proximas_a_vencer = pd.merge(proximas_a_vencer, apolice_info_df, left_on='apolice_id', right_on='id')
                cols_to_show = ['cliente', 'numero_apolice', 'numero_parcela', 'data_vencimento', 'valor']
                proximas_a_vencer['data_vencimento'] = proximas_a_vencer['data_vencimento'].dt.strftime('%d/%m/%Y')
                st.dataframe(proximas_a_vencer[cols_to_show], use_container_width=True)
            else:
                st.info("Nenhuma parcela pendente com vencimento nos próximos 30 dias.")
        else:
            st.info("Nenhuma parcela cadastrada no sistema.")

    with tab_renovacoes:
        # O código desta aba não precisa de alterações
        apolices_df = get_apolices()
        st.subheader("Visão de Renovação de Apólices")
        if apolices_df.empty:
            st.info("Nenhuma apólice cadastrada para analisar as renovações.")
            return
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
        cols_to_show_renovacao = ['cliente', 'numero_apolice', 'tipo_seguro', 'data_final_de_vigencia', 'dias_restantes']
        for tab, (prioridade, df) in zip(tabs_renovacao, prioridades_map.items()):
            with tab:
                if not df.empty:
                    df_display = df.copy()
                    df_display['data_final_de_vigencia'] = df_display['data_final_de_vigencia'].dt.strftime('%d/%m/%Y')
                    st.dataframe(df_display[cols_to_show_renovacao], use_container_width=True)
                else:
                    st.info(f"Nenhuma apólice com prioridade '{prioridade.split(' ')[-1]}'.")

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
                        df_display['data_vencimento'] = pd.to_datetime(df_display['data_vencimento']).dt.strftime('%d/%m/%Y')
                        df_display['valor'] = df_display['valor'].apply(lambda x: f"R$ {x:,.2f}")
                        st.dataframe(df_display[['numero_parcela', 'data_vencimento', 'valor', 'status']], use_container_width=True)
                    else:
                        st.warning("Nenhuma parcela encontrada para esta apólice. Preencha e salve o formulário abaixo para gerá-las.")
                    st.divider()
                    st.subheader("📝 Editar Informações e Gerar Parcelas")
                    with st.form(f"edit_form_{apolice_id}", clear_on_submit=False):
                        is_frota_atual = "Faturamento" == apolice_row.get('tipo_cobranca')
                        edit_is_frota = st.toggle("É uma apólice de Frota?", value=is_frota_atual, key=f"frota_{apolice_id}")
                        col1, col2 = st.columns(2)
                        with col1:
                            seguradora = st.text_input("Seguradora*", value=apolice_row['seguradora'], key=f"seg_{apolice_id}")
                            numero_apolice = st.text_input("Número da Apólice*", value=apolice_row['numero_apolice'], key=f"num_{apolice_id}")
                            tipo_seguro = st.selectbox("Tipo de Seguro*", ["Automóvel", "RCO", "Vida", "Residencial", "Empresarial", "Saúde", "Viagem", "Fiança", "Outro"], index=["Automóvel", "RCO", "Vida", "Residencial", "Empresarial", "Saúde", "Viagem", "Fiança", "Outro"].index(apolice_row['tipo_seguro']), key=f"tipo_{apolice_id}")
                        with col2:
                            cliente = st.text_input("Cliente*", value=apolice_row['cliente'], key=f"cli_{apolice_id}")
                            if edit_is_frota:
                                placas_input = st.text_area("Placas da Frota (uma por linha)*", value=apolice_row.get('placa', '').replace(', ', '\n'), height=105, key=f"placas_{apolice_id}")
                                placa_unica_input = ""
                            else:
                                placa_unica_input = st.text_input("🚗 Placa do Veículo (Opcional)", value=apolice_row.get('placa', ''), max_chars=10, key=f"placa_unica_{apolice_id}")
                                placas_input = ""
                            opcoes_cobranca = ["Boleto", "Boleto a Vista", "Faturamento", "Cartão de Crédito", "Débito em Conta"]
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
                            tipo_cobranca = st.selectbox("Tipo de Cobrança*", options=opcoes_cobranca, index=opcoes_cobranca.index(tipo_cobranca_selecionado), key=f"cobranca_{apolice_id}", disabled=edit_is_frota)
                        st.subheader("Vigência e Parcelamento")
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            data_inicio = st.date_input("📅 Início de Vigência*", value=pd.to_datetime(apolice_row['data_inicio_vigencia']), format="DD/MM/YYYY", key=f"inicio_{apolice_id}")
                        with col2:
                            primeira_parcela_existente = parcelas_df['data_vencimento'].iloc[0] if not parcelas_df.empty else datetime.date.today()
                            vencimento_primeira_parcela = st.date_input("📅 Vencimento da 1ª Parcela*", value=pd.to_datetime(primeira_parcela_existente), format="DD/MM/YYYY", key=f"venc1_{apolice_id}")
                        with col3:
                            dia_vencimento_demais = st.number_input("Dia Venc. Demais Parcelas*", min_value=1, max_value=31, value=int(apolice_row.get('dia_vencimento', 10)), key=f"dia_demais_{apolice_id}")
                        with col4:
                            quantidade_parcelas = st.number_input("Quantidade de Parcelas*", min_value=1, max_value=24, value=qtd_parcelas_valor, disabled=campos_travados, key=f"qtd_parc_{apolice_id}")
                        st.subheader("Valores e Comissão")
                        col1, col2 = st.columns(2)
                        with col1:
                            valor_parcela_str = st.text_input("💰 Valor de Cada Parcela (R$)*", value=f"{apolice_row.get('valor_parcela', 0.0):.2f}".replace('.',','), key=f"valor_{apolice_id}")
                        with col2:
                            comissao = st.number_input("💼 Comissão (%)", min_value=0.0, value=float(apolice_row.get('comissao', 10.0)), key=f"comissao_{apolice_id}")
                        st.subheader("Dados de Contato e Anexos")
                        contato = st.text_input("📱 Contato do Cliente*", value=apolice_row.get('contato', ''), key=f"contato_{apolice_id}")
                        email = st.text_input("📧 E-mail do Cliente", value=apolice_row.get('email', ''), key=f"email_{apolice_id}")
                        observacoes = st.text_area("📝 Observações", value=apolice_row.get('observacoes', ''), key=f"obs_{apolice_id}")
                        pdf_apolice_file = st.file_uploader("Substituir PDF da Apólice (Opcional)", type=["pdf"], key=f"pdf_apolice_{apolice_id}")
                        pdf_boletos_file = st.file_uploader("Substituir Carnê de Boletos (Opcional)", type=["pdf"], key=f"pdf_boletos_{apolice_id}")
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
                                'data_inicio_vigencia': data_inicio,
                                'quantidade_parcelas': quantidade_parcelas,
                                'dia_vencimento': dia_vencimento_demais,
                                'contato': contato, 'email': email, 'observacoes': observacoes,
                                'vencimento_primeira_parcela': vencimento_primeira_parcela,
                                'dia_vencimento_demais': dia_vencimento_demais
                            }
                            if pdf_apolice_file:
                                st.info("Fazendo upload da nova apólice...")
                                update_data['caminho_pdf_apolice'] = salvar_ficheiros_supabase(pdf_apolice_file, numero_apolice, cliente, 'apolices')
                            if pdf_boletos_file:
                                st.info("Fazendo upload do novo carnê...")
                                update_data['caminho_pdf_boletos'] = salvar_ficheiros_supabase(pdf_boletos_file, numero_apolice, cliente, 'boletos')
                            if update_apolice(apolice_id, update_data):
                                st.success("Apólice atualizada com sucesso!")
                                st.rerun()

def render_configuracoes():
    st.title("⚙️ Configurações do Sistema")
    tab1, tab2 = st.tabs(["Gerenciar Usuários", "Backup e Restauração"])
    with tab1:
        st.subheader("Usuários Cadastrados")
        try:
            usuarios_df = conn.query("SELECT id, nome, email, perfil, data_cadastro FROM usuarios", ttl=10)
            st.dataframe(usuarios_df, use_container_width=True)
        except Exception as e:
            st.error(f"Erro ao listar usuários: {e}")
        with st.expander("Adicionar Novo Usuário"):
            with st.form("form_novo_usuario", clear_on_submit=True):
                nome = st.text_input("Nome Completo")
                email = st.text_input("E-mail")
                senha = st.text_input("Senha", type="password")
                perfil = st.selectbox("Perfil", ["user", "admin"])
                if st.form_submit_button("Adicionar Usuário"):
                    if not all([nome, email, senha, perfil]):
                        st.warning("Todos os campos são obrigatórios.")
                    else:
                        try:
                            with conn.session as s:
                                s.execute(text("INSERT INTO usuarios (nome, email, senha, perfil) VALUES (:nome, :email, :senha, :perfil)"),
                                          {'nome': nome, 'email': email, 'senha': senha, 'perfil': perfil})
                                s.commit()
                            st.success(f"Usuário '{nome}' adicionado com sucesso!")
                            st.rerun()
                        except psycopg2.errors.UniqueViolation:
                            st.error(f"Erro: O e-mail '{email}' já está cadastrado.")
                        except Exception as e:
                            st.error(f"Erro ao adicionar usuário: {e}")
    with tab2:
        st.subheader("Backup de Dados (Exportar)")
        all_data_df = conn.query("SELECT * FROM apolices", ttl=10)
        if not all_data_df.empty:
            csv_data = all_data_df.to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Exportar Backup de Apólices (CSV)", data=csv_data,
                               file_name=f"backup_apolices_{date.today()}.csv", mime="text/csv")
        else:
            st.info("Nenhuma apólice para exportar.")

def main():
    st.set_page_config(page_title="Moreiraseg - Gestão de Apólices", page_icon=ICONE_PATH, layout="wide", initial_sidebar_state="expanded")
    init_db()
    if 'user_email' not in st.session_state:
        st.session_state.user_email = None
        st.session_state.user_nome = None
        st.session_state.user_perfil = None
    if not st.session_state.user_email:
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.image(ICONE_PATH, width=150)
            st.write("")
            with st.form("login_form"):
                email = st.text_input("📧 E-mail")
                senha = st.text_input("🔑 Senha", type="password")
                submit = st.form_submit_button("Entrar", use_container_width=True)
                if submit:
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
        menu_options = ["📊 Painel de Controle", "➕ Cadastrar Apólice", "🔍 Pesquisar e Editar Apólice"]
        if st.session_state.user_perfil == 'admin':
            menu_options.append("⚙️ Configurações")
        menu_opcao = st.radio("Menu Principal", menu_options)
        st.divider()
        if st.button("🚪 Sair do Sistema", use_container_width=True):
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
    elif menu_opcao == "➕ Cadastrar Apólice":
        render_cadastro_form()
    elif menu_opcao == "🔍 Pesquisar e Editar Apólice":
        render_pesquisa_e_edicao()
    elif menu_opcao == "⚙️ Configurações" and st.session_state.user_perfil == 'admin':
        render_configuracoes()

if __name__ == "__main__":
    main()
