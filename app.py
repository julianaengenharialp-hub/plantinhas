
import base64
import hashlib
import io
import json
import sqlite3
from datetime import datetime

import requests
import streamlit as st
from PIL import Image


st.set_page_config(
    page_title="Meu Jardim",
    page_icon="🪴",
    layout="wide"
)

DB = "plantas.db"

GRUPOS = [
    "Sol pleno",
    "Luz indireta",
    "Pouca luz"
]

STATUS = [
    "Pendente",
    "No catálogo",
    "Arquivada"
]

GEMINI_BASE = (
    "https://generativelanguage.googleapis.com/v1beta"
)


# ============================================================
# BANCO DE DADOS
# ============================================================

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
            INSERT INTO catalogo_v04 (
                nome_comum,
                nome_cientifico,
                familia,
                grupo,
                score,
                status,
                local,
                observacoes,
                cuidados,
                imagem,
                criado_em
            )
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
            SET
                nome_comum=?,
                nome_cientifico=?,
                familia=?,
                grupo=?,
                status=?,
                observacoes=?,
                cuidados=?
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


# ============================================================
# FOTOGRAFIA
# ============================================================

def tratar_foto(arquivo):
    imagem = Image.open(arquivo).convert("RGB")
    imagem.thumbnail((1200, 1200))

    buffer = io.BytesIO()

    imagem.save(
        buffer,
        format="JPEG",
        quality=82
    )

    return buffer.getvalue()


# ============================================================
# GEMINI
# ============================================================

def chave_gemini():
    chave = st.secrets.get("GEMINI_API_KEY")

    if not chave:
        raise ValueError(
            "GEMINI_API_KEY não encontrada nos Secrets."
        )

    return chave


def diagnosticar_erro_gemini(resposta):
    """
    Extrai a mensagem real devolvida pelo Google.

    Não mostra cabeçalhos, URL com chave ou
    informações de autenticação.
    """

    codigo = resposta.status_code

    try:
        corpo = resposta.json()

        erro = corpo.get("error", {})

        mensagem = erro.get(
            "message",
            "O Google não forneceu uma descrição."
        )

        status = erro.get(
            "status",
            "Não informado"
        )

        detalhes = erro.get(
            "details",
            []
        )

    except (ValueError, TypeError, AttributeError):
        mensagem = (
            "A resposta do servidor não estava "
            "em formato JSON."
        )

        status = "Não informado"
        detalhes = []

    explicacao = {
        400: "A requisição foi rejeitada.",
        401: "Falha de autenticação.",
        403: "O projeto não tem permissão para esta operação.",
        404: "O modelo solicitado não está disponível.",
        429: "Cota ou limite de requisições atingido.",
        500: "Erro interno no servidor do Google.",
        502: "Falha de comunicação no serviço.",
        503: "O serviço não conseguiu atender à solicitação.",
        504: "Tempo de resposta do serviço esgotado."
    }.get(
        codigo,
        "O Google recusou ou não concluiu a solicitação."
    )

    resultado = (
        f"HTTP {codigo}\n\n"
        f"Status do Google: {status}\n\n"
        f"Explicação: {explicacao}\n\n"
        f"Mensagem original do Google:\n{mensagem}"
    )

    if detalhes:
        resultado += (
            "\n\nDetalhes adicionais:\n"
            + json.dumps(
                detalhes,
                ensure_ascii=False,
                indent=2
            )[:1500]
        )

    return resultado


def listar_modelos():
    resposta = requests.get(
        GEMINI_BASE + "/models",
        headers={
            "x-goog-api-key": chave_gemini()
        },
        params={
            "pageSize": 1000
        },
        timeout=30
    )

    if not resposta.ok:
        raise ValueError(
            diagnosticar_erro_gemini(resposta)
        )

    modelos = resposta.json().get(
        "models",
        []
    )

    return [
        m["name"].replace(
            "models/",
            "",
            1
        )
        for m in modelos
        if (
            "generateContent"
            in (
                m.get(
                    "supportedGenerationMethods"
                ) or []
            )
            and m.get(
                "name",
                ""
            ).startswith("models/gemini")
        )
    ]


def gerar_ficha_gemini(foto, modelo):

    instrucao = """
Você é um assistente de botânica e horticultura.

Analise esta fotografia e produza uma ficha técnica
de planta para um catálogo doméstico brasileiro.

Responda SOMENTE com JSON válido, contendo:

nome_comum: string
nome_cientifico: string
familia: string
grupo: string
luminosidade: string
rega: string
substrato: string
seguranca_animais: string
justificativa_identificacao: string
identificacao_incerta: boolean
alternativas: lista de strings

O grupo deve ser uma destas opções:
"Sol pleno", "Luz indireta", "Pouca luz" ou "".

Regras:

1. Não invente percentuais de confiança.

2. Explique quais características visíveis
   fundamentam a identificação.

3. Se houver dúvida entre espécies semelhantes,
   sinalize identificacao_incerta=true.

4. Não afirme identificação exata quando a
   fotografia não permitir diferenciá-la.

5. Se a luminosidade for incerta, use grupo="".

6. Diferencie tolerância à sombra de preferência
   por pouca luz.

7. Informe orientações gerais de rega e substrato.

8. Sobre segurança para cães, gatos e coelhos,
   não invente informações de toxicidade.
   Declare quando não houver evidência confiável.

9. Não afirme ter consultado fontes externas.

10. Escreva em português do Brasil.
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": instrucao
                    },
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
            "temperature": 0.2,
            "maxOutputTokens": 2048
        }
    }

    resposta = requests.post(
        (
            f"{GEMINI_BASE}/models/"
            f"{modelo}:generateContent"
        ),
        headers={
            "x-goog-api-key": chave_gemini(),
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=120
    )

    if not resposta.ok:
        raise ValueError(
            diagnosticar_erro_gemini(resposta)
        )

    retorno = resposta.json()

    candidatos = retorno.get(
        "candidates"
    ) or []

    if not candidatos:
        raise ValueError(
            "O Gemini não retornou uma identificação. "
            "Resposta recebida sem candidatos."
        )

    candidato = candidatos[0]

    partes = (
        candidato
        .get("content", {})
        .get("parts", [])
    )

    texto = "".join(
        parte.get("text", "")
        for parte in partes
    )

    if not texto.strip():
        motivo = candidato.get(
            "finishReason",
            "Não informado"
        )

        raise ValueError(
            "O Gemini não retornou texto.\n\n"
            f"Motivo de encerramento: {motivo}"
        )

    try:
        ficha = json.loads(texto)

    except json.JSONDecodeError:
        motivo = candidato.get(
            "finishReason",
            "Não informado"
        )

        raise ValueError(
            "O Gemini respondeu, mas a ficha "
            "não veio em JSON válido.\n\n"
            f"Motivo de encerramento: {motivo}"
        )

    if not isinstance(ficha, dict):
        raise ValueError(
            "O Gemini retornou um formato inesperado."
        )

    return ficha


# ============================================================
# PLANTNET
# ============================================================

def consultar_plantnet(foto):

    chave = st.secrets.get(
        "PLANTNET_API_KEY"
    )

    if not chave:
        raise ValueError(
            "PLANTNET_API_KEY não encontrada."
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
        data={
            "organs": "auto"
        },
        timeout=60
    )

    if not resposta.ok:
        raise ValueError(
            f"Pl@ntNet retornou HTTP "
            f"{resposta.status_code}."
        )

    return resposta.json().get(
        "results",
        []
    )


# ============================================================
# FORMULÁRIOS
# ============================================================

def texto_seguro(valor):
    if valor is None:
        return ""

    return str(valor)


def campos_formulario(prefixo, inicial):

    nome = st.text_input(
        "Nome popular",
        value=texto_seguro(
            inicial.get("nome_comum")
        ),
        key=prefixo + "nome"
    )

    cientifico = st.text_input(
        "Nome científico",
        value=texto_seguro(
            inicial.get("nome_cientifico")
        ),
        key=prefixo + "cientifico"
    )

    familia = st.text_input(
        "Família botânica",
        value=texto_seguro(
            inicial.get("familia")
        ),
        key=prefixo + "familia"
    )

    grupo_atual = (
        inicial.get("grupo") or ""
    )

    opcoes = [
        "Não definida"
    ] + GRUPOS

    grupo = st.selectbox(
        "Grupo de luminosidade",
        opcoes,
        index=(
            opcoes.index(grupo_atual)
            if grupo_atual in opcoes
            else 0
        ),
        key=prefixo + "grupo"
    )

    cuidados = st.text_area(
        "Ficha de cuidados",
        value=texto_seguro(
            inicial.get("cuidados")
        ),
        height=240,
        key=prefixo + "cuidados"
    )

    observacoes = st.text_area(
        "Observações pessoais",
        value=texto_seguro(
            inicial.get("observacoes")
        ),
        key=prefixo + "observacoes"
    )

    situacao = (
        inicial.get("status")
        or "Pendente"
    )

    status = st.selectbox(
        "Situação",
        STATUS,
        index=(
            STATUS.index(situacao)
            if situacao in STATUS
            else 0
        ),
        key=prefixo + "status"
    )

    return {
        "nome_comum": nome.strip(),
        "nome_cientifico": cientifico.strip(),
        "familia": familia.strip(),
        "grupo": (
            ""
            if grupo == "Não definida"
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
            "Revise a ficha ou mantenha como Pendente."
        )

        return False

    return True


# ============================================================
# APLICATIVO
# ============================================================

preparar_banco()

st.title("🪴 Meu Jardim")

st.caption(
    "Identificação por Gemini • "
    "Segunda opinião Pl@ntNet"
)

st.warning(
    "Armazenamento provisório: os cadastros "
    "podem ser perdidos após reinicializações "
    "do Streamlit."
)

aba_identificar, aba_catalogo = st.tabs([
    "📸 Identificar",
    "🌿 Meu catálogo"
])


# ============================================================
# ABA IDENTIFICAR
# ============================================================

with aba_identificar:

    with st.expander(
        "⚙️ Configuração do Gemini"
    ):

        modelo = st.text_input(
            "Modelo Gemini",
            value="gemini-3.1-flash-lite",
            key="modelo_gemini"
        ).strip()

        if st.button(
            "Consultar modelos disponíveis"
        ):

            try:
                with st.spinner(
                    "Consultando modelos..."
                ):
                    modelos = listar_modelos()

                if modelos:
                    st.code(
                        "\n".join(modelos)
                    )

                    st.caption(
                        "A presença na lista não "
                        "garante cota gratuita."
                    )

                else:
                    st.warning(
                        "Nenhum modelo encontrado."
                    )

            except (
                ValueError,
                requests.RequestException
            ) as erro:

                st.error(str(erro))

    origem = st.radio(
        "Fotografia",
        [
            "Enviar imagem",
            "Tirar foto"
        ],
        horizontal=True
    )

    if origem == "Enviar imagem":

        arquivo = st.file_uploader(
            "Selecione uma fotografia",
            type=[
                "jpg",
                "jpeg",
                "png"
            ]
        )

    else:

        arquivo = st.camera_input(
            "Fotografe sua planta"
        )

    if arquivo is not None:

        try:
            foto = tratar_foto(arquivo)

            assinatura = hashlib.sha256(
                foto
            ).hexdigest()

            if (
                st.session_state.get("foto_id")
                != assinatura
            ):

                st.session_state[
                    "foto_id"
                ] = assinatura

                for chave in [
                    "ficha_ia",
                    "opiniao_plantnet",
                    "foto_salva"
                ]:
                    st.session_state.pop(
                        chave,
                        None
                    )

            col_foto, col_botoes = st.columns(
                [1, 1]
            )

            with col_foto:

                st.image(
                    foto,
                    use_container_width=True
                )

            with col_botoes:

                st.subheader(
                    "Análise da fotografia"
                )

                if st.button(
                    "✨ Gerar ficha com Gemini",
                    type="primary",
                    use_container_width=True
                ):

                    if not modelo:

                        st.error(
                            "Informe um modelo Gemini."
                        )

                    else:

                        try:
                            with st.spinner(
                                "Identificando a planta..."
                            ):

                                ficha = (
                                    gerar_ficha_gemini(
                                        foto,
                                        modelo
                                    )
                                )

                            st.session_state[
                                "ficha_ia"
                            ] = ficha

                            st.session_state.pop(
                                "foto_salva",
                                None
                            )

                        except ValueError as erro:

                            st.error(
                                "Falha na consulta ao Gemini."
                            )

                            st.code(
                                str(erro),
                                language="text"
                            )

                        except requests.RequestException as erro:

                            st.error(
                                "Falha de conexão com "
                                "o serviço Gemini."
                            )

                            st.write(
                                type(erro).__name__
                            )

            with col_botoes:

                if st.button(
                    "🔎 Segunda opinião: Pl@ntNet",
                    use_container_width=True
                ):

                    try:
                        with st.spinner(
                            "Consultando Pl@ntNet..."
                        ):

                            resultados = (
                                consultar_plantnet(foto)
                            )

                        st.session_state[
                            "opiniao_plantnet"
                        ] = resultados

                    except (
                        ValueError,
                        requests.RequestException
                    ) as erro:

                        st.error(str(erro))

            resultados = st.session_state.get(
                "opiniao_plantnet"
            )

            if resultados is not None:

                with st.expander(
                    "Segunda opinião do Pl@ntNet",
                    expanded=True
                ):

                    if not resultados:

                        st.info(
                            "Nenhuma identificação encontrada."
                        )

                    for item in resultados[:5]:

                        especie = (
                            item.get("species")
                            or {}
                        )

                        nome = (
                            especie.get(
                                "scientificNameWithoutAuthor"
                            )
                            or especie.get(
                                "scientificName"
                            )
                            or "Não informado"
                        )

                        score = float(
                            item.get("score")
                            or 0
                        )

                        st.write(
                            f"*{nome}* • "
                            f"score: {score * 100:.1f}%"
                        )

                    st.caption(
                        "O score não representa "
                        "certeza estatística."
                    )

            ficha = st.session_state.get(
                "ficha_ia"
            )

            if ficha:

                st.divider()

                st.subheader(
                    "Ficha técnica sugerida"
                )

                if ficha.get(
                    "identificacao_incerta"
                ):

                    st.warning(
                        "Identificação incerta. "
                        "Confira antes de confirmar."
                    )

                st.markdown(
                    "**Justificativa da identificação**"
                )

                st.write(
                    ficha.get(
                        "justificativa_identificacao"
                    )
                    or "Não informada"
                )

                alternativas = (
                    ficha.get("alternativas")
                    or []
                )

                if isinstance(
                    alternativas,
                    list
                ) and alternativas:

                    st.write(
                        "**Outras possibilidades:** "
                        + ", ".join(
                            str(x)
                            for x in alternativas
                        )
                    )

                cuidados = "\n\n".join([
                    "LUMINOSIDADE\n"
                    + texto_seguro(
                        ficha.get("luminosidade")
                    ),

                    "REGA\n"
                    + texto_seguro(
                        ficha.get("rega")
                    ),

                    "SUBSTRATO\n"
                    + texto_seguro(
                        ficha.get("substrato")
                    ),

                    "SEGURANÇA PARA ANIMAIS\n"
                    + texto_seguro(
                        ficha.get("seguranca_animais")
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
                        ficha.get("familia")
                        or ""
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
                    "Revise as informações antes "
                    "de salvar. Informações de "
                    "toxicidade devem ser confirmadas "
                    "em fontes confiáveis."
                )

                if (
                    st.session_state.get("foto_salva")
                    == assinatura
                ):

                    st.success(
                        "Planta salva no catálogo!"
                    )

                else:

                    with st.form(
                        "cadastro_nova_planta"
                    ):

                        dados = campos_formulario(
                            "nova_",
                            inicial
                        )

                        enviado = (
                            st.form_submit_button(
                                "💾 Salvar planta",
                                type="primary"
                            )
                        )

                    if enviado and validar(dados):

                        salvar(
                            dados,
                            foto
                        )

                        st.session_state[
                            "foto_salva"
                        ] = assinatura

                        st.rerun()

        except (
            OSError,
            ValueError
        ) as erro:

            st.error(
                f"Erro ao processar fotografia: {erro}"
            )


# ============================================================
# ABA CATÁLOGO
# ============================================================

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

    c1.metric(
        "No catálogo",
        total
    )

    c2.metric(
        "Pendentes",
        pendentes
    )

    c3.metric(
        "Arquivadas",
        arquivadas
    )

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
            [
                "Todas"
            ] + GRUPOS + [
                "Não definida"
            ]
        )

    busca = st.text_input(
        "Buscar planta",
        placeholder=(
            "Nome popular ou científico"
        )
    )

    visiveis = [
        p
        for p in plantas

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
            texto_seguro(
                p["nome_comum"]
            )
            + " "
            + texto_seguro(
                p["nome_cientifico"]
            )
        ).casefold()
    ]

    if not visiveis:

        st.info(
            "Nenhuma planta encontrada."
        )

    for inicio in range(
        0,
        len(visiveis),
        3
    ):

        colunas = st.columns(3)

        for coluna, planta in zip(
            colunas,
            visiveis[
                inicio:inicio + 3
            ]
        ):

            with coluna:

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

                            dados = campos_formulario(
                                f"edit_{planta['id']}_",
                                planta
                            )

                            gravar = (
                                st.form_submit_button(
                                    "Salvar alterações"
                                )
                            )

                        if gravar and validar(dados):

                            atualizar(
                                planta["id"],
                                dados
                            )

                            st.rerun()

                        confirmar = st.checkbox(
                            "Confirmo a exclusão definitiva",
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
