import sqlite3
from PIL import Image
import streamlit as st
from google import genai

# Configuração da página do Streamlit
st.set_page_config(
    page_title="Catálogo de Plantas", page_icon="🪴", layout="centered"
)

# Inicialização do Banco de Dados SQLite
conn = sqlite3.connect("plantas.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS plantas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_comum TEXT,
    nome_cientifico TEXT,
    cuidados TEXT,
    curiosidades TEXT,
    data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
)
conn.commit()

# Interface Principal
st.title("🪴 Catálogo e Identificador de Plantas")
st.write(
    "Tire uma foto ou carregue uma imagem para identificar e catalogar automaticamente."
)

# Barra Lateral - Chave de API
st.sidebar.header("Configurações")
api_key = st.sidebar.text_input(
    "Chave da API Gemini", type="password", help="Insira a sua chave do Google AI Studio"
)

# Navegação por Abas
tab1, tab2 = st.tabs(["📸 Identificar & Adicionar", "🔍 Banco de Dados"])

with tab1:
    origem_foto = st.radio(
        "Como deseja enviar a foto?", ("Câmara", "Carregar do Dispositivo")
    )

    imagem = None
    if origem_foto == "Câmara":
        foto_camara = st.camera_input("Tire uma foto da planta")
        if foto_camara:
            imagem = Image.open(foto_camara)
    else:
        foto_upload = st.file_uploader(
            "Escolha uma imagem...", type=["jpg", "jpeg", "png"]
        )
        if foto_upload:
            imagem = Image.open(foto_upload)

    if imagem:
        st.image(imagem, caption="Imagem para Análise", use_column_width=True)

        if not api_key:
            st.warning("Por favor, insira a sua Chave da API Gemini na barra lateral.")
        else:
            if st.button("✨ Analisar com Gemini IA"):
                try:
                    # Usando o novo cliente do SDK google-genai
                    client = genai.Client(api_key=api_key)

                    prompt = """
                    Analise esta imagem de planta e responda estritamente no seguinte formato:
                    Nome Comum: [Nome comum da planta em português]
                    Nome Científico: [Nome científico em itálico/latim]
                    Cuidados: [Breve resumo sobre iluminação, rega e solo]
                    Curiosidades: [Fato interessante sobre a espécie]
                    """

                    with st.spinner("A identificar a planta..."):
                        # Atualizado para o modelo gemini-3.8-flash requisitado pela API
                        response = client.models.generate_content(
                            model="gemini-3.8-flash",
                            contents=[prompt, imagem]
                        )
                        texto_resposta = response.text

                        st.success("Planta Identificada!")
                        st.markdown(texto_resposta)

                        # Processar o texto retornado para guardar no banco de dados
                        linhas = texto_resposta.strip().split("\n")
                        dados = {
                            "Nome Comum": "Desconhecido",
                            "Nome Científico": "Desconhecido",
                            "Cuidados": "Não informado",
                            "Curiosidades": "Não informado",
                        }

                        for linha in linhas:
                            if ":" in linha:
                                chave, valor = linha.split(":", 1)
                                chave_limpa = chave.strip()
                                if chave_limpa in dados:
                                    dados[chave_limpa] = valor.strip()

                        # Inserir no SQLite
                        cursor.execute(
                            """
                        INSERT INTO plantas (nome_comum, nome_cientifico, cuidados, curiosidades)
                        VALUES (?, ?, ?, ?)
                        """,
                            (
                                dados["Nome Comum"],
                                dados["Nome Científico"],
                                dados["Cuidados"],
                                dados["Curiosidades"],
                            ),
                        )
                        conn.commit()
                        st.info("✅ Dados salvos com sucesso no seu catálogo!")

                except Exception as e:
                    st.error(f"Erro ao processar imagem: {e}")

with tab2:
    st.header("📋 Plantas Cadastradas")

    # Busca por filtro
    busca = st.text_input("Buscar por nome comum ou científico:")

    if busca:
        cursor.execute(
            "SELECT * FROM plantas WHERE nome_comum LIKE ? OR nome_cientifico LIKE ?",
            (f"%{busca}%", f"%{busca}%"),
        )
    else:
        cursor.execute("SELECT * FROM plantas ORDER BY data_registro DESC")

    registros = cursor.fetchall()

    if registros:
        for reg in registros:
            with st.expander(f"🪴 {reg[1]} ({reg[2]})"):
                st.write(f"**Cuidados:** {reg[3]}")
                st.write(f"**Curiosidades:** {reg[4]}")
                st.caption(f"Registrado em: {reg[5]}")
    else:
        st.write("Nenhuma planta cadastrada ainda.")
