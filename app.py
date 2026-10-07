import base64
import io
import sqlite3
import time
import requests
from PIL import Image
import streamlit as st

# Configuração da página do Streamlit
st.set_page_config(
    page_title="Catálogo de Plantas", page_icon="🪴", layout="centered"
)

# Inicialização do Banco de Dados SQLite com suporte a imagens
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
    imagem_base64 TEXT,
    data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
)

# Adiciona a coluna imagem_base64 caso a tabela já exista sem ela
try:
    cursor.execute("ALTER TABLE plantas ADD COLUMN imagem_base64 TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass


def extrair_texto_da_resposta(dados):
    """Extrai texto da resposta JSON do Gemini com fallback para várias estruturas."""
    try:
        candidates = dados.get("candidates", [])
        if not candidates:
            return None

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        textos = []
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                txt = part["text"].strip()
                if txt:
                    textos.append(txt)

        if textos:
            return "\n".join(textos)

        # Fallback de busca textual genérica caso a estrutura seja diferente
        return str(dados)
    except Exception:
        return None


def converter_imagem_para_base64(imagem_pil):
    """Converte a imagem PIL para string Base64 compacta para armazenar no SQLite."""
    if imagem_pil.mode in ("RGBA", "P"):
        imagem_pil = imagem_pil.convert("RGB")

    imagem_pil.thumbnail((800, 800))
    buffered = io.BytesIO()
    imagem_pil.save(buffered, format="JPEG", quality=80)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def analisar_planta_api_direta(imagem_pil, api_key):
    """Converte a imagem e realiza a chamada à API Gemini."""
    img_base64 = converter_imagem_para_base64(imagem_pil)

    modelo_ativo = "gemini-3.8-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo_ativo}:generateContent?key={api_key}"

    prompt_texto = """
    Analise esta imagem de planta e responda exatamente neste formato (mantenha os rótulos):
    Nome Comum: [Nome comum em português]
    Nome Científico: [Nome científico em latim]
    Cuidados: [Resumo de rega, iluminação e solo]
    Curiosidades: [Fato interessante sobre a planta]
    """

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_texto},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": img_base64,
                        }
                    },
                ]
            }
        ]
    }

    headers = {"Content-Type": "application/json"}

    for tentativa in range(3):
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=60
            )
            dados = response.json()

            if response.status_code == 200:
                texto = extrair_texto_da_resposta(dados)
                if texto:
                    return texto, img_base64
                raise Exception("A API não retornou texto válido.")

            if response.status_code in [429, 503] or "high demand" in response.text.lower():
                time.sleep(2)
                continue

            msg_erro = dados.get("error", {}).get("message", response.text)
            raise Exception(f"Erro {response.status_code}: {msg_erro}")

        except requests.exceptions.Timeout:
            if tentativa < 2:
                time.sleep(2)
                continue
            raise Exception("O servidor demorou para responder. Tente novamente.")
        except Exception as e:
            if tentativa == 2:
                raise e
            time.sleep(1)


# Interface Principal
st.title("🪴 Catálogo e Identificador de Plantas")
st.write(
    "Tire uma foto ou carregue uma imagem para identificar e catalogar automaticamente."
)

# Barra Lateral - Chave de API
st.sidebar.header("Configurações")
api_key = st.sidebar.text_input(
    "Chave da API Gemini",
    type="password",
    help="Insira a sua chave do Google AI Studio",
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
            st.warning(
                "Por favor, insira a sua Chave da API Gemini na barra lateral."
            )
        else:
            if st.button("✨ Analisar com Gemini IA"):
                try:
                    with st.spinner("A identificar a planta..."):
                        texto_resposta, img_b64 = analisar_planta_api_direta(
                            imagem, api_key
                        )

                    st.success("Planta Identificada com Sucesso!")
                    st.markdown(texto_resposta)

                    # Leitura dos campos retornados
                    dados_planta = {
                        "Nome Comum": "Desconhecido",
                        "Nome Científico": "Desconhecido",
                        "Cuidados": "Não informado",
                        "Curiosidades": "Não informado",
                    }

                    if texto_resposta:
                        for linha in texto_resposta.split("\n"):
                            if ":" in linha:
                                chave, valor = linha.split(":", 1)
                                chave_limpa = chave.strip()
                                for k in dados_planta.keys():
                                    if k.lower() in chave_limpa.lower():
                                        dados_planta[k] = valor.strip()

                    # Inserção no banco de dados SQLite com a foto em Base64
                    cursor.execute(
                        """
                    INSERT INTO plantas (nome_comum, nome_cientifico, cuidados, curiosidades, imagem_base64)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                        (
                            dados_planta["Nome Comum"],
                            dados_planta["Nome Científico"],
                            dados_planta["Cuidados"],
                            dados_planta["Curiosidades"],
                            img_b64,
                        ),
                    )
                    conn.commit()
                    st.info("✅ Dados e fotografia salvos com sucesso no catálogo!")

                except Exception as e:
                    st.error(f"Erro ao processar: {e}")

with tab2:
    st.header("📋 Plantas Cadastradas")

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
            # Estrutura do registro: (id, nome_comum, nome_cientifico, cuidados, curiosidades, imagem_base64, data_registro)
            nome_comum = reg[1] if reg[1] else "Desconhecido"
            nome_cientifico = reg[2] if reg[2] else "Desconhecido"
            cuidados = reg[3] if reg[3] else "Não informado"
            curiosidades = reg[4] if reg[4] else "Não informado"
            img_b64 = reg[5] if len(reg) > 5 else None
            data_reg = reg[6] if len(reg) > 6 else (reg[5] if len(reg) > 5 and not img_b64 else "")

            with st.expander(f"🪴 {nome_comum} ({nome_cientifico})"):
                col1, col2 = st.columns([1, 2])

                with col1:
                    if img_b64 and len(img_b64) > 100:
                        try:
                            img_bytes = base64.b64decode(img_b64)
                            img_display = Image.open(io.BytesIO(img_bytes))
                            st.image(img_display, use_column_width=True)
                        except Exception:
                            st.caption("📷 Imagem não disponível")
                    else:
                        st.caption("📷 Sem fotografia cadastrada")

                with col2:
                    st.write(f"**Cuidados:** {cuidados}")
                    st.write(f"**Curiosidades:** {curiosidades}")
                    if data_reg:
                        st.caption(f"Registado em: {data_reg}")
    else:
        st.write("Nenhuma planta cadastrada ainda.")
