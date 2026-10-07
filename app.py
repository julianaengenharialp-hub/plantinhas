# ============================================================
# MEU CATÁLOGO DE PLANTAS
# Versão 0.3
# Etapa 1.2 - Identificação com Pl@ntNet
# ============================================================

import io
import requests
from PIL import Image
import streamlit as st


# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="Meu Catálogo de Plantas",
    page_icon="🪴",
    layout="centered"
)


# ============================================================
# FUNÇÃO DE IDENTIFICAÇÃO
# ============================================================

def identificar_planta_plantnet(imagem_pil):
    """
    Envia a fotografia para a API do Pl@ntNet e retorna
    as identificações mais prováveis.
    """

    try:
        api_key = st.secrets["PLANTNET_API_KEY"]
    except KeyError:
        raise Exception(
            "A chave do Pl@ntNet não foi encontrada nos Secrets "
            "do Streamlit."
        )

    # --------------------------------------------------------
    # PREPARAR IMAGEM
    # --------------------------------------------------------

    imagem = imagem_pil.copy()

    if imagem.mode != "RGB":
        imagem = imagem.convert("RGB")

    # Evita enviar fotografias gigantes sem necessidade
    imagem.thumbnail((1600, 1600))

    buffer = io.BytesIO()

    imagem.save(
        buffer,
        format="JPEG",
        quality=90
    )

    buffer.seek(0)

    # --------------------------------------------------------
    # ENDPOINT DO PL@NTNET
    # --------------------------------------------------------

    url = (
        "https://my-api.plantnet.org/v2/identify/all"
    )

    params = {
        "api-key": api_key,
        "lang": "pt"
    }

    files = [
        (
            "images",
            (
                "planta.jpg",
                buffer.getvalue(),
                "image/jpeg"
            )
        )
    ]

    data = {
        "organs": "auto"
    }

    # --------------------------------------------------------
    # REQUISIÇÃO
    # --------------------------------------------------------

    try:

        resposta = requests.post(
            url,
            params=params,
            files=files,
            data=data,
            timeout=60
        )

    except requests.exceptions.Timeout:

        raise Exception(
            "O Pl@ntNet demorou demais para responder. "
            "Tente novamente."
        )

    except requests.exceptions.ConnectionError:

        raise Exception(
            "Não foi possível conectar ao Pl@ntNet."
        )

    # --------------------------------------------------------
    # TRATAMENTO DOS ERROS
    # --------------------------------------------------------

    if resposta.status_code == 401:

        raise Exception(
            "O Pl@ntNet não aceitou a chave da API. "
            "Verifique se a chave foi salva corretamente "
            "nos Secrets do Streamlit."
        )

    if resposta.status_code == 404:

        raise Exception(
            "O serviço de identificação do Pl@ntNet "
            "não foi encontrado."
        )

    if resposta.status_code == 429:

        raise Exception(
            "O limite de identificações disponível no "
            "Pl@ntNet foi atingido."
        )

    if resposta.status_code >= 500:

        raise Exception(
            "O Pl@ntNet está temporariamente indisponível. "
            "Tente novamente mais tarde."
        )

    if resposta.status_code != 200:

        try:
            detalhe = resposta.json()
        except Exception:
            detalhe = resposta.text

        raise Exception(
            f"O Pl@ntNet retornou o erro "
            f"{resposta.status_code}: {detalhe}"
        )

    # --------------------------------------------------------
    # INTERPRETAR RESPOSTA
    # --------------------------------------------------------

    try:
        dados = resposta.json()
    except Exception:
        raise Exception(
            "O Pl@ntNet respondeu, mas o aplicativo "
            "não conseguiu interpretar a resposta."
        )

    resultados = dados.get("results", [])

    if not resultados:

        raise Exception(
            "O Pl@ntNet não encontrou uma identificação "
            "compatível com esta fotografia."
        )

    return dados


# ============================================================
# CABEÇALHO
# ============================================================

st.title("🪴 Meu Catálogo de Plantas")

st.write(
    "Envie uma fotografia para obter sugestões de "
    "identificação botânica."
)

st.caption(
    "A identificação é realizada pelo Pl@ntNet e ainda "
    "não será adicionada automaticamente ao catálogo."
)


# ============================================================
# ABAS
# ============================================================

tab_identificar, tab_catalogo = st.tabs(
    [
        "📸 Identificar",
        "🪴 Meu Catálogo"
    ]
)


# ============================================================
# IDENTIFICAR
# ============================================================

with tab_identificar:

    st.subheader("Fotografia da planta")

    origem = st.radio(
        "Como deseja enviar a fotografia?",
        [
            "Tirar foto",
            "Carregar do dispositivo"
        ]
    )

    arquivo = None

    if origem == "Tirar foto":

        arquivo = st.camera_input(
            "Fotografe a planta"
        )

    else:

        arquivo = st.file_uploader(
            "Escolha uma fotografia",
            type=[
                "jpg",
                "jpeg",
                "png"
            ]
        )

    imagem = None

    if arquivo is not None:

        try:

            imagem = Image.open(arquivo)

            st.image(
                imagem,
                caption="Fotografia selecionada",
                use_container_width=True
            )

        except Exception:

            st.error(
                "Não foi possível abrir a fotografia."
            )

    # --------------------------------------------------------
    # IDENTIFICAR
    # --------------------------------------------------------

    if imagem is not None:

        if st.button(
            "🔎 Identificar planta",
            type="primary"
        ):

            try:

                with st.spinner(
                    "Comparando sua planta com a base "
                    "botânica do Pl@ntNet..."
                ):

                    dados = identificar_planta_plantnet(
                        imagem
                    )

                st.session_state[
                    "resultado_plantnet"
                ] = dados

            except Exception as erro:

                st.error(str(erro))


    # ========================================================
    # RESULTADO
    # ========================================================

    if "resultado_plantnet" in st.session_state:

        dados = st.session_state[
            "resultado_plantnet"
        ]

        resultados = dados.get(
            "results",
            []
        )

        st.divider()

        st.header(
            "Resultado da identificação"
        )

        if resultados:

            principal = resultados[0]

            especie = principal.get(
                "species",
                {}
            )

            score = principal.get(
                "score",
                0
            )

            nome_cientifico = especie.get(
                "scientificNameWithoutAuthor"
            )

            if not nome_cientifico:

                nome_cientifico = especie.get(
                    "scientificName",
                    "Não determinado"
                )

            nomes_comuns = especie.get(
                "commonNames",
                []
            )

            genero = especie.get(
                "genus",
                {}
            ).get(
                "scientificNameWithoutAuthor",
                ""
            )

            familia = especie.get(
                "family",
                {}
            ).get(
                "scientificNameWithoutAuthor",
                ""
            )

            # ------------------------------------------------
            # IDENTIFICAÇÃO PRINCIPAL
            # ------------------------------------------------

            if nomes_comuns:

                st.subheader(
                    nomes_comuns[0]
                )

            st.markdown(
                f"### *{nome_cientifico}*"
            )

            if familia:

                st.write(
                    f"**Família:** {familia}"
                )

            if genero:

                st.write(
                    f"**Gênero:** {genero}"
                )

            # ------------------------------------------------
            # SCORE
            # ------------------------------------------------

            percentual = round(
                score * 100,
                1
            )

            st.write(
                "**Compatibilidade da identificação**"
            )

            st.progress(
                max(
                    0.0,
                    min(
                        float(score),
                        1.0
                    )
                )
            )

            st.write(
                f"**{percentual}%**"
            )

            st.caption(
                "Este valor é o score retornado pelo "
                "Pl@ntNet para esta identificação. "
                "Ele não deve ser interpretado como "
                "confirmação botânica absoluta."
            )

            # ------------------------------------------------
            # AVALIAÇÃO VISUAL DO SCORE
            # ------------------------------------------------

            if score >= 0.70:

                st.success(
                    "A identificação apresentou "
                    "compatibilidade relativamente alta."
                )

            elif score >= 0.40:

                st.warning(
                    "A identificação apresentou "
                    "compatibilidade intermediária. "
                    "Vale conferir as alternativas abaixo."
                )

            else:

                st.error(
                    "A identificação apresentou "
                    "compatibilidade baixa. "
                    "Recomendamos outras fotografias "
                    "antes de confirmar a espécie."
                )

            # ------------------------------------------------
            # OUTROS NOMES COMUNS
            # ------------------------------------------------

            if len(nomes_comuns) > 1:

                st.write(
                    "**Outros nomes comuns informados "
                    "pelo Pl@ntNet:**"
                )

                for nome in nomes_comuns[1:]:

                    st.write(
                        f"• {nome}"
                    )

            # ------------------------------------------------
            # ALTERNATIVAS
            # ------------------------------------------------

            st.subheader(
                "🔎 Outras identificações possíveis"
            )

            alternativas_exibidas = 0

            for resultado in resultados[1:5]:

                especie_alt = resultado.get(
                    "species",
                    {}
                )

                nome_alt = especie_alt.get(
                    "scientificNameWithoutAuthor"
                )

                if not nome_alt:

                    nome_alt = especie_alt.get(
                        "scientificName",
                        "Espécie não determinada"
                    )

                score_alt = resultado.get(
                    "score",
                    0
                )

                percentual_alt = round(
                    score_alt * 100,
                    1
                )

                nomes_alt = especie_alt.get(
                    "commonNames",
                    []
                )

                if nomes_alt:

                    st.write(
                        f"**{nomes_alt[0]}** — "
                        f"*{nome_alt}* — "
                        f"{percentual_alt}%"
                    )

                else:

                    st.write(
                        f"*{nome_alt}* — "
                        f"{percentual_alt}%"
                    )

                alternativas_exibidas += 1

            if alternativas_exibidas == 0:

                st.write(
                    "Nenhuma alternativa relevante "
                    "foi retornada."
                )

            # ------------------------------------------------
            # AVISO
            # ------------------------------------------------

            st.divider()

            st.info(
                "Esta identificação ainda não foi "
                "adicionada ao seu catálogo. "
                "Primeiro estamos validando o sistema "
                "de reconhecimento."
            )


# ============================================================
# CATÁLOGO
# ============================================================

with tab_catalogo:

    st.header(
        "🪴 Meu Catálogo"
    )

    st.info(
        "O cadastro será ativado depois que validarmos "
        "a identificação pelo Pl@ntNet."
    )

    st.subheader(
        "Grupos do catálogo"
    )

    st.write(
        "☀️ **Sol pleno**"
    )

    st.write(
        "🌤️ **Luz indireta**"
    )

    st.write(
        "🌥️ **Pouca luz**"
    )

    st.divider()

    st.write(
        "Também teremos:"
    )

    st.write(
        "⏳ **Pendentes** — aguardando sua conferência"
    )

    st.write(
        "📦 **Arquivadas** — plantas que já fizeram "
        "parte da coleção"
    )

    st.write(
        "🗑️ **Excluir** — remoção definitiva"
    )
