import sqlite3
import streamlit as st
from google import genai
from PIL import Image

# 1. Configuração da página e do Banco de Dados SQLite
st.set_page_config(page_title="Catálogo de Plantas - Bunnito Pet", layout="wide")

conn = sqlite3.connect("catalogo_plantas.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS plantas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_popular TEXT,
        nome_botanico TEXT,
        familia TEXT,
        grupo TEXT,
        luminosidade TEXT,
        rega TEXT,
        substrato TEXT,
        pet_friendly TEXT,
        observacoes TEXT
    )
"""
)
conn.commit()

# 2. Interface Principal
st.title("🪴 Catálogo e Identificador de Plantas")
st.write(
    "Tire uma foto ou carregue uma imagem para identificar e catalogar automaticamente."
)

# Inserção da Chave de API
api_key = st.sidebar.text_input("Chave da API Gemini", type="password")

aba1, aba2 = st.tabs(["📷 Identificar & Adicionar", "🔍 Banco de Dados"])

with aba1:
    opcao_imagem = st.radio(
        "Como deseja enviar a foto?", ("Câmara", "Carregar do Dispositivo")
    )

    imagem_enviada = None
    if opcao_imagem == "Câmara":
        imagem_enviada = st.camera_input("Tire uma foto da planta")
    else:
        imagem_enviada = st.file_uploader(
            "Escolha uma imagem...", type=["jpg", "jpeg", "png"]
        )

    if imagem_enviada and api_key:
        image = Image.open(imagem_enviada)
        st.image(image, caption="Imagem para Análise", width=300)

        if st.button("✨ Analisar com Gemini IA"):
            with st.spinner("A identificar a planta e a extrair dados..."):
                try:
                    client = genai.Client(api_key=api_key)

                    prompt = """
                    Analise esta imagem de planta e retorne EXATAMENTE no seguinte formato de linhas (sem formatação markdown extra, apenas o texto):
                    Nome Popular: [Nome popular principal]
                    Nome Botânico: [Nome científico em itálico]
                    Família: [Família botânica]
                    Grupo: [Grupo 1 - Sol Pleno / Grupo 2 - Meia-Sombra / Outro]
                    Luminosidade: [Requisito de luz]
                    Rega: [Frequência de rega]
                    Substrato: [Tipo de solo ideal]
                    Pet Friendly: [Sim / Não / Cuidado (com leve explicação)]
                    Observações: [Breve descrição ou diagnósticos de cultivo/saúde]
                    """

                    response = client.models.generate_content(
                        model="gemini-2.5-flash", contents=[image, prompt]
                    )

                    st.success("Análise Concluída!")
                    resultado = response.text
                    st.text_area(
                        "Dados Extraídos:",
                        resultado,
                        height=220,
                    )

                    # Processamento simples das linhas para salvar no BD
                    linhas = resultado.strip().split("\n")
                    dados = {}
                    for linha in linhas:
                        if ":" in linha:
                            chave, valor = linha.split(":", 1)
                            dados[chave.strip()] = valor.strip()

                    # Guardar no SQLite
                    cursor.execute(
                        """
                        INSERT INTO plantas (nome_popular, nome_botanico, familia, grupo, luminosidade, rega, substrato, pet_friendly, observacoes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            dados.get("Nome Popular", "Desconhecido"),
                            dados.get("Nome Botânico", "N/A"),
                            dados.get("Família", "N/A"),
                            dados.get("Grupo", "N/A"),
                            dados.get("Luminosidade", "N/A"),
                            dados.get("Rega", "N/A"),
                            dados.get("Substrato", "N/A"),
                            dados.get("Pet Friendly", "N/A"),
                            dados.get("Observações", "N/A"),
                        ),
                    )
                    conn.commit()
                    st.success("✅ Planta registada com sucesso no Banco de Dados!")

                except Exception as e:
                    st.error(f"Erro ao processar imagem: {e}")

    elif imagem_enviada and not api_key:
        st.warning("Por favor, insira a sua Chave da API Gemini na barra lateral.")

with aba2:
    st.subheader("📋 Plantas Cadastradas")
    busca = st.text_input("🔍 Pesquisar por nome, grupo ou pet friendly:")

    query = "SELECT * FROM plantas"
    if busca:
        query += f" WHERE nome_popular LIKE '%{busca}%' OR nome_botanico LIKE '%{busca}%' OR pet_friendly LIKE '%{busca}%' OR grupo LIKE '%{busca}%'"

    cursor.execute(query)
    registos = cursor.fetchall()

    if registos:
        for reg in registos:
            with st.expander(f"🪴 {reg[1]} ({reg[2]})"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Família:** {reg[3]}")
                    st.write(f"**Grupo:** {reg[4]}")
                    st.write(f"**Luminosidade:** {reg[5]}")
                with col2:
                    st.write(f"**Rega:** {reg[6]}")
                    st.write(f"**Substrato:** {reg[7]}")
                    st.write(f"**Pet Friendly:** {reg[8]}")
                st.info(f"**Observações:** {reg[9]}")
    else:
        st.info("Nenhuma planta encontrada no banco de dados.")
