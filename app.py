
import base64
import hashlib
import io
import json
import sqlite3
from datetime import datetime
from html import escape

import requests
import streamlit as st
from PIL import Image, ImageOps, ImageChops, ImageStat

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as PDFImage,
    KeepTogether,
    PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# =====================================================
# CONFIGURAÇÃO
# =====================================================

st.set_page_config(
    page_title="Meu Jardim",
    page_icon="🪴",
    layout="wide"
)

DB = "plantas.db"
API = "https://generativelanguage.googleapis.com/v1beta"

GRUPOS = [
    "Sol pleno",
    "Luz indireta",
    "Pouca luz"
]

SOLOS = [
    "Bem drenado",
    "Orgânico",
    "Úmido",
    "Arenoso",
    "Outro",
    "Não definido"
]

TOXICIDADES = [
    "Não verificada",
    "Potencialmente tóxica",
    "Tóxica",
    "Sem toxicidade conhecida"
]

RARIDADES = [
    "Não avaliada",
    "Comum",
    "Incomum",
    "Rara"
]

STATUS = [
    "Pendente",
    "No catálogo",
    "Arquivada"
]

PREFERIDOS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash"
]


# =====================================================
# ESTILO
# =====================================================

st.markdown(
    """
    <style>
    .resumo-jardim {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin: 10px 0 25px;
    }

    .resumo-item {
        padding: 14px 12px;
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 12px;
        text-align: center;
        min-width: 0;
    }

    .resumo-numero {
        font-size: 32px;
        font-weight: 650;
        line-height: 1.2;
        margin-top: 7px;
    }

    .resumo-legenda {
        font-size: 13px;
        line-height: 1.3;
    }

    .simbolos-planta {
        text-align: center;
        font-size: 18px;
        letter-spacing: 1px;
        white-space: nowrap;
        margin: 4px 0;
    }

    .nome-planta {
        text-align: center;
        font-size: 13px;
        font-weight: 650;
        line-height: 1.3;
        min-height: 36px;
        overflow-wrap: anywhere;
    }

    @media (max-width: 700px) {
        .resumo-jardim {
            gap: 6px;
        }

        .resumo-item {
            padding: 11px 4px;
        }

        .resumo-numero {
            font-size: 26px;
        }

        .resumo-legenda {
            font-size: 11px;
        }

        .simbolos-planta {
            font-size: 16px;
            letter-spacing: 0;
        }

        [class*="st-key-galeria_responsiva"]
        [data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: wrap !important;
            align-items: stretch !important;
            gap: 8px !important;
        }

        [class*="st-key-galeria_responsiva"]
        [data-testid="column"] {
            flex: 0 0 calc(50% - 4px) !important;
            width: calc(50% - 4px) !important;
            min-width: 0 !important;
        }

        [class*="st-key-galeria_responsiva"]
        [data-testid="stVerticalBlockBorderWrapper"] {
            min-width: 0 !important;
        }

        [class*="st-key-galeria_responsiva"]
        [data-testid="stButton"] button {
            font-size: 12px;
            padding-left: 4px;
            padding-right: 4px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)


# =====================================================
# BANCO DE DADOS
# =====================================================

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

        existentes = {
            r["name"]
            for r in con.execute(
                "PRAGMA table_info(catalogo_v04)"
            )
        }

        novas = {
            "solo_tipo": "TEXT DEFAULT 'Não definido'",
            "toxicidade": "TEXT DEFAULT 'Não verificada'",
            "raridade": "TEXT DEFAULT 'Não avaliada'",
            "justificativa_raridade": "TEXT DEFAULT ''"
        }

        for nome, definicao in novas.items():
            if nome not in existentes:
                con.execute(
                    f"ALTER TABLE catalogo_v04 "
                    f"ADD COLUMN {nome} {definicao}"
                )


def salvar(dados, foto):
    with conectar() as con:
        con.execute("""
            INSERT INTO catalogo_v04 (
                nome_comum, nome_cientifico, familia,
                grupo, score, status, local,
                observacoes, cuidados, imagem,
                criado_em, solo_tipo, toxicidade,
                raridade, justificativa_raridade
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            dados["nome_comum"],
            dados["nome_cientifico"],
            dados["familia"],
            dados["grupo"],
            None,
            dados["status"],
            "",
            dados["observacoes"],
            dados["cuidados"],
            foto,
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            dados["solo_tipo"],
            dados["toxicidade"],
            dados["raridade"],
            dados["justificativa_raridade"]
        ))


def atualizar(id_, dados):
    with conectar() as con:
        con.execute("""
            UPDATE catalogo_v04 SET
                nome_comum=?,
                nome_cientifico=?,
                familia=?,
                grupo=?,
                status=?,
                observacoes=?,
                cuidados=?,
                solo_tipo=?,
                toxicidade=?,
                raridade=?,
                justificativa_raridade=?
            WHERE id=?
        """, (
            dados["nome_comum"],
            dados["nome_cientifico"],
            dados["familia"],
            dados["grupo"],
            dados["status"],
            dados["observacoes"],
            dados["cuidados"],
            dados["solo_tipo"],
            dados["toxicidade"],
            dados["raridade"],
            dados["justificativa_raridade"],
            id_
        ))


def excluir(id_):
    with conectar() as con:
        con.execute(
            "DELETE FROM catalogo_v04 WHERE id=?",
            (id_,)
        )


def plantas_salvas():
    with conectar() as con:
        return [
            dict(r)
            for r in con.execute(
                "SELECT * FROM catalogo_v04 ORDER BY id DESC"
            )
        ]


# =====================================================
# FOTOGRAFIAS
# =====================================================

def tratar_foto(arquivo):
    imagem = Image.open(arquivo)
    imagem = ImageOps.exif_transpose(imagem)
    imagem = imagem.convert("RGB")
    imagem.thumbnail((1200, 1200))

    buffer = io.BytesIO()
    imagem.save(
        buffer,
        format="JPEG",
        quality=82
    )

    return buffer.getvalue()


@st.cache_data(show_spinner=False, max_entries=200)
def imagem_quadrada(foto):
    imagem = Image.open(io.BytesIO(foto))
    imagem = ImageOps.exif_transpose(imagem)
    imagem = imagem.convert("RGB")

    imagem = ImageOps.fit(
        imagem,
        (400, 400),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5)
    )

    buffer = io.BytesIO()
    imagem.save(
        buffer,
        format="JPEG",
        quality=85
    )

    return buffer.getvalue()


def imagem_comparacao(foto):
    imagem = Image.open(io.BytesIO(foto))
    imagem = ImageOps.exif_transpose(imagem)
    imagem = imagem.convert("RGB")

    return ImageOps.fit(
        imagem,
        (96, 96),
        method=Image.Resampling.LANCZOS
    )


def imagens_praticamente_iguais(foto1, foto2):
    try:
        a = imagem_comparacao(foto1)
        b = imagem_comparacao(foto2)

        diferenca = ImageChops.difference(a, b)
        medias = ImageStat.Stat(diferenca).mean

        return sum(medias) / len(medias) < 8

    except (OSError, ValueError):
        return False


# =====================================================
# GEMINI AUTOMÁTICO
# =====================================================

def chave_gemini():
    chave = st.secrets.get("GEMINI_API_KEY")

    if not chave:
        raise ValueError(
            "GEMINI_API_KEY não encontrada nos Secrets."
        )

    return chave


def texto_erro(resposta):
    try:
        erro = resposta.json().get("error", {})
        mensagem = erro.get("message", "")
    except (ValueError, AttributeError):
        mensagem = "Resposta não estruturada."

    chave = st.secrets.get("GEMINI_API_KEY", "")

    if chave:
        mensagem = mensagem.replace(
            chave,
            "[CHAVE OCULTA]"
        )

    return (
        f"HTTP {resposta.status_code}: "
        f"{mensagem[:350]}"
    )


def modelo_elegivel(nome):
    nome = nome.lower()

    if not nome.startswith("gemini-"):
        return False

    proibidos = [
        "image",
        "tts",
        "transcribe",
        "audio",
        "omni",
        "robotics",
        "computer-use",
        "nano-banana",
        "customtools"
    ]

    if any(p in nome for p in proibidos):
        return False

    if "pro" in nome:
        return False

    return "flash" in nome or "lite" in nome


def listar_modelos_elegiveis():
    encontrados = []
    pagina = None

    while True:
        parametros = {"pageSize": 1000}

        if pagina:
            parametros["pageToken"] = pagina

        resposta = requests.get(
            API + "/models",
            headers={
                "x-goog-api-key": chave_gemini()
            },
            params=parametros,
            timeout=30
        )

        if not resposta.ok:
            raise ValueError(
                "Falha ao consultar modelos: "
                + texto_erro(resposta)
            )

        corpo = resposta.json()

        for item in corpo.get("models", []):
            metodos = (
                item.get("supportedGenerationMethods")
                or []
            )

            nome = item.get("name", "").replace(
                "models/",
                "",
                1
            )

            if (
                "generateContent" in metodos
                and modelo_elegivel(nome)
            ):
                encontrados.append(nome)

        pagina = corpo.get("nextPageToken")

        if not pagina:
            break

    encontrados = list(dict.fromkeys(encontrados))

    def prioridade(nome):
        if nome in PREFERIDOS:
            return (0, PREFERIDOS.index(nome))
        return (1, nome)

    encontrados.sort(key=prioridade)

    preferido = st.session_state.get(
        "modelo_gemini_funcionando"
    )

    if preferido in encontrados:
        encontrados.remove(preferido)
        encontrados.insert(0, preferido)

    return encontrados


def prompt_botanico():
    return """
Analise a fotografia de uma planta e gere uma
ficha botânica em português brasileiro.

Responda SOMENTE com JSON válido contendo:

nome_comum: string
nome_cientifico: string
familia: string
grupo: string
solo_tipo: string
toxicidade: string
raridade: string
justificativa_raridade: string
luminosidade: string
rega: string
substrato: string
seguranca_animais: string
crescimento: string
porte_adulto: string
propagacao: string
adubacao: string
problemas_comuns: string
justificativa_identificacao: string
identificacao_incerta: boolean
alternativas: lista de strings

GRUPO:
"Sol pleno", "Luz indireta", "Pouca luz" ou "".

SOLO_TIPO:
"Bem drenado", "Orgânico", "Úmido",
"Arenoso", "Outro", "Não definido".

TOXICIDADE:
"Não verificada", "Potencialmente tóxica",
"Tóxica", "Sem toxicidade conhecida".

RARIDADE:
"Não avaliada", "Comum", "Incomum", "Rara".

Regras:
- Identifique a espécie com prudência.
- Se espécies semelhantes não puderem ser
  diferenciadas, marque identificacao_incerta=true.
- Não invente porcentagens de confiança.
- Justifique a identificação com características
  observáveis na imagem.
- Informe luminosidade, rega, substrato,
  crescimento, porte adulto, propagação,
  adubação e problemas comuns.
- Não invente dados de toxicidade.
- Diferencie cães, gatos e coelhos.
- Declare quando a segurança não for conhecida.
- Ausência de dados não significa ausência
  de toxicidade.
- Raridade significa frequência no cultivo
  ornamental brasileiro, não ameaça de extinção.
- Não confunda aparência exótica com raridade.
- Se não houver fundamento para raridade,
  use "Não avaliada".
- Não afirme ter consultado fontes externas.
- Não preencha lacunas com informações inventadas.
"""


def consultar_modelo(foto, modelo):
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt_botanico()},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(
                            foto
                        ).decode("ascii")
                    }
                }
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 4096
        }
    }

    try:
        resposta = requests.post(
            f"{API}/models/{modelo}:generateContent",
            headers={
                "x-goog-api-key": chave_gemini(),
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=90
        )

    except requests.RequestException as erro:
        return (
            None,
            "Falha de conexão: "
            + type(erro).__name__,
            False
        )

    if not resposta.ok:
        interromper = resposta.status_code in (
            401, 403, 429
        )

        return (
            None,
            texto_erro(resposta),
            interromper
        )

    try:
        retorno = resposta.json()
        candidatos = retorno.get("candidates") or []

        if not candidatos:
            return None, "Resposta sem candidatos.", False

        candidato = candidatos[0]

        partes = candidato.get(
            "content", {}
        ).get("parts", [])

        resposta_texto = "".join(
            parte.get("text", "")
            for parte in partes
        )

        if not resposta_texto.strip():
            return (
                None,
                "Resposta vazia. Motivo: "
                + str(candidato.get("finishReason")),
                False
            )

        ficha = json.loads(resposta_texto)

        if not isinstance(ficha, dict):
            return (
                None,
                "Resposta não é um objeto JSON.",
                False
            )

        if not (
            ficha.get("nome_comum")
            or ficha.get("nome_cientifico")
        ):
            return (
                None,
                "Ficha sem identificação.",
                False
            )

        return ficha, None, False

    except (ValueError, TypeError, KeyError):
        return (
            None,
            "Ficha inválida ou incompleta.",
            False
        )


def identificar_automaticamente(foto):
    modelos = listar_modelos_elegiveis()

    if not modelos:
        raise ValueError(
            "Nenhum modelo Gemini Flash compatível "
            "foi encontrado."
        )

    tentativas = []
    progresso = st.progress(0)
    mensagem = st.empty()

    try:
        for indice, modelo in enumerate(modelos, 1):
            mensagem.info(
                f"Testando modelo {indice} de "
                f"{len(modelos)}: {modelo}"
            )

            ficha, erro, interromper = consultar_modelo(
                foto,
                modelo
            )

            progresso.progress(
                indice / len(modelos)
            )

            if ficha is not None:
                st.session_state[
                    "modelo_gemini_funcionando"
                ] = modelo

                st.session_state[
                    "diagnostico_gemini"
                ] = tentativas + [{
                    "modelo": modelo,
                    "resultado": "Funcionou"
                }]

                return ficha, modelo

            tentativas.append({
                "modelo": modelo,
                "resultado": erro
            })

            if interromper:
                break

    finally:
        progresso.empty()
        mensagem.empty()

    st.session_state[
        "diagnostico_gemini"
    ] = tentativas

    raise ValueError(
        "Nenhum modelo conseguiu gerar a ficha. "
        f"Foram realizadas {len(tentativas)} "
        "tentativa(s). Consulte o diagnóstico."
    )


# =====================================================
# PLANTNET
# =====================================================

def consultar_plantnet(foto):
    chave = st.secrets.get("PLANTNET_API_KEY")

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
        data={"organs": "auto"},
        timeout=60
    )

    if not resposta.ok:
        raise ValueError(
            f"Pl@ntNet retornou HTTP "
            f"{resposta.status_code}."
        )

    return resposta.json().get("results", [])


def urls_referencia_plantnet(resultado):
    urls_encontradas = []

    imagens = resultado.get("images") or []

    for imagem in imagens:
        if not isinstance(imagem, dict):
            continue

        urls = imagem.get("url") or {}

        if isinstance(urls, str):
            candidatas = [urls]

        elif isinstance(urls, dict):
            candidatas = [
                urls.get("m"),
                urls.get("o"),
                urls.get("s")
            ]

        else:
            candidatas = []

        for url in candidatas:
            if (
                isinstance(url, str)
                and url.startswith("https://")
                and url not in urls_encontradas
            ):
                urls_encontradas.append(url)

    return urls_encontradas


@st.cache_data(
    show_spinner=False,
    ttl=3600,
    max_entries=150
)
def baixar_imagem_referencia(url):
    try:
        resposta = requests.get(
            url,
            timeout=12,
            headers={
                "User-Agent": "MeuJardim/1.0"
            }
        )

        resposta.raise_for_status()

        tipo = resposta.headers.get(
            "Content-Type", ""
        ).lower()

        if not tipo.startswith("image/"):
            return None

        if len(resposta.content) > 8_000_000:
            return None

        imagem = Image.open(
            io.BytesIO(resposta.content)
        )
        imagem.load()
        imagem = ImageOps.exif_transpose(imagem)
        imagem = imagem.convert("RGB")
        imagem.thumbnail((900, 900))

        buffer = io.BytesIO()
        imagem.save(
            buffer,
            format="JPEG",
            quality=85
        )

        return buffer.getvalue()

    except (
        requests.RequestException,
        OSError,
        ValueError
    ):
        return None


def encontrar_foto_referencia(resultado, foto_usuario):
    urls = urls_referencia_plantnet(resultado)

    for url in urls[:8]:
        imagem = baixar_imagem_referencia(url)

        if imagem is None:
            continue

        if imagens_praticamente_iguais(
            imagem,
            foto_usuario
        ):
            continue

        return imagem

    return None


def mostrar_resultados_plantnet(foto, resultados):
    st.subheader("🔎 Segunda opinião do Pl@ntNet")

    if not resultados:
        st.info("Nenhuma sugestão encontrada.")
        return

    st.markdown("**Sua fotografia**")
    st.image(
        foto,
        width=260
    )

    st.caption(
        "As fotografias de referência aparecem "
        "somente quando disponíveis."
    )

    for indice, item in enumerate(resultados[:5], 1):
        especie = item.get("species") or {}

        nome = (
            especie.get("scientificNameWithoutAuthor")
            or especie.get("scientificName")
            or "Espécie não informada"
        )

        nomes_comuns = (
            especie.get("commonNames") or []
        )

        nome_popular = (
            nomes_comuns[0]
            if nomes_comuns
            else ""
        )

        score = float(item.get("score") or 0)

        with st.container(border=True):
            st.markdown(
                f"**{indice}. {nome}**"
            )

            if nome_popular:
                st.caption(nome_popular)

            st.write(
                f"Correspondência: "
                f"**{score * 100:.1f}%**"
            )

            referencia = encontrar_foto_referencia(
                item,
                foto
            )

            if referencia is not None:
                st.image(
                    referencia,
                    width=260,
                    caption="Fotografia de referência"
                )

    st.caption(
        "O percentual é o score do Pl@ntNet, "
        "não uma confirmação definitiva."
    )


# =====================================================
# FUNÇÕES AUXILIARES
# =====================================================

def texto(valor):
    return "" if valor is None else str(valor)


def escolha(valor, opcoes, padrao):
    return valor if valor in opcoes else padrao


def montar_cuidados(ficha):
    secoes = [
        ("LUMINOSIDADE", "luminosidade"),
        ("REGA", "rega"),
        ("SUBSTRATO", "substrato"),
        ("SEGURANÇA PARA ANIMAIS", "seguranca_animais"),
        ("CRESCIMENTO", "crescimento"),
        ("PORTE ADULTO", "porte_adulto"),
        ("PROPAGAÇÃO", "propagacao"),
        ("ADUBAÇÃO", "adubacao"),
        ("PROBLEMAS COMUNS", "problemas_comuns")
    ]

    return "\n\n".join(
        titulo + "\n" + (
            texto(ficha.get(chave))
            or "Não informado."
        )
        for titulo, chave in secoes
    )


def campos_formulario(prefixo, inicial):
    nome = st.text_input(
        "Nome popular",
        value=texto(inicial.get("nome_comum")),
        key=prefixo + "nome"
    )

    cientifico = st.text_input(
        "Nome científico",
        value=texto(inicial.get("nome_cientifico")),
        key=prefixo + "cientifico"
    )

    familia = st.text_input(
        "Família botânica",
        value=texto(inicial.get("familia")),
        key=prefixo + "familia"
    )

    st.markdown("**Indicadores do catálogo**")

    c1, c2 = st.columns(2)

    with c1:
        opcoes_luz = ["Não definida"] + GRUPOS

        luz_atual = escolha(
            inicial.get("grupo"),
            GRUPOS,
            "Não definida"
        )

        luz = st.selectbox(
            "☀️ Luminosidade",
            opcoes_luz,
            index=opcoes_luz.index(luz_atual),
            key=prefixo + "luz"
        )

        solo_atual = escolha(
            inicial.get("solo_tipo"),
            SOLOS,
            "Não definido"
        )

        solo = st.selectbox(
            "🌱 Solo",
            SOLOS,
            index=SOLOS.index(solo_atual),
            key=prefixo + "solo"
        )

    with c2:
        tox_atual = escolha(
            inicial.get("toxicidade"),
            TOXICIDADES,
            "Não verificada"
        )

        toxicidade = st.selectbox(
            "🛡️ Toxicidade",
            TOXICIDADES,
            index=TOXICIDADES.index(tox_atual),
            key=prefixo + "tox"
        )

        rar_atual = escolha(
            inicial.get("raridade"),
            RARIDADES,
            "Não avaliada"
        )

        raridade = st.selectbox(
            "💎 Raridade",
            RARIDADES,
            index=RARIDADES.index(rar_atual),
            key=prefixo + "rar"
        )

    justificativa = st.text_area(
        "Justificativa da raridade",
        value=texto(
            inicial.get("justificativa_raridade")
        ),
        height=75,
        key=prefixo + "just"
    )

    cuidados = st.text_area(
        "Ficha completa de cuidados",
        value=texto(inicial.get("cuidados")),
        height=280,
        key=prefixo + "cuidados"
    )

    observacoes = st.text_area(
        "Observações pessoais",
        value=texto(inicial.get("observacoes")),
        key=prefixo + "obs"
    )

    atual = escolha(
        inicial.get("status"),
        STATUS,
        "Pendente"
    )

    status = st.selectbox(
        "Situação",
        STATUS,
        index=STATUS.index(atual),
        key=prefixo + "status"
    )

    return {
        "nome_comum": nome.strip(),
        "nome_cientifico": cientifico.strip(),
        "familia": familia.strip(),
        "grupo": (
            "" if luz == "Não definida"
            else luz
        ),
        "solo_tipo": solo,
        "toxicidade": toxicidade,
        "raridade": raridade,
        "justificativa_raridade": justificativa.strip(),
        "cuidados": cuidados.strip(),
        "observacoes": observacoes.strip(),
        "status": status
    }


def validar(dados):
    if not dados["nome_comum"]:
        st.error("Informe um nome para a planta.")
        return False

    if (
        dados["status"] == "No catálogo"
        and not dados["grupo"]
    ):
        st.error(
            "Defina a luminosidade ou mantenha "
            "a planta como Pendente."
        )
        return False

    if (
        dados["raridade"] != "Não avaliada"
        and not dados["justificativa_raridade"]
    ):
        st.error(
            "Informe a justificativa da raridade "
            "ou escolha Não avaliada."
        )
        return False

    return True


def inicial_da_ficha(ficha):
    raridade = escolha(
        ficha.get("raridade"),
        RARIDADES,
        "Não avaliada"
    )

    justificativa = texto(
        ficha.get("justificativa_raridade")
    )

    if raridade != "Não avaliada" and not justificativa:
        raridade = "Não avaliada"

    return {
        "nome_comum": (
            ficha.get("nome_comum")
            or "Planta a identificar"
        ),
        "nome_cientifico": (
            ficha.get("nome_cientifico") or ""
        ),
        "familia": ficha.get("familia") or "",
        "grupo": escolha(
            ficha.get("grupo"),
            GRUPOS,
            ""
        ),
        "solo_tipo": escolha(
            ficha.get("solo_tipo"),
            SOLOS,
            "Não definido"
        ),
        "toxicidade": escolha(
            ficha.get("toxicidade"),
            TOXICIDADES,
            "Não verificada"
        ),
        "raridade": raridade,
        "justificativa_raridade": justificativa,
        "cuidados": montar_cuidados(ficha),
        "observacoes": "",
        "status": (
            "Pendente"
            if ficha.get("identificacao_incerta")
            else "No catálogo"
        )
    }


# =====================================================
# INDICADORES VISUAIS
# =====================================================

def dados_indicadores(planta):
    luz = planta.get("grupo") or "Não definida"
    solo = planta.get("solo_tipo") or "Não definido"
    tox = planta.get("toxicidade") or "Não verificada"
    rar = planta.get("raridade") or "Não avaliada"

    return [
        (
            {
                "Sol pleno": "☀️",
                "Luz indireta": "🌤️",
                "Pouca luz": "🌥️"
            }.get(luz, "❔"),
            "Luz",
            luz
        ),
        (
            {
                "Bem drenado": "🏜️",
                "Orgânico": "🌱",
                "Úmido": "💧",
                "Arenoso": "⏳"
            }.get(solo, "🪴"),
            "Solo",
            solo
        ),
        (
            {
                "Não verificada": "❔",
                "Potencialmente tóxica": "⚠️",
                "Tóxica": "☠️",
                "Sem toxicidade conhecida": "🛡️"
            }.get(tox, "❔"),
            "Toxicidade",
            tox
        ),
        (
            {
                "Não avaliada": "❔",
                "Comum": "🌿",
                "Incomum": "💎",
                "Rara": "✨"
            }.get(rar, "❔"),
            "Raridade",
            rar
        )
    ]


def indicadores_compactos(planta):
    indicadores = dados_indicadores(planta)

    simbolos = " ".join(
        icone for icone, _, _ in indicadores
    )

    st.markdown(
        "<div class='simbolos-planta'>"
        f"{simbolos}"
        "</div>",
        unsafe_allow_html=True
    )


def indicadores_detalhados(planta):
    linhas = []

    for icone, titulo, valor in dados_indicadores(planta):
        linhas.append(
            "<div style='text-align:center;min-width:0'>"
            f"<div style='font-size:24px'>{icone}</div>"
            f"<div style='font-size:11px'>"
            f"<b>{escape(titulo)}</b></div>"
            f"<div style='font-size:11px;"
            f"overflow-wrap:anywhere'>"
            f"{escape(valor)}</div>"
            "</div>"
        )

    st.markdown(
        "<div style='display:grid;"
        "grid-template-columns:repeat(4,minmax(0,1fr));"
        "gap:5px;margin:15px 0'>"
        + "".join(linhas)
        + "</div>",
        unsafe_allow_html=True
    )


# =====================================================
# PDF: FONTES E ESTILOS
# =====================================================

def registrar_fontes_pdf():
    """
    Procura fontes Unicode instaladas no sistema.
    Permite imprimir corretamente os acentos.
    """
    import os

    candidatos = [
        (
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf"
        ),
        (
            "/usr/share/fonts/truetype/liberation2/"
            "LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/"
            "LiberationSans-Bold.ttf"
        ),
        (
            "/usr/share/fonts/truetype/liberation/"
            "LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/"
            "LiberationSans-Bold.ttf"
        )
    ]

    for regular, negrito in candidatos:
        if os.path.exists(regular):
            if "JardimRegular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(
                    TTFont("JardimRegular", regular)
                )

            if os.path.exists(negrito):
                if "JardimBold" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(
                        TTFont("JardimBold", negrito)
                    )

                return "JardimRegular", "JardimBold"

            return "JardimRegular", "JardimRegular"

    return "Helvetica", "Helvetica-Bold"


def estilos_pdf():
    regular, negrito = registrar_fontes_pdf()

    estilos = {}

    estilos["titulo"] = ParagraphStyle(
        "JardimTitulo",
        fontName=negrito,
        fontSize=19,
        leading=25,
        textColor=colors.HexColor("#244D36"),
        spaceAfter=9
    )

    estilos["subtitulo"] = ParagraphStyle(
        "JardimSubtitulo",
        fontName=regular,
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#555555"),
        spaceAfter=12
    )

    estilos["nome"] = ParagraphStyle(
        "JardimNome",
        fontName=negrito,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#244D36"),
        spaceAfter=3
    )

    estilos["cientifico"] = ParagraphStyle(
        "JardimCientifico",
        fontName=regular,
        fontSize=8,
        leading=12,
        textColor=colors.HexColor("#666666"),
        spaceAfter=5
    )

    estilos["corpo"] = ParagraphStyle(
        "JardimCorpo",
        fontName=regular,
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#222222"),
        spaceAfter=6
    )

    estilos["pequeno"] = ParagraphStyle(
        "JardimPequeno",
        fontName=regular,
        fontSize=7.5,
        leading=11,
        textColor=colors.HexColor("#444444")
    )

    estilos["secao"] = ParagraphStyle(
        "JardimSecao",
        fontName=negrito,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#244D36"),
        spaceBefore=9,
        spaceAfter=5
    )

    estilos["centro"] = ParagraphStyle(
        "JardimCentro",
        fontName=regular,
        fontSize=8,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#444444")
    )

    return estilos


def ptexto(valor):
    """
    Escapa caracteres para uso seguro
    em Paragraph do ReportLab.
    """
    return escape(texto(valor)).replace(
        "\n",
        "<br/>"
    )


def imagem_pdf(foto, largura, altura):
    """
    Cria miniatura centralizada sem deformação.
    """
    if not foto:
        return Spacer(1, altura)

    try:
        imagem = Image.open(io.BytesIO(foto))
        imagem = ImageOps.exif_transpose(imagem)
        imagem = imagem.convert("RGB")

        imagem.thumbnail((900, 900))

        iw, ih = imagem.size

        escala = min(
            largura / iw,
            altura / ih
        )

        w = iw * escala
        h = ih * escala

        buffer = io.BytesIO()
        imagem.save(
            buffer,
            format="JPEG",
            quality=85
        )
        buffer.seek(0)

        figura = PDFImage(
            buffer,
            width=w,
            height=h
        )

        figura.hAlign = "CENTER"
        return figura

    except (OSError, ValueError, ZeroDivisionError):
        return Spacer(1, altura)


def rodape_pdf(canvas, doc):
    canvas.saveState()

    largura, _ = A4

    canvas.setStrokeColor(
        colors.HexColor("#DDDDDD")
    )

    canvas.line(
        16 * mm,
        15 * mm,
        largura - 16 * mm,
        15 * mm
    )

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(
        colors.HexColor("#666666")
    )

    canvas.drawString(
        16 * mm,
        10 * mm,
        "Meu Jardim | Catálogo pessoal"
    )

    canvas.drawRightString(
        largura - 16 * mm,
        10 * mm,
        f"Página {doc.page}"
    )

    canvas.restoreState()


def criar_documento_pdf(buffer):
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=17 * mm,
        bottomMargin=21 * mm,
        title="Meu Jardim",
        author="Meu Jardim"
    )


def cabecalho_relatorio(estilos, titulo, quantidade):
    return [
        Paragraph(
            ptexto(titulo),
            estilos["titulo"]
        ),
        Paragraph(
            (
                f"Gerado em "
                f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"
                f" | {quantidade} planta(s)"
            ),
            estilos["subtitulo"]
        )
    ]


# =====================================================
# PDF RESUMIDO
# =====================================================

def cartao_pdf_resumido(planta, estilos):
    largura = 53 * mm

    nome = (
        planta.get("nome_comum")
        or "Sem nome"
    )

    cientifico = (
        planta.get("nome_cientifico")
        or "Nome científico não informado"
    )

    informacoes = [
        imagem_pdf(
            planta.get("imagem"),
            47 * mm,
            43 * mm
        ),
        Spacer(1, 5),
        Paragraph(
            ptexto(nome),
            estilos["nome"]
        ),
        Paragraph(
            ptexto(cientifico),
            estilos["cientifico"]
        ),
        Paragraph(
            "Luz: " + ptexto(
                planta.get("grupo") or "Não definida"
            ),
            estilos["pequeno"]
        ),
        Paragraph(
            "Solo: " + ptexto(
                planta.get("solo_tipo") or "Não definido"
            ),
            estilos["pequeno"]
        ),
        Paragraph(
            "Toxicidade: " + ptexto(
                planta.get("toxicidade") or "Não verificada"
            ),
            estilos["pequeno"]
        ),
        Paragraph(
            "Raridade: " + ptexto(
                planta.get("raridade") or "Não avaliada"
            ),
            estilos["pequeno"]
        )
    ]

    return Table(
        [[informacoes]],
        colWidths=[largura],
        style=TableStyle([
            (
                "BOX",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#DDDDDD")
            ),
            (
                "BACKGROUND",
                (0, 0),
                (-1, -1),
                colors.white
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                3 * mm
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                3 * mm
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                3 * mm
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                3 * mm
            )
        ])
    )


def gerar_pdf_resumido(plantas):
    buffer = io.BytesIO()
    doc = criar_documento_pdf(buffer)
    estilos = estilos_pdf()

    elementos = cabecalho_relatorio(
        estilos,
        "Meu Jardim | Catálogo resumido",
        len(plantas)
    )

    if not plantas:
        elementos.append(
            Paragraph(
                "Nenhuma planta selecionada.",
                estilos["corpo"]
            )
        )
    else:
        cartoes = [
            cartao_pdf_resumido(p, estilos)
            for p in plantas
        ]

        linhas = []

        for inicio in range(0, len(cartoes), 3):
            linha = cartoes[inicio:inicio + 3]

            while len(linha) < 3:
                linha.append("")

            linhas.append(linha)

        tabela = Table(
            linhas,
            colWidths=[59 * mm] * 3,
            hAlign="CENTER"
        )

        tabela.setStyle(TableStyle([
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                2 * mm
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                2 * mm
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                2 * mm
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                2 * mm
            )
        ]))

        elementos.append(tabela)

    doc.build(
        elementos,
        onFirstPage=rodape_pdf,
        onLaterPages=rodape_pdf
    )

    return buffer.getvalue()


# =====================================================
# PDF COMPLETO
# =====================================================

def tabela_dados_pdf(planta, estilos):
    dados = [
        (
            "Nome popular",
            planta.get("nome_comum")
        ),
        (
            "Nome científico",
            planta.get("nome_cientifico")
        ),
        (
            "Família",
            planta.get("familia")
        ),
        (
            "Luminosidade",
            planta.get("grupo") or "Não definida"
        ),
        (
            "Tipo de solo",
            planta.get("solo_tipo") or "Não definido"
        ),
        (
            "Toxicidade",
            planta.get("toxicidade") or "Não verificada"
        ),
        (
            "Raridade",
            planta.get("raridade") or "Não avaliada"
        ),
        (
            "Situação",
            planta.get("status")
        )
    ]

    linhas = []

    for titulo, valor in dados:
        linhas.append([
            Paragraph(
                "<b>" + ptexto(titulo) + "</b>",
                estilos["pequeno"]
            ),
            Paragraph(
                ptexto(valor or "Não informado"),
                estilos["pequeno"]
            )
        ])

    tabela = Table(
        linhas,
        colWidths=[39 * mm, 137 * mm],
        hAlign="LEFT"
    )

    tabela.setStyle(TableStyle([
        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "TOP"
        ),
        (
            "LINEBELOW",
            (0, 0),
            (-1, -1),
            0.3,
            colors.HexColor("#E5E5E5")
        ),
        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            3
        ),
        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            3
        ),
        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            5
        ),
        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            5
        )
    ]))

    return tabela


def gerar_pdf_completo(plantas):
    buffer = io.BytesIO()
    doc = criar_documento_pdf(buffer)
    estilos = estilos_pdf()

    elementos = []

    if not plantas:
        elementos.extend(
            cabecalho_relatorio(
                estilos,
                "Meu Jardim | Fichas completas",
                0
            )
        )
        elementos.append(
            Paragraph(
                "Nenhuma planta selecionada.",
                estilos["corpo"]
            )
        )

    for indice, planta in enumerate(plantas):
        if indice > 0:
            elementos.append(PageBreak())

        elementos.extend(
            cabecalho_relatorio(
                estilos,
                "Ficha botânica",
                len(plantas)
            )
        )

        elementos.append(
            Paragraph(
                ptexto(
                    planta.get("nome_comum")
                    or "Planta sem nome"
                ),
                estilos["titulo"]
            )
        )

        if planta.get("imagem"):
            elementos.append(
                imagem_pdf(
                    planta["imagem"],
                    90 * mm,
                    65 * mm
                )
            )

            elementos.append(Spacer(1, 8))

        elementos.append(
            tabela_dados_pdf(
                planta,
                estilos
            )
        )

        if planta.get("justificativa_raridade"):
            elementos.append(
                Paragraph(
                    "Raridade",
                    estilos["secao"]
                )
            )
            elementos.append(
                Paragraph(
                    ptexto(
                        planta["justificativa_raridade"]
                    ),
                    estilos["corpo"]
                )
            )

        elementos.append(
            Paragraph(
                "Cuidados e cultivo",
                estilos["secao"]
            )
        )

        cuidados = (
            planta.get("cuidados")
            or "Ficha de cuidados não preenchida."
        )

        blocos = cuidados.split("\n\n")

        for bloco in blocos:
            bloco = bloco.strip()

            if not bloco:
                continue

            linhas = bloco.split("\n", 1)

            if (
                len(linhas) == 2
                and linhas[0].isupper()
                and len(linhas[0]) < 60
            ):
                elementos.append(
                    KeepTogether([
                        Paragraph(
                            ptexto(linhas[0]),
                            estilos["secao"]
                        ),
                        Paragraph(
                            ptexto(linhas[1]),
                            estilos["corpo"]
                        )
                    ])
                )

            else:
                elementos.append(
                    Paragraph(
                        ptexto(bloco),
                        estilos["corpo"]
                    )
                )

        if planta.get("observacoes"):
            elementos.append(
                Paragraph(
                    "Minhas observações",
                    estilos["secao"]
                )
            )
            elementos.append(
                Paragraph(
                    ptexto(
                        planta["observacoes"]
                    ),
                    estilos["corpo"]
                )
            )

        elementos.append(Spacer(1, 8))

        elementos.append(
            Paragraph(
                (
                    "A identificação e as informações "
                    "de cultivo podem ter sido geradas "
                    "por inteligência artificial. "
                    "Verifique especialmente a "
                    "toxicidade para animais."
                ),
                estilos["pequeno"]
            )
        )

    doc.build(
        elementos,
        onFirstPage=rodape_pdf,
        onLaterPages=rodape_pdf
    )

    return buffer.getvalue()


# =====================================================
# JANELA DA FICHA
# =====================================================

@st.dialog("🌿 Ficha da planta", width="large")
def abrir_ficha(planta):
    id_ = planta["id"]

    st.subheader(planta["nome_comum"])

    if planta.get("nome_cientifico"):
        st.caption(
            planta["nome_cientifico"]
        )

    st.caption(
        f"Situação: {planta['status']}"
    )

    if planta.get("imagem"):
        st.image(
            planta["imagem"],
            use_container_width=True
        )

    indicadores_detalhados(planta)

    st.divider()

    st.markdown("**Cuidados e cultivo**")

    st.text(
        texto(planta.get("cuidados"))
        or "Ficha não preenchida."
    )

    if planta.get("justificativa_raridade"):
        st.markdown("**Raridade**")
        st.write(
            planta["justificativa_raridade"]
        )

    if planta.get("observacoes"):
        st.markdown("**Minhas observações**")
        st.write(
            planta["observacoes"]
        )

    st.caption(
        "Informações geradas por IA devem ser "
        "verificadas, especialmente a toxicidade."
    )

    with st.expander("✏️ Editar esta planta"):
        with st.form(f"editar_{id_}"):
            dados = campos_formulario(
                f"edit_{id_}_",
                planta
            )

            gravar = st.form_submit_button(
                "💾 Salvar alterações",
                type="primary"
            )

        if gravar and validar(dados):
            atualizar(id_, dados)
            st.rerun()

    with st.expander("🗑️ Excluir planta"):
        st.warning(
            "A exclusão é definitiva."
        )

        confirmar = st.checkbox(
            "Confirmo que desejo excluir esta planta",
            key=f"confirmar_{id_}"
        )

        if st.button(
            "Excluir definitivamente",
            key=f"excluir_{id_}",
            disabled=not confirmar
        ):
            excluir(id_)
            st.rerun()


# =====================================================
# CARTÃO COMPACTO
# =====================================================

def cartao_compacto(planta):
    with st.container(border=True):
        if planta.get("imagem"):
            try:
                st.image(
                    imagem_quadrada(planta["imagem"]),
                    use_container_width=True
                )

            except (OSError, ValueError):
                st.caption("Imagem indisponível")
        else:
            st.info("Sem foto")

        nome = texto(
            planta.get("nome_comum")
        )

        st.markdown(
            "<div class='nome-planta'>"
            f"{escape(nome)}"
            "</div>",
            unsafe_allow_html=True
        )

        if planta["status"] == "Pendente":
            st.caption("🟡 Pendente")

        elif planta["status"] == "Arquivada":
            st.caption("📦 Arquivada")

        indicadores_compactos(planta)

        if st.button(
            "Ver ficha",
            key=f"abrir_{planta['id']}",
            use_container_width=True
        ):
            abrir_ficha(planta)


# =====================================================
# INICIALIZAÇÃO
# =====================================================

preparar_banco()

st.title("🪴 Meu Jardim")
st.caption("Seu catálogo pessoal de plantas")

with st.expander("ℹ️ Sobre o armazenamento"):
    st.warning(
        "O armazenamento ainda é provisório. "
        "Os registros podem ser perdidos quando "
        "o Streamlit Cloud reiniciar."
    )

aba_identificar, aba_catalogo = st.tabs([
    "📸 Identificar planta",
    "🌿 Meu catálogo"
])


# =====================================================
# IDENTIFICAÇÃO
# =====================================================

with aba_identificar:
    modelo_ativo = st.session_state.get(
        "modelo_gemini_funcionando"
    )

    if modelo_ativo:
        st.caption(
            "Gemini automático • "
            f"Último modelo funcional: {modelo_ativo}"
        )
    else:
        st.caption(
            "Gemini automático • Seleção "
            "automática de modelo compatível."
        )

    origem = st.radio(
        "Fotografia",
        ["Enviar imagem", "Tirar foto"],
        horizontal=True
    )

    if origem == "Enviar imagem":
        arquivo = st.file_uploader(
            "Escolha uma fotografia",
            type=["jpg", "jpeg", "png"]
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

            if st.session_state.get("foto_id") != assinatura:
                st.session_state["foto_id"] = assinatura

                for chave in [
                    "ficha_ia",
                    "opiniao_plantnet",
                    "foto_salva",
                    "diagnostico_gemini"
                ]:
                    st.session_state.pop(chave, None)

            st.image(
                foto,
                width=320,
                caption="Fotografia enviada"
            )

            st.subheader("Análise da fotografia")

            if st.button(
                "✨ Gerar ficha automaticamente",
                type="primary",
                use_container_width=True
            ):
                try:
                    with st.spinner(
                        "Identificando a planta..."
                    ):
                        ficha, modelo_usado = (
                            identificar_automaticamente(foto)
                        )

                    st.session_state["ficha_ia"] = ficha

                    st.session_state.pop(
                        "foto_salva",
                        None
                    )

                    st.success(
                        "Ficha gerada com sucesso! "
                        f"Modelo: {modelo_usado}"
                    )

                except ValueError as erro:
                    st.error(str(erro))

                except requests.RequestException as erro:
                    st.error(
                        "Falha de conexão: "
                        + type(erro).__name__
                    )

            if st.button(
                "🔎 Segunda opinião: Pl@ntNet",
                use_container_width=True
            ):
                try:
                    with st.spinner(
                        "Consultando Pl@ntNet..."
                    ):
                        resultados = consultar_plantnet(foto)

                    st.session_state[
                        "opiniao_plantnet"
                    ] = resultados

                except (
                    ValueError,
                    requests.RequestException
                ) as erro:
                    st.error(str(erro))

            diagnostico = st.session_state.get(
                "diagnostico_gemini"
            )

            if diagnostico:
                with st.expander(
                    "🔧 Diagnóstico dos modelos Gemini"
                ):
                    for tentativa in diagnostico:
                        st.write(
                            f"**{tentativa['modelo']}**: "
                            f"{tentativa['resultado']}"
                        )

            resultados = st.session_state.get(
                "opiniao_plantnet"
            )

            if resultados is not None:
                with st.expander(
                    "🌿 Resultados do Pl@ntNet",
                    expanded=True
                ):
                    mostrar_resultados_plantnet(
                        foto,
                        resultados
                    )

            ficha = st.session_state.get(
                "ficha_ia"
            )

            if ficha:
                st.divider()
                st.subheader(
                    "🌿 Ficha botânica sugerida"
                )

                if ficha.get("identificacao_incerta"):
                    st.warning(
                        "Identificação incerta. "
                        "Confira antes de confirmar."
                    )

                st.markdown(
                    "**Justificativa da identificação**"
                )

                st.write(
                    ficha.get("justificativa_identificacao")
                    or "Não informada."
                )

                alternativas = (
                    ficha.get("alternativas") or []
                )

                if (
                    isinstance(alternativas, list)
                    and alternativas
                ):
                    st.write(
                        "**Outras possibilidades:** "
                        + ", ".join(
                            str(a) for a in alternativas
                        )
                    )

                inicial = inicial_da_ficha(ficha)

                st.info(
                    "Revise os dados antes de salvar. "
                    "A toxicidade e a raridade não "
                    "devem ser consideradas verificadas "
                    "apenas pela resposta da IA."
                )

                if (
                    st.session_state.get("foto_salva")
                    == assinatura
                ):
                    st.success(
                        "Planta salva no catálogo!"
                    )

                else:
                    ficha_id = hashlib.sha256(
                        json.dumps(
                            ficha,
                            sort_keys=True,
                            ensure_ascii=False
                        ).encode("utf-8")
                    ).hexdigest()[:12]

                    with st.form(
                        f"nova_{assinatura}_{ficha_id}"
                    ):
                        dados = campos_formulario(
                            f"nova_{assinatura[:8]}_{ficha_id}_",
                            inicial
                        )

                        enviado = st.form_submit_button(
                            "💾 Salvar planta",
                            type="primary"
                        )

                    if enviado and validar(dados):
                        salvar(dados, foto)

                        st.session_state[
                            "foto_salva"
                        ] = assinatura

                        st.rerun()

        except (OSError, ValueError) as erro:
            st.error(
                "Erro ao processar fotografia: "
                + str(erro)
            )


# =====================================================
# CATÁLOGO
# =====================================================

with aba_catalogo:
    plantas = plantas_salvas()

    total_catalogo = sum(
        p["status"] == "No catálogo"
        for p in plantas
    )

    total_pendentes = sum(
        p["status"] == "Pendente"
        for p in plantas
    )

    total_arquivadas = sum(
        p["status"] == "Arquivada"
        for p in plantas
    )

    st.markdown(
        "<div class='resumo-jardim'>"

        "<div class='resumo-item'>"
        "<div class='resumo-legenda'>🌿 No catálogo</div>"
        f"<div class='resumo-numero'>{total_catalogo}</div>"
        "</div>"

        "<div class='resumo-item'>"
        "<div class='resumo-legenda'>🟡 Pendentes</div>"
        f"<div class='resumo-numero'>{total_pendentes}</div>"
        "</div>"

        "<div class='resumo-item'>"
        "<div class='resumo-legenda'>📦 Arquivadas</div>"
        f"<div class='resumo-numero'>{total_arquivadas}</div>"
        "</div>"

        "</div>",
        unsafe_allow_html=True
    )

    st.subheader("Minha coleção")

    busca = st.text_input(
        "🔎 Buscar planta",
        placeholder="Nome popular ou científico"
    )

    colunas_galeria = st.selectbox(
        "Fotos por linha no computador",
        [5, 6, 4, 3],
        index=0
    )

    st.caption(
        "No celular, a galeria é organizada "
        "em duas colunas."
    )

    # =================================================
    # FILTROS COMBINADOS
    # =================================================

    with st.expander(
        "🎛️ Filtrar coleção",
        expanded=True
    ):
        st.caption(
            "Combine os critérios para encontrar "
            "as plantas desejadas."
        )

        filtro_status = st.multiselect(
            "Situação",
            STATUS,
            default=["No catálogo", "Pendente"]
        )

        filtro_luz = st.selectbox(
            "☀️ Luminosidade",
            ["Todas", "Não definida"] + GRUPOS
        )

        filtro_solo = st.selectbox(
            "🌱 Tipo de solo",
            ["Todos"] + SOLOS
        )

        filtro_tox = st.selectbox(
            "🛡️ Toxicidade",
            ["Todas"] + TOXICIDADES
        )

        filtro_raridade = st.selectbox(
            "💎 Raridade",
            ["Todas"] + RARIDADES
        )

        if st.button(
            "Limpar filtros",
            use_container_width=True
        ):
            st.session_state["limpar_filtros"] = True
            st.rerun()

    # Limpeza de filtros é aplicada na próxima
    # execução, antes da criação dos widgets.
    # Os filtros também podem ser alterados
    # individualmente pelo usuário.

    visiveis = []

    for planta in plantas:
        if planta["status"] not in filtro_status:
            continue

        luz = planta.get("grupo") or "Não definida"
        solo = planta.get("solo_tipo") or "Não definido"
        tox = planta.get("toxicidade") or "Não verificada"
        rar = planta.get("raridade") or "Não avaliada"

        if (
            filtro_luz != "Todas"
            and luz != filtro_luz
        ):
            continue

        if (
            filtro_solo != "Todos"
            and solo != filtro_solo
        ):
            continue

        if (
            filtro_tox != "Todas"
            and tox != filtro_tox
        ):
            continue

        if (
            filtro_raridade != "Todas"
            and rar != filtro_raridade
        ):
            continue

        nomes = (
            texto(planta.get("nome_comum"))
            + " "
            + texto(planta.get("nome_cientifico"))
        ).casefold()

        if busca.casefold() not in nomes:
            continue

        visiveis.append(planta)

    st.caption(
        f"{len(visiveis)} planta(s) encontrada(s)"
    )

    # =================================================
    # RELATÓRIOS EM PDF
    # =================================================

    with st.expander(
        "📄 Gerar relatório em PDF",
        expanded=False
    ):
        st.markdown(
            "Escolha o formato e quais plantas "
            "deseja incluir no relatório."
        )

        formato_pdf = st.radio(
            "Formato do relatório",
            [
                "Catálogo resumido",
                "Fichas completas"
            ],
            horizontal=True
        )

        abrangencia_pdf = st.radio(
            "Plantas incluídas",
            [
                "Somente plantas filtradas",
                "Todas as plantas"
            ],
            horizontal=True
        )

        if abrangencia_pdf == "Todas as plantas":
            plantas_pdf = plantas
        else:
            plantas_pdf = visiveis

        st.caption(
            f"O relatório incluirá "
            f"{len(plantas_pdf)} planta(s)."
        )

        if plantas_pdf:
            assinatura_pdf = hashlib.sha256(
                json.dumps(
                    [
                        {
                            "id": p["id"],
                            "nome": p["nome_comum"],
                            "cuidados": p.get("cuidados"),
                            "status": p["status"],
                            "grupo": p.get("grupo"),
                            "solo": p.get("solo_tipo"),
                            "toxicidade": p.get("toxicidade"),
                            "raridade": p.get("raridade")
                        }
                        for p in plantas_pdf
                    ],
                    sort_keys=True,
                    ensure_ascii=False
                ).encode("utf-8")
            ).hexdigest()[:16]

            chave_pdf = (
                formato_pdf,
                abrangencia_pdf,
                assinatura_pdf
            )

            if st.button(
                "Preparar relatório",
                type="primary",
                use_container_width=True
            ):
                try:
                    with st.spinner(
                        "Preparando o PDF..."
                    ):
                        if formato_pdf == "Catálogo resumido":
                            pdf_gerado = gerar_pdf_resumido(
                                plantas_pdf
                            )
                        else:
                            pdf_gerado = gerar_pdf_completo(
                                plantas_pdf
                            )

                    st.session_state["pdf_gerado"] = pdf_gerado
                    st.session_state["pdf_chave"] = chave_pdf

                    st.success(
                        "Relatório preparado!"
                    )

                except Exception as erro:
                    st.error(
                        "Não foi possível gerar o PDF: "
                        + str(erro)
                    )

            if (
                st.session_state.get("pdf_chave")
                == chave_pdf
                and st.session_state.get("pdf_gerado")
            ):
                nome_arquivo = (
                    "meu_jardim_resumido.pdf"
                    if formato_pdf == "Catálogo resumido"
                    else "meu_jardim_fichas.pdf"
                )

                st.download_button(
                    "⬇️ Baixar PDF",
                    data=st.session_state["pdf_gerado"],
                    file_name=nome_arquivo,
                    mime="application/pdf",
                    use_container_width=True
                )

        else:
            st.info(
                "Nenhuma planta selecionada "
                "para o relatório."
            )

    # =================================================
    # GALERIA
    # =================================================

    if not visiveis:
        st.info(
            "Nenhuma planta encontrada."
        )

    with st.container(key="galeria_responsiva"):
        for inicio in range(
            0,
            len(visiveis),
            colunas_galeria
        ):
            linha = visiveis[
                inicio:inicio + colunas_galeria
            ]

            colunas = st.columns(
                colunas_galeria,
                gap="small"
            )

            for coluna, planta in zip(
                colunas,
                linha
            ):
                with coluna:
                    cartao_compacto(planta)

    st.caption(
        "Clique em 'Ver ficha' para ampliar "
        "a fotografia e consultar ou editar "
        "os cuidados da planta."
    )
