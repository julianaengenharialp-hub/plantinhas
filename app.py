
import base64
import hashlib
import io
import json
import sqlite3
from datetime import datetime

import requests
import streamlit as st
from PIL import Image

st.set_page_config(page_title="Meu Jardim", page_icon="🪴", layout="wide")

DB = "plantas.db"
GRUPOS = ["Sol pleno", "Luz indireta", "Pouca luz"]
STATUS = ["Pendente", "No catálogo", "Arquivada"]


def conectar():
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    return con


def preparar_banco():
    with conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS catalogo_v04 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_comum TEXT NOT NULL,
                nome_cientifico TEXT,
                familia TEXT,
                grupo TEXT,
                score REAL,
                status TEXT NOT NULL,
                local TEXT,
                observacoes TEXT,
                cuidados TEXT,
                imagem BLOB,
                criado_em TEXT NOT NULL
            )
        """)


def salvar(dados, foto):
    with conectar() as con:
        con.execute("""
            INSERT INTO catalogo_v04
            (nome_comum, nome_cientifico, familia, grupo, score, status,
             local, observacoes, cuidados, imagem, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            dados["nome_comum"],
            dados["nome_cientifico"],
            dados["familia"],
            dados["grupo"],
            dados.get("score"),
            dados["status"],
            "",
            dados["observacoes"],
            dados["cuidados"],
            foto,
            datetime.now().strftime("%d/%m/%Y %H:%M")
        ))


def atualizar(id_, dados):
    with conectar() as con:
        con.execute("""
            UPDATE catalogo_v04
            SET nome_comum=?, nome_cientifico=?, familia=?,
                grupo=?, status=?, observacoes=?, cuidados=?
            WHERE id=?
        """, (
            dados["nome_comum"],
            dados["nome_cientifico"],
            dados["familia"],
            dados["grupo"],
            dados["status"],
            dados["observacoes"],
            dados["cuidados"],
            id_
        ))


def excluir(id_):
    with conectar() as con:
        con.execute(
            "DELETE FROM catalogo_v04 WHERE id=?",
            (id_,)
        )


def tratar_foto(arquivo):
    imagem = Image.open(arquivo).convert("RGB")
    imagem.thumbnail((1200, 1200))

    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=82)

    return buffer.getvalue()


def gemini(foto):
    chave = st.secrets.get("GEMINI_API_KEY")

    if not chave:
        raise ValueError(
            "GEMINI_API_KEY não encontrada nos Secrets."
        )

    instrucao = """
    Analise a fotografia de uma planta para um catálogo
    doméstico brasileiro.

    Responda SOMENTE com um objeto JSON válido,
    sem markdown, contendo exatamente estes campos:

    nome_comum (string)
    nome_cientifico (string)
    familia (string)
    grupo (uma das strings: 'Sol pleno',
           'Luz indireta', 'Pouca luz', ou '')
    luminosidade (string)
    rega (string)
    substrato (string)
    seguranca_animais (string)
    justificativa_identificacao (string)
    identificacao_incerta (boolean)
    alternativas (lista de strings)

    Seja prudente: espécies visualmente semelhantes
    podem ser indistinguíveis.

    Não invente porcentagem de certeza, fatos
    botânicos, toxicidade ou fontes.

    Se não for possível identificar a espécie com
    segurança, use nome_cientifico no nível de
    gênero ou vazio, identificacao_incerta=true
    e grupo='' se não houver informação suficiente
    para recomendar luminosidade.

    Não considere tolerância à sombra como
    preferência por pouca luz.

    Na segurança para cães, gatos e coelhos,
    indique claramente quando não houver evidência
    confiável. Não garanta que uma planta é segura.

    Descreva cuidados gerais com cautela, pois
    clima e condições variam.

    Escreva em português do Brasil.
    """

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": instrucao},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64.b64encode(
                                foto
                            ).decode("ascii")
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2
        }
    }

    resposta = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        headers={
            "x-goog-api-key": chave,
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=90
    )

    if resposta.status_code == 429:
        raise ValueError(
            "Limite de uso do Gemini atingido (429). "
            "Tente novamente mais tarde."
        )

    if resposta.status_code >= 500:
        raise ValueError(
            "Gemini temporariamente indisponível. "
            "Você poderá tentar novamente."
        )

    if not resposta.ok:
        raise ValueError(
            f"Gemini retornou HTTP {resposta.status_code}: "
            f"{resposta.text[:250]}"
        )

    bruto = resposta.json()

    candidatos = bruto.get("candidates") or []
    if not candidatos:
        raise ValueError(
            "Gemini não devolveu uma identificação."
        )

    partes = candidatos[0].get(
        "content", {}
    ).get("parts", [])

    texto = "".join(
        p.get("text", "") for p in partes
    )

    if not texto.strip():
        raise ValueError(
            "Gemini não devolveu uma ficha."
        )

    try:
        ficha = json.loads(texto)
    except json.JSONDecodeError:
        raise ValueError(
            "A ficha veio em formato inesperado."
        )

    if not isinstance(ficha, dict):
        raise ValueError(
            "A resposta não contém uma ficha válida."
        )

    return ficha


def plantnet(foto):
    chave = st.secrets.get("PLANTNET_API_KEY")

    if not chave:
        raise ValueError(
            "PLANTNET_API_KEY não encontrada nos Secrets."
        )

    resposta = requests.post(
        "https://my-api.plantnet.org/v2/identify/all",
        params={
            "api-key": chave,
            "lang": "pt"
        },
        files={
            "images": (
                "planta.jpg",
                foto,
                "image/jpeg"
            )
        },
        data={"organs": "auto"},
        timeout=60
    )

    if not resposta.ok:
        raise ValueError(
            f"Pl@ntNet retornou HTTP "
            f"{resposta.status_code}: "
            f"{resposta.text[:200]}"
        )

    return resposta.json().get("results", [])


def campos(prefixo, inicial):
    nome = st.text_input(
        "Nome popular",
        value=str(
            inicial.get("nome_comum") or ""
        ),
        key=prefixo + "nome"
    )

    cientifico = st.text_input(
        "Nome científico",
        value=str(
            inicial.get("nome_cientifico") or ""
        ),
        key=prefixo + "cientifico"
    )

    familia = st.text_input(
        "Família",
        value=str(
            inicial.get("familia") or ""
        ),
        key=prefixo + "familia"
    )

    grupo_atual = inicial.get("grupo") or ""
    opcoes = ["Não definida"] + GRUPOS

    grupo = st.selectbox(
        "Luminosidade",
        opcoes,
        index=(
            opcoes.index(grupo_atual)
            if grupo_atual in opcoes else 0
        ),
        key=prefixo + "grupo"
    )

    cuidados = st.text_area(
        "Ficha de cuidados",
        value=str(
            inicial.get("cuidados") or ""
        ),
        height=220,
        key=prefixo + "cuidados"
    )

    observacoes = st.text_area(
        "Observações pessoais",
        value=str(
            inicial.get("observacoes") or ""
        ),
        key=prefixo + "observacoes"
    )

    status_atual = (
        inicial.get("status") or "Pendente"
    )

    status = st.selectbox(
        "Situação",
        STATUS,
        index=(
            STATUS.index(status_atual)
            if status_atual in STATUS else 0
        ),
        key=prefixo + "status"
    )

    return {
        "nome_comum": nome.strip(),
        "nome_cientifico": cientifico.strip(),
        "familia": familia.strip(),
        "grupo": (
            "" if grupo == "Não definida"
            else grupo
        ),
        "cuidados": cuidados.strip(),
        "observacoes": observacoes.strip(),
        "status": status,
        "score": inicial.get("score")
    }


def validar(dados):
    if not dados["nome_comum"]:
        st.error(
            "Informe um nome popular ou provisório."
        )
        return False

    if (
        dados["status"] == "No catálogo"
        and not dados["grupo"]
    ):
        st.error(
            "A luminosidade está indefinida. "
            "Revise a ficha ou salve como Pendente."
        )
        return False

    return True


# INICIALIZAÇÃO

preparar_banco()

st.title("🪴 Meu Jardim")

st.caption(
    "Identificação por IA • Pl@ntNet como "
    "segunda opinião • fichas revisáveis"
)

st.warning(
    "Armazenamento ainda provisório: o banco local "
    "do Streamlit Cloud pode ser apagado em "
    "reinicializações. Não cadastre sua coleção "
    "definitiva nesta versão."
)

aba_foto, aba_catalogo = st.tabs([
    "📸 Identificar planta",
    "🌿 Meu catálogo"
])


# IDENTIFICAÇÃO

with aba_foto:

    origem = st.radio(
        "Fotografia",
        ["Enviar imagem", "Tirar foto"],
        horizontal=True
    )

    if origem == "Enviar imagem":
        arquivo = st.file_uploader(
            "Selecione uma foto",
            type=["jpg", "jpeg", "png"]
        )
    else:
        arquivo = st.camera_input(
            "Fotografe a planta"
        )

    if arquivo is not None:
        try:
            foto = tratar_foto(arquivo)

            assinatura = hashlib.sha256(
                foto
            ).hexdigest()

            if st.session_state.get(
                "foto_id"
            ) != assinatura:

                st.session_state[
                    "foto_id"
                ] = assinatura

                for chave in [
                    "ficha_ia",
                    "opiniao_plantnet",
                    "foto_salva"
                ]:
                    st.session_state.pop(
                        chave, None
                    )

            col_img, col_acao = st.columns([1, 1])

            with col_img:
                st.image(
                    foto,
                    use_container_width=True
                )

            with col_acao:
                st.write(
                    "**Análise da fotografia**"
                )

                if st.button(
                    "✨ Gerar ficha com Gemini",
                    type="primary",
                    use_container_width=True
                ):
                    try:
                        with st.spinner(
                            "Analisando e preparando "
                            "a ficha..."
                        ):
                            st.session_state[
                                "ficha_ia"
                            ] = gemini(foto)

                        st.session_state.pop(
                            "foto_salva", None
                        )

                    except (
                        ValueError,
                        requests.RequestException
                    ) as erro:
                        st.error(str(erro))

                if st.button(
                    "🔎 Segunda opinião: Pl@ntNet",
                    use_container_width=True
                ):
                    try:
                        with st.spinner(
                            "Consultando Pl@ntNet..."
                        ):
                            st.session_state[
                                "opiniao_plantnet"
                            ] = plantnet(foto)

                    except (
                        ValueError,
                        requests.RequestException
                    ) as erro:
                        st.error(str(erro))

            if "opiniao_plantnet" in st.session_state:

                with st.expander(
                    "Resultados da segunda opinião",
                    expanded=True
                ):
                    resultados = st.session_state[
                        "opiniao_plantnet"
                    ]

                    if not resultados:
                        st.info(
                            "Nenhuma sugestão encontrada."
                        )

                    for item in resultados[:5]:
                        esp = (
                            item.get("species") or {}
                        )

                        nome = (
                            esp.get(
                                "scientificNameWithoutAuthor"
                            )
                            or esp.get(
                                "scientificName"
                            )
                            or "Não informado"
                        )

                        score = float(
                            item.get("score") or 0
                        )

                        st.write(
                            f"*{nome}* • score Pl@ntNet: "
                            f"{score * 100:.1f}%"
                        )

                    st.caption(
                        "Scores de correspondência "
                        "não garantem identificação correta."
                    )

            ficha = st.session_state.get(
                "ficha_ia"
            )

            if ficha:

                st.subheader(
                    "Ficha técnica sugerida"
                )

                if ficha.get(
                    "identificacao_incerta"
                ):
                    st.warning(
                        "Identificação incerta. "
                        "Compare as alternativas "
                        "antes de confirmar."
                    )

                st.markdown(
                    "**Por que a IA sugeriu "
                    "essa identificação?**"
                )

                st.write(
                    ficha.get(
                        "justificativa_identificacao"
                    ) or "Não informado"
                )

                alternativas = (
                    ficha.get("alternativas") or []
                )

                if alternativas:
                    st.caption(
                        "Outras possibilidades: "
                        + ", ".join(
                            str(x)
                            for x in alternativas
                        )
                    )

                cuidados = "\n".join([
                    "Luminosidade: "
                    + str(
                        ficha.get("luminosidade")
                        or "Não informada"
                    ),
                    "Rega: "
                    + str(
                        ficha.get("rega")
                        or "Não informada"
                    ),
                    "Substrato: "
                    + str(
                        ficha.get("substrato")
                        or "Não informado"
                    ),
                    "Segurança para animais: "
                    + str(
                        ficha.get("seguranca_animais")
                        or "Não verificada"
                    )
                ])

                inicial = {
                    "nome_comum": (
                        ficha.get("nome_comum")
                        or "Planta a identificar"
                    ),
                    "nome_cientifico": (
                        ficha.get("nome_cientifico")
                        or ""
                    ),
                    "familia": (
                        ficha.get("familia") or ""
                    ),
                    "grupo": (
                        ficha.get("grupo")
                        if ficha.get("grupo") in GRUPOS
                        else ""
                    ),
                    "cuidados": cuidados,
                    "observacoes": "",
                    "status": (
                        "Pendente"
                        if ficha.get(
                            "identificacao_incerta"
                        )
                        else "No catálogo"
                    ),
                    "score": None
                }

                st.info(
                    "Confira a identificação e os cuidados. "
                    "As orientações da IA podem conter erros, "
                    "especialmente sobre toxicidade para animais."
                )

                if st.session_state.get(
                    "foto_salva"
                ) == assinatura:

                    st.success(
                        "Planta salva. Confira "
                        "a aba Meu catálogo."
                    )

                else:

                    with st.form(
                        "form_nova_planta"
                    ):
                        dados = campos(
                            "nova_", inicial
                        )

                        enviar = (
                            st.form_submit_button(
                                "💾 Salvar planta",
                                type="primary"
                            )
                        )

                    if enviar and validar(dados):
                        salvar(dados, foto)

                        st.session_state[
                            "foto_salva"
                        ] = assinatura

                        st.rerun()

        except (
            OSError,
            ValueError
        ) as erro:
            st.error(
                "Não foi possível abrir "
                f"a fotografia: {erro}"
            )


# CATÁLOGO UNIFICADO

with aba_catalogo:

    with conectar() as con:
        plantas = [
            dict(p)
            for p in con.execute(
                "SELECT * FROM catalogo_v04 "
                "ORDER BY id DESC"
            ).fetchall()
        ]

    total = sum(
        p["status"] == "No catálogo"
        for p in plantas
    )

    pendentes = sum(
        p["status"] == "Pendente"
        for p in plantas
    )

    arquivadas = sum(
        p["status"] == "Arquivada"
        for p in plantas
    )

    c1, c2, c3 = st.columns(3)

    c1.metric("No catálogo", total)
    c2.metric("Pendentes", pendentes)
    c3.metric("Arquivadas", arquivadas)

    f1, f2 = st.columns(2)

    with f1:
        filtro_status = st.multiselect(
            "Situação",
            STATUS,
            default=[
                "No catálogo",
                "Pendente"
            ]
        )

    with f2:
        filtro_luz = st.selectbox(
            "Luminosidade",
            ["Todas"] + GRUPOS + [
                "Não definida"
            ]
        )

    busca = st.text_input(
        "Buscar pelo nome",
        placeholder=(
            "Nome popular ou científico"
        )
    )

    visiveis = [
        p for p in plantas

        if p["status"] in filtro_status

        and (
            filtro_luz == "Todas"
            or (
                not p["grupo"]
                if filtro_luz == "Não definida"
                else p["grupo"] == filtro_luz
            )
        )

        and busca.casefold() in (
            str(p["nome_comum"] or "")
            + " "
            + str(p["nome_cientifico"] or "")
        ).casefold()
    ]

    if not visiveis:
        st.info(
            "Nenhuma planta encontrada "
            "para esses filtros."
        )

    for inicio in range(
        0, len(visiveis), 3
    ):
        cols = st.columns(3)

        for col, planta in zip(
            cols,
            visiveis[inicio:inicio + 3]
        ):
            with col:

                with st.container(
                    border=True
                ):

                    if planta["imagem"]:
                        st.image(
                            planta["imagem"],
                            use_container_width=True
                        )

                    st.markdown(
                        f"**{planta['nome_comum']}**"
                    )

                    st.caption(
                        planta["nome_cientifico"]
                        or "Nome científico pendente"
                    )

                    st.write(
                        planta["grupo"]
                        or "Luminosidade a confirmar"
                    )

                    st.caption(
                        planta["status"]
                    )

                    with st.expander(
                        "Ver e editar ficha"
                    ):

                        with st.form(
                            f"editar_{planta['id']}"
                        ):
                            dados = campos(
                                f"edit_{planta['id']}_",
                                planta
                            )

                            gravar = (
                                st.form_submit_button(
                                    "Salvar alterações"
                                )
                            )

                        if gravar and validar(
                            dados
                        ):
                            atualizar(
                                planta["id"],
                                dados
                            )

                            st.rerun()

                        confirmar = st.checkbox(
                            "Confirmo a exclusão permanente",
                            key=f"conf_{planta['id']}"
                        )

                        if st.button(
                            "Excluir definitivamente",
                            key=f"del_{planta['id']}",
                            disabled=not confirmar
                        ):
                            excluir(
                                planta["id"]
                            )

                            st.rerun()
