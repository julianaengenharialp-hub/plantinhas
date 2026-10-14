
import base64
import hashlib
import io
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime
from html import escape

import requests
import streamlit as st
from PIL import Image, ImageOps, ImageChops, ImageStat
from supabase import create_client

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, Image as PDFImage,
    PageBreak, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="Meu Jardim",
    page_icon="🪴",
    layout="wide"
)

API_GEMINI = "https://generativelanguage.googleapis.com/v1beta"
BUCKET = "fotos-plantas"

GRUPOS = ["Sol pleno", "Luz indireta", "Pouca luz"]
SOLOS = [
    "Bem drenado", "Orgânico", "Úmido",
    "Arenoso", "Outro", "Não definido"
]
TOXICIDADES = [
    "Não verificada",
    "Potencialmente tóxica",
    "Tóxica",
    "Sem toxicidade conhecida"
]
RARIDADES = ["Não avaliada", "Comum", "Incomum", "Rara"]
STATUS = ["Pendente", "No catálogo", "Arquivada"]

PREFERIDOS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash"
]

CAMPOS_PLANTA = [
    "nome_comum", "nome_cientifico", "familia",
    "grupo", "solo_tipo", "toxicidade",
    "raridade", "justificativa_raridade",
    "status", "observacoes", "cuidados"
]


# ============================================================
# ESTILO
# ============================================================

st.markdown("""
<style>
.resumo-jardim {
    display: grid;
    grid-template-columns: repeat(3, minmax(0,1fr));
    gap: 10px;
    margin: 12px 0 24px;
}
.resumo-item {
    border: 1px solid rgba(128,128,128,.25);
    border-radius: 12px;
    padding: 12px 6px;
    text-align: center;
}
.resumo-numero {
    font-size: 30px;
    font-weight: 700;
}
.resumo-legenda {
    font-size: 12px;
}
.nome-planta {
    font-size: 12px;
    font-weight: 650;
    text-align: center;
    min-height: 35px;
    overflow-wrap: anywhere;
}
.simbolos-planta {
    font-size: 17px;
    text-align: center;
    white-space: nowrap;
    margin: 5px 0;
}
@media(max-width:700px) {
    .resumo-jardim {gap: 5px;}
    .resumo-numero {font-size: 25px;}
    .resumo-legenda {font-size: 10px;}
    [class*="st-key-galeria_responsiva"]
    [data-testid="stHorizontalBlock"] {
        flex-direction: row !important;
        flex-wrap: wrap !important;
        gap: 8px !important;
    }
    [class*="st-key-galeria_responsiva"]
    [data-testid="column"] {
        flex: 0 0 calc(50% - 4px) !important;
        width: calc(50% - 4px) !important;
        min-width: 0 !important;
    }
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# SUPABASE
# ============================================================

@st.cache_resource
def cliente_supabase():
    url = st.secrets.get("SUPABASE_URL")
    chave = st.secrets.get("SUPABASE_KEY")

    if not url or not chave:
        raise RuntimeError(
            "Configure SUPABASE_URL e SUPABASE_KEY "
            "nos Secrets do Streamlit."
        )

    return create_client(url, chave)


def testar_conexao():
    cliente_supabase().table("plantas").select(
        "id"
    ).limit(1).execute()


def listar_plantas():
    cliente = cliente_supabase()
    registros = []
    inicio = 0
    tamanho = 500

    while True:
        resposta = (
            cliente.table("plantas")
            .select("*")
            .order("id", desc=True)
            .range(inicio, inicio + tamanho - 1)
            .execute()
        )

        lote = resposta.data or []
        registros.extend(lote)

        if len(lote) < tamanho:
            break

        inicio += tamanho

    return registros


def criar_planta(dados, foto):
    cliente = cliente_supabase()
    caminho = f"{uuid.uuid4().hex}.jpg"

    # Primeiro envia a foto para o bucket privado.
    cliente.storage.from_(BUCKET).upload(
        path=caminho,
        file=foto,
        file_options={
            "content-type": "image/jpeg",
            "upsert": "false"
        }
    )

    registro = {
        campo: dados.get(campo)
        for campo in CAMPOS_PLANTA
    }
    registro["imagem_path"] = caminho

    try:
        cliente.table("plantas").insert(
            registro
        ).execute()

    except Exception:
        # Evita foto órfã se o cadastro falhar.
        try:
            cliente.storage.from_(BUCKET).remove(
                [caminho]
            )
        except Exception:
            pass
        raise


def atualizar_planta(id_, dados):
    registro = {
        campo: dados.get(campo)
        for campo in CAMPOS_PLANTA
    }

    cliente_supabase().table("plantas").update(
        registro
    ).eq("id", id_).execute()


def excluir_planta(planta):
    cliente = cliente_supabase()

    # Exclui primeiro o registro. Se a exclusão
    # da foto falhar, o cadastro não reaparece.
    cliente.table("plantas").delete().eq(
        "id", planta["id"]
    ).execute()

    caminho = planta.get("imagem_path")

    if caminho:
        try:
            cliente.storage.from_(BUCKET).remove(
                [caminho]
            )
        except Exception:
            st.warning(
                "O cadastro foi excluído, mas não foi "
                "possível remover a fotografia do Storage."
            )


@st.cache_data(
    show_spinner=False,
    ttl=600,
    max_entries=400
)
def baixar_foto(caminho):
    if not caminho:
        return None

    try:
        return cliente_supabase().storage.from_(
            BUCKET
        ).download(caminho)
    except Exception:
        return None


def foto_da_planta(planta):
    return baixar_foto(
        planta.get("imagem_path")
    )


def limpar_cache_fotos():
    baixar_foto.clear()


# ============================================================
# TRATAMENTO DE IMAGENS
# ============================================================

def tratar_foto(arquivo):
    imagem = Image.open(arquivo)
    imagem = ImageOps.exif_transpose(imagem)
    imagem = imagem.convert("RGB")
    imagem.thumbnail((1200, 1200))

    buffer = io.BytesIO()
    imagem.save(
        buffer, format="JPEG", quality=82
    )
    return buffer.getvalue()


@st.cache_data(show_spinner=False, max_entries=300)
def imagem_quadrada(foto):
    imagem = Image.open(io.BytesIO(foto))
    imagem = ImageOps.exif_transpose(imagem)
    imagem = imagem.convert("RGB")

    imagem = ImageOps.fit(
        imagem,
        (400, 400),
        method=Image.Resampling.LANCZOS
    )

    buffer = io.BytesIO()
    imagem.save(
        buffer, format="JPEG", quality=85
    )
    return buffer.getvalue()


def imagem_comparacao(foto):
    imagem = Image.open(io.BytesIO(foto))
    imagem = ImageOps.exif_transpose(imagem)
    imagem = imagem.convert("RGB")

    return ImageOps.fit(
        imagem, (96, 96),
        method=Image.Resampling.LANCZOS
    )


def imagens_iguais(foto1, foto2):
    try:
        a = imagem_comparacao(foto1)
        b = imagem_comparacao(foto2)
        diferenca = ImageChops.difference(a, b)
        medias = ImageStat.Stat(diferenca).mean
        return sum(medias) / len(medias) < 8
    except Exception:
        return False


# ============================================================
# GEMINI: DESCOBERTA AUTOMÁTICA DE MODELOS
# ============================================================

def chave_gemini():
    chave = st.secrets.get("GEMINI_API_KEY")
    if not chave:
        raise ValueError(
            "GEMINI_API_KEY não encontrada nos Secrets."
        )
    return chave


def mensagem_erro(resposta):
    try:
        mensagem = resposta.json().get(
            "error", {}
        ).get("message", "")
    except Exception:
        mensagem = "Erro não detalhado."

    chave = st.secrets.get("GEMINI_API_KEY", "")

    if chave:
        mensagem = mensagem.replace(
            chave, "[CHAVE OCULTA]"
        )

    return (
        f"HTTP {resposta.status_code}: "
        f"{mensagem[:300]}"
    )


def modelo_elegivel(nome):
    nome = nome.lower()

    if not nome.startswith("gemini-"):
        return False

    excluidos = [
        "image", "tts", "audio", "transcribe",
        "omni", "robotics", "computer-use",
        "nano-banana", "customtools"
    ]

    if any(x in nome for x in excluidos):
        return False

    if "pro" in nome:
        return False

    return "flash" in nome or "lite" in nome


@st.cache_data(show_spinner=False, ttl=3600)
def descobrir_modelos():
    encontrados = []
    pagina = None

    while True:
        parametros = {"pageSize": 1000}

        if pagina:
            parametros["pageToken"] = pagina

        resposta = requests.get(
            API_GEMINI + "/models",
            headers={
                "x-goog-api-key": chave_gemini()
            },
            params=parametros,
            timeout=30
        )

        if not resposta.ok:
            raise ValueError(
                "Erro ao consultar modelos: "
                + mensagem_erro(resposta)
            )

        corpo = resposta.json()

        for item in corpo.get("models", []):
            metodos = item.get(
                "supportedGenerationMethods"
            ) or []

            nome = item.get("name", "").replace(
                "models/", "", 1
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

    encontrados.sort(
        key=lambda nome: (
            0, PREFERIDOS.index(nome)
        ) if nome in PREFERIDOS else (1, nome)
    )

    return encontrados


def modelos_ordenados():
    modelos = descobrir_modelos().copy()

    ultimo = st.session_state.get(
        "modelo_gemini_funcionando"
    )

    if ultimo in modelos:
        modelos.remove(ultimo)
        modelos.insert(0, ultimo)

    return modelos


def prompt_botanico(rejeitadas=None):
    prompt = """
Analise a fotografia e gere uma ficha botânica
em português brasileiro.

Retorne APENAS um objeto JSON válido com:
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

Valores permitidos:
grupo: "Sol pleno", "Luz indireta",
"Pouca luz" ou "".

solo_tipo: "Bem drenado", "Orgânico",
"Úmido", "Arenoso", "Outro",
"Não definido".

toxicidade: "Não verificada",
"Potencialmente tóxica", "Tóxica",
"Sem toxicidade conhecida".

raridade: "Não avaliada", "Comum",
"Incomum", "Rara".

Regras:
- Use apenas características observáveis.
- Não invente certeza nem porcentagens.
- Se não for possível distinguir espécies,
  informe identificacao_incerta=true.
- Justifique a identificação.
- Descreva rega, luminosidade, solo,
  crescimento, porte, propagação,
  adubação e problemas comuns.
- Tenha cuidado especial com toxicidade
  para cães, gatos e coelhos.
- Não confunda ausência de dados sobre
  toxicidade com segurança comprovada.
- Raridade significa frequência no
  cultivo ornamental, não ameaça de extinção.
- Se não houver fundamento para avaliar
  raridade, use "Não avaliada".
- Não afirme ter consultado fontes externas.
"""

    if rejeitadas:
        historico = json.dumps(
            rejeitadas[-10:],
            ensure_ascii=False
        )

        prompt += f"""

REAVALIAÇÃO:
O usuário rejeitou identificações anteriores.

Histórico:
{historico}

Reexamine as características da imagem.
Considere os motivos de rejeição.
Procure outras hipóteses compatíveis.
Não apresente espécie rejeitada como
identificação confirmada.
Não invente uma espécie alternativa apenas
para produzir uma resposta diferente.
Se a imagem for insuficiente, informe
a incerteza e explique quais detalhes
fotográficos seriam necessários.
"""

    return prompt


def consultar_modelo(foto, modelo, rejeitadas):
    payload = {
        "contents": [{
            "parts": [
                {
                    "text": prompt_botanico(rejeitadas)
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
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 4096
        }
    }

    try:
        resposta = requests.post(
            f"{API_GEMINI}/models/{modelo}:generateContent",
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
            type(erro).__name__,
            False
        )

    if not resposta.ok:
        return (
            None,
            mensagem_erro(resposta),
            resposta.status_code in (401, 403, 429)
        )

    try:
        corpo = resposta.json()
        candidatos = corpo.get("candidates") or []

        if not candidatos:
            return None, "Sem candidatos.", False

        partes = candidatos[0].get(
            "content", {}
        ).get("parts", [])

        conteudo = "".join(
            parte.get("text", "")
            for parte in partes
        )

        ficha = json.loads(conteudo)

        if not isinstance(ficha, dict):
            raise ValueError("JSON inválido")

        if not (
            ficha.get("nome_comum")
            or ficha.get("nome_cientifico")
        ):
            raise ValueError("Identificação vazia")

        return ficha, None, False

    except (ValueError, TypeError, KeyError):
        return None, "Ficha inválida ou incompleta.", False


def nome_normalizado(nome):
    nome = unicodedata.normalize(
        "NFKD", str(nome or "")
    )
    nome = "".join(
        c for c in nome
        if not unicodedata.combining(c)
    )
    return " ".join(nome.casefold().split())


def identificacao_repetida(ficha, rejeitadas):
    nome = nome_normalizado(
        ficha.get("nome_cientifico")
        or ficha.get("nome_comum")
    )

    return any(
        nome == nome_normalizado(
            r.get("nome_cientifico")
            or r.get("nome_comum")
        )
        for r in rejeitadas
    )


def identificar_automaticamente(foto, rejeitadas=None):
    rejeitadas = rejeitadas or []
    modelos = modelos_ordenados()

    if not modelos:
        raise ValueError(
            "Nenhum modelo Gemini Flash compatível encontrado."
        )

    tentativas = []
    progresso = st.progress(0)
    aviso = st.empty()

    try:
        for indice, modelo in enumerate(modelos, 1):
            aviso.info(
                f"Consultando Gemini {indice}/{len(modelos)}: "
                f"{modelo}"
            )

            ficha, erro, interromper = consultar_modelo(
                foto, modelo, rejeitadas
            )

            progresso.progress(
                indice / len(modelos)
            )

            if ficha is not None:
                if identificacao_repetida(
                    ficha, rejeitadas
                ):
                    tentativas.append({
                        "modelo": modelo,
                        "resultado": "Identificação já rejeitada"
                    })
                    continue

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
        aviso.empty()

    st.session_state[
        "diagnostico_gemini"
    ] = tentativas

    raise ValueError(
        "Não foi possível obter uma nova identificação. "
        "Se a imagem não mostrar detalhes suficientes, "
        "tente outra fotografia."
    )


# ============================================================
# PLANTNET
# ============================================================

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
                "planta.jpg", foto, "image/jpeg"
            )
        },
        data={"organs": "auto"},
        timeout=60
    )

    if not resposta.ok:
        raise ValueError(
            f"Pl@ntNet: HTTP {resposta.status_code}"
        )

    return resposta.json().get("results", [])


def urls_referencia(resultado):
    encontradas = []

    for imagem in resultado.get("images") or []:
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
                and url not in encontradas
            ):
                encontradas.append(url)

    return encontradas


@st.cache_data(
    show_spinner=False,
    ttl=3600,
    max_entries=150
)
def baixar_referencia(url):
    try:
        resposta = requests.get(
            url, timeout=12,
            headers={"User-Agent": "MeuJardim/1.0"}
        )
        resposta.raise_for_status()

        if not resposta.headers.get(
            "Content-Type", ""
        ).lower().startswith("image/"):
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
            buffer, format="JPEG", quality=85
        )

        return buffer.getvalue()

    except Exception:
        return None


def foto_referencia(resultado, foto_usuario):
    for url in urls_referencia(resultado)[:8]:
        imagem = baixar_referencia(url)

        if imagem is None:
            continue

        if imagens_iguais(imagem, foto_usuario):
            continue

        return imagem

    return None


def mostrar_plantnet(foto, resultados):
    st.subheader("Segunda opinião do Pl@ntNet")

    if not resultados:
        st.info("Nenhuma sugestão encontrada.")
        return

    st.image(
        foto, width=250,
        caption="Sua fotografia"
    )

    for indice, resultado in enumerate(
        resultados[:5], 1
    ):
        especie = resultado.get("species") or {}

        nome = (
            especie.get("scientificNameWithoutAuthor")
            or especie.get("scientificName")
            or "Espécie não informada"
        )

        comuns = especie.get("commonNames") or []
        score = float(resultado.get("score") or 0)

        with st.container(border=True):
            st.markdown(f"**{indice}. {nome}**")

            if comuns:
                st.caption(comuns[0])

            st.write(
                f"Correspondência: {score * 100:.1f}%"
            )

            referencia = foto_referencia(
                resultado, foto
            )

            if referencia:
                st.image(
                    referencia,
                    width=250,
                    caption="Fotografia de referência"
                )

    st.caption(
        "A correspondência não representa "
        "confirmação definitiva da espécie."
    )


# ============================================================
# FORMULÁRIOS E FICHAS
# ============================================================

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
        titulo + "\n"
        + (texto(ficha.get(chave)) or "Não informado.")
        for titulo, chave in secoes
    )


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
        "nome_cientifico": texto(
            ficha.get("nome_cientifico")
        ),
        "familia": texto(ficha.get("familia")),
        "grupo": escolha(
            ficha.get("grupo"), GRUPOS, ""
        ),
        "solo_tipo": escolha(
            ficha.get("solo_tipo"),
            SOLOS, "Não definido"
        ),
        "toxicidade": escolha(
            ficha.get("toxicidade"),
            TOXICIDADES, "Não verificada"
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

    c1, c2 = st.columns(2)

    with c1:
        opcoes_luz = ["Não definida"] + GRUPOS
        luz_atual = escolha(
            inicial.get("grupo"),
            GRUPOS, "Não definida"
        )

        luz = st.selectbox(
            "☀️ Luminosidade",
            opcoes_luz,
            index=opcoes_luz.index(luz_atual),
            key=prefixo + "luz"
        )

        solo_atual = escolha(
            inicial.get("solo_tipo"),
            SOLOS, "Não definido"
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
            TOXICIDADES, "Não verificada"
        )

        toxicidade = st.selectbox(
            "🛡️ Toxicidade",
            TOXICIDADES,
            index=TOXICIDADES.index(tox_atual),
            key=prefixo + "tox"
        )

        rar_atual = escolha(
            inicial.get("raridade"),
            RARIDADES, "Não avaliada"
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
        height=270,
        key=prefixo + "cuidados"
    )

    observacoes = st.text_area(
        "Observações pessoais",
        value=texto(inicial.get("observacoes")),
        key=prefixo + "obs"
    )

    atual = escolha(
        inicial.get("status"),
        STATUS, "Pendente"
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
        "grupo": "" if luz == "Não definida" else luz,
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
        st.error("Informe o nome da planta.")
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
            "Justifique a raridade ou escolha "
            "'Não avaliada'."
        )
        return False

    return True


# ============================================================
# INDICADORES
# ============================================================

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
            "Luz", luz
        ),
        (
            {
                "Bem drenado": "🏜️",
                "Orgânico": "🌱",
                "Úmido": "💧",
                "Arenoso": "⏳"
            }.get(solo, "🪴"),
            "Solo", solo
        ),
        (
            {
                "Não verificada": "❔",
                "Potencialmente tóxica": "⚠️",
                "Tóxica": "☠️",
                "Sem toxicidade conhecida": "🛡️"
            }.get(tox, "❔"),
            "Toxicidade", tox
        ),
        (
            {
                "Não avaliada": "❔",
                "Comum": "🌿",
                "Incomum": "💎",
                "Rara": "✨"
            }.get(rar, "❔"),
            "Raridade", rar
        )
    ]


def indicadores_compactos(planta):
    simbolos = " ".join(
        icone
        for icone, _, _ in dados_indicadores(planta)
    )

    st.markdown(
        "<div class='simbolos-planta'>"
        + simbolos
        + "</div>",
        unsafe_allow_html=True
    )


def indicadores_detalhados(planta):
    partes = []

    for icone, titulo, valor in dados_indicadores(planta):
        partes.append(
            "<div style='text-align:center;min-width:0'>"
            f"<div style='font-size:24px'>{icone}</div>"
            f"<div style='font-size:11px'><b>{escape(titulo)}</b></div>"
            f"<div style='font-size:11px;overflow-wrap:anywhere'>"
            f"{escape(valor)}</div></div>"
        )

    st.markdown(
        "<div style='display:grid;"
        "grid-template-columns:repeat(4,minmax(0,1fr));"
        "gap:5px;margin:15px 0'>"
        + "".join(partes)
        + "</div>",
        unsafe_allow_html=True
    )


# ============================================================
# PDF
# ============================================================

def fontes_pdf():
    candidatos = [
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ),
        (
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        )
    ]

    for regular, negrito in candidatos:
        if os.path.exists(regular) and os.path.exists(negrito):
            if "JardimRegular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(
                    TTFont("JardimRegular", regular)
                )
                pdfmetrics.registerFont(
                    TTFont("JardimBold", negrito)
                )
                pdfmetrics.registerFontFamily(
                    "JardimRegular",
                    normal="JardimRegular",
                    bold="JardimBold"
                )
            return "JardimRegular", "JardimBold"

    return "Helvetica", "Helvetica-Bold"


def estilos_pdf():
    regular, negrito = fontes_pdf()

    return {
        "titulo": ParagraphStyle(
            "JardimTitulo",
            fontName=negrito,
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#244D36"),
            spaceAfter=9
        ),
        "nome": ParagraphStyle(
            "JardimNome",
            fontName=negrito,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#244D36"),
            spaceAfter=4
        ),
        "corpo": ParagraphStyle(
            "JardimCorpo",
            fontName=regular,
            fontSize=9,
            leading=14,
            spaceAfter=6
        ),
        "pequeno": ParagraphStyle(
            "JardimPequeno",
            fontName=regular,
            fontSize=7.5,
            leading=11
        ),
        "secao": ParagraphStyle(
            "JardimSecao",
            fontName=negrito,
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#244D36"),
            spaceBefore=9,
            spaceAfter=4
        )
    }


def ptexto(valor):
    return escape(texto(valor)).replace(
        "\n", "<br/>"
    )


def imagem_pdf(foto, largura, altura):
    if not foto:
        return Spacer(1, altura)

    try:
        imagem = Image.open(io.BytesIO(foto))
        imagem = ImageOps.exif_transpose(imagem)
        imagem = imagem.convert("RGB")
        imagem.thumbnail((900, 900))

        iw, ih = imagem.size
        escala = min(largura / iw, altura / ih)

        buffer = io.BytesIO()
        imagem.save(
            buffer, format="JPEG", quality=85
        )
        buffer.seek(0)

        figura = PDFImage(
            buffer,
            width=iw * escala,
            height=ih * escala
        )
        figura.hAlign = "CENTER"
        return figura

    except Exception:
        return Spacer(1, altura)


def rodape_pdf(canvas, doc):
    canvas.saveState()
    largura, _ = A4

    canvas.setStrokeColor(
        colors.HexColor("#DDDDDD")
    )
    canvas.line(
        16 * mm, 15 * mm,
        largura - 16 * mm, 15 * mm
    )

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(
        colors.HexColor("#666666")
    )

    canvas.drawString(
        16 * mm, 10 * mm,
        "Meu Jardim | Catálogo pessoal"
    )
    canvas.drawRightString(
        largura - 16 * mm, 10 * mm,
        f"Página {doc.page}"
    )
    canvas.restoreState()


def documento_pdf(buffer):
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=17 * mm,
        bottomMargin=21 * mm,
        title="Meu Jardim",
        author="Meu Jardim"
    )


def cabecalho_pdf(estilos, titulo, quantidade):
    return [
        Paragraph(ptexto(titulo), estilos["titulo"]),
        Paragraph(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            f" | {quantidade} planta(s)",
            estilos["pequeno"]
        ),
        Spacer(1, 12)
    ]


def cartao_pdf_resumido(planta, estilos):
    foto = foto_da_planta(planta)

    itens = [
        imagem_pdf(foto, 47 * mm, 43 * mm),
        Spacer(1, 5),
        Paragraph(
            ptexto(planta.get("nome_comum") or "Sem nome"),
            estilos["nome"]
        ),
        Paragraph(
            ptexto(
                planta.get("nome_cientifico")
                or "Nome científico não informado"
            ),
            estilos["pequeno"]
        ),
        Spacer(1, 5)
    ]

    for titulo, campo, padrao in [
        ("Luz", "grupo", "Não definida"),
        ("Solo", "solo_tipo", "Não definido"),
        ("Toxicidade", "toxicidade", "Não verificada"),
        ("Raridade", "raridade", "Não avaliada")
    ]:
        itens.append(
            Paragraph(
                f"<b>{ptexto(titulo)}:</b> "
                f"{ptexto(planta.get(campo) or padrao)}",
                estilos["pequeno"]
            )
        )

    tabela = Table(
        [[itens]],
        colWidths=[53 * mm]
    )

    tabela.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), .5, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm)
    ]))

    return tabela


def gerar_pdf_resumido(plantas):
    buffer = io.BytesIO()
    estilos = estilos_pdf()
    elementos = cabecalho_pdf(
        estilos,
        "Meu Jardim | Catálogo resumido",
        len(plantas)
    )

    cartoes = [
        cartao_pdf_resumido(p, estilos)
        for p in plantas
    ]

    # Uma linha por tabela permite que o ReportLab
    # distribua as linhas entre páginas.
    for inicio in range(0, len(cartoes), 3):
        linha = cartoes[inicio:inicio + 3]
        linha += [""] * (3 - len(linha))

        tabela = Table(
            [linha],
            colWidths=[59 * mm] * 3,
            hAlign="CENTER"
        )

        tabela.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm)
        ]))

        elementos.append(tabela)

    documento_pdf(buffer).build(
        elementos,
        onFirstPage=rodape_pdf,
        onLaterPages=rodape_pdf
    )

    return buffer.getvalue()


def tabela_dados_pdf(planta, estilos):
    campos = [
        ("Nome popular", "nome_comum"),
        ("Nome científico", "nome_cientifico"),
        ("Família", "familia"),
        ("Luminosidade", "grupo"),
        ("Tipo de solo", "solo_tipo"),
        ("Toxicidade", "toxicidade"),
        ("Raridade", "raridade"),
        ("Situação", "status")
    ]

    linhas = []

    for titulo, campo in campos:
        linhas.append([
            Paragraph(
                f"<b>{ptexto(titulo)}</b>",
                estilos["pequeno"]
            ),
            Paragraph(
                ptexto(
                    planta.get(campo) or "Não informado"
                ),
                estilos["pequeno"]
            )
        ])

    tabela = Table(
        linhas,
        colWidths=[39 * mm, 137 * mm]
    )

    tabela.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        (
            "LINEBELOW", (0, 0), (-1, -1),
            .3, colors.HexColor("#E5E5E5")
        ),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5)
    ]))

    return tabela


def gerar_pdf_completo(plantas):
    buffer = io.BytesIO()
    estilos = estilos_pdf()
    elementos = []

    for indice, planta in enumerate(plantas):
        if indice:
            elementos.append(PageBreak())

        elementos.extend(
            cabecalho_pdf(
                estilos, "Ficha botânica",
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

        foto = foto_da_planta(planta)

        if foto:
            elementos.append(
                imagem_pdf(
                    foto, 90 * mm, 65 * mm
                )
            )
            elementos.append(Spacer(1, 8))

        elementos.append(
            tabela_dados_pdf(planta, estilos)
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

        for bloco in cuidados.split("\n\n"):
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
                    ptexto(planta["observacoes"]),
                    estilos["corpo"]
                )
            )

        elementos.append(
            Paragraph(
                "Identificações e cuidados gerados por IA "
                "exigem verificação, especialmente "
                "quanto à toxicidade.",
                estilos["pequeno"]
            )
        )

    documento_pdf(buffer).build(
        elementos,
        onFirstPage=rodape_pdf,
        onLaterPages=rodape_pdf
    )

    return buffer.getvalue()


# ============================================================
# GALERIA E EDIÇÃO
# ============================================================

@st.dialog("🌿 Ficha da planta", width="large")
def abrir_ficha(planta):
    st.subheader(planta["nome_comum"])

    if planta.get("nome_cientifico"):
        st.caption(planta["nome_cientifico"])

    st.caption(
        f"Situação: {planta['status']}"
    )

    foto = foto_da_planta(planta)

    if foto:
        st.image(
            foto, use_container_width=True
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
        st.write(planta["observacoes"])

    with st.expander("✏️ Editar planta"):
        with st.form(f"editar_{planta['id']}"):
            dados = campos_formulario(
                f"edit_{planta['id']}_",
                planta
            )

            gravar = st.form_submit_button(
                "💾 Salvar alterações",
                type="primary"
            )

        if gravar and validar(dados):
            try:
                atualizar_planta(
                    planta["id"], dados
                )
                st.rerun()
            except Exception as erro:
                st.error(
                    "Erro ao atualizar a planta: "
                    + str(erro)
                )

    with st.expander("🗑️ Excluir planta"):
        st.warning("A exclusão é definitiva.")

        confirmar = st.checkbox(
            "Confirmo que desejo excluir esta planta",
            key=f"confirmar_{planta['id']}"
        )

        if st.button(
            "Excluir definitivamente",
            key=f"excluir_{planta['id']}",
            disabled=not confirmar
        ):
            try:
                excluir_planta(planta)
                limpar_cache_fotos()
                st.rerun()
            except Exception as erro:
                st.error(
                    "Erro ao excluir: " + str(erro)
                )


def cartao_compacto(planta):
    with st.container(border=True):
        foto = foto_da_planta(planta)

        if foto:
            try:
                st.image(
                    imagem_quadrada(foto),
                    use_container_width=True
                )
            except Exception:
                st.caption("Imagem indisponível")
        else:
            st.caption("Sem fotografia")

        st.markdown(
            "<div class='nome-planta'>"
            + escape(
                texto(planta.get("nome_comum"))
            )
            + "</div>",
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


# ============================================================
# ESTADO DA IDENTIFICAÇÃO
# ============================================================

def reiniciar_analise(assinatura):
    if st.session_state.get("foto_id") == assinatura:
        return

    st.session_state["foto_id"] = assinatura

    for chave in [
        "ficha_ia",
        "opiniao_plantnet",
        "foto_salva",
        "diagnostico_gemini",
        "identificacoes_rejeitadas",
        "numero_tentativa",
        "erro_reidentificacao",
        "motivo_rejeicao"
    ]:
        st.session_state.pop(chave, None)

    st.session_state["identificacoes_rejeitadas"] = []
    st.session_state["numero_tentativa"] = 0


def realizar_identificacao(foto, rejeitadas=None):
    ficha, modelo = identificar_automaticamente(
        foto, rejeitadas
    )

    st.session_state["ficha_ia"] = ficha
    st.session_state["numero_tentativa"] = (
        st.session_state.get("numero_tentativa", 0) + 1
    )
    st.session_state.pop("foto_salva", None)
    st.session_state.pop("erro_reidentificacao", None)

    return modelo


def rejeitar_identificacao(ficha, motivo):
    rejeitadas = st.session_state.setdefault(
        "identificacoes_rejeitadas", []
    )

    rejeitadas.append({
        "nome_comum": texto(
            ficha.get("nome_comum")
        ),
        "nome_cientifico": texto(
            ficha.get("nome_cientifico")
        ),
        "motivo": motivo.strip()
    })


# ============================================================
# INÍCIO DO APLICATIVO
# ============================================================

st.title("🪴 Meu Jardim")
st.caption("Seu catálogo pessoal de plantas")

try:
    testar_conexao()
except Exception as erro:
    st.error(
        "Não foi possível conectar ao Supabase."
    )
    with st.expander("Detalhes técnicos"):
        st.code(str(erro))
    st.stop()

aba_identificar, aba_catalogo = st.tabs([
    "📸 Identificar planta",
    "🌿 Meu catálogo"
])


# ============================================================
# IDENTIFICAR PLANTA
# ============================================================

with aba_identificar:
    modelo_ativo = st.session_state.get(
        "modelo_gemini_funcionando"
    )

    if modelo_ativo:
        st.caption(
            "Gemini automático • Último modelo "
            f"funcional: {modelo_ativo}"
        )
    else:
        st.caption(
            "Gemini automático • Seleção automática "
            "de modelo compatível"
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

            reiniciar_analise(assinatura)

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
                        modelo = realizar_identificacao(
                            foto,
                            st.session_state.get(
                                "identificacoes_rejeitadas", []
                            )
                        )

                    st.success(
                        f"Ficha gerada! Modelo: {modelo}"
                    )
                except Exception as erro:
                    st.error(str(erro))

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

                except Exception as erro:
                    st.error(str(erro))

            diagnostico = st.session_state.get(
                "diagnostico_gemini"
            )

            if diagnostico:
                with st.expander(
                    "🔧 Diagnóstico do Gemini"
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
                    mostrar_plantnet(
                        foto, resultados
                    )

            rejeitadas = st.session_state.get(
                "identificacoes_rejeitadas", []
            )

            if rejeitadas:
                with st.expander(
                    f"📋 Identificações descartadas "
                    f"({len(rejeitadas)})"
                ):
                    for indice, item in enumerate(
                        rejeitadas, 1
                    ):
                        nome = (
                            item["nome_cientifico"]
                            or item["nome_comum"]
                        )

                        st.write(
                            f"**{indice}. {nome}**"
                        )

                        if item.get("motivo"):
                            st.caption(
                                "Motivo: " + item["motivo"]
                            )

            ficha = st.session_state.get("ficha_ia")

            if ficha:
                st.divider()
                st.subheader("🌿 Ficha botânica sugerida")

                st.markdown(
                    "**Espécie sugerida:** "
                    + texto(
                        ficha.get("nome_cientifico")
                        or ficha.get("nome_comum")
                    )
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

                alternativas = ficha.get(
                    "alternativas"
                ) or []

                if isinstance(alternativas, list) and alternativas:
                    st.write(
                        "**Outras possibilidades:** "
                        + ", ".join(map(str, alternativas))
                    )

                # ------------------------------------
                # REFAZER IDENTIFICAÇÃO
                # ------------------------------------

                with st.container(border=True):
                    st.markdown(
                        "**Não corresponde à sua planta?**"
                    )

                    motivo = st.text_area(
                        "O que não corresponde? (opcional)",
                        placeholder=(
                            "Ex.: Minha planta tem folhas "
                            "mais estreitas."
                        ),
                        key="motivo_rejeicao",
                        height=80
                    )

                    if st.button(
                        "🔄 Não é esta planta? "
                        "Refazer identificação",
                        use_container_width=True
                    ):
                        rejeitar_identificacao(
                            ficha, motivo
                        )

                        st.session_state.pop(
                            "ficha_ia", None
                        )

                        try:
                            with st.spinner(
                                "Procurando outra identificação..."
                            ):
                                realizar_identificacao(
                                    foto,
                                    st.session_state[
                                        "identificacoes_rejeitadas"
                                    ]
                                )

                            st.session_state[
                                "motivo_rejeicao"
                            ] = ""

                            st.rerun()

                        except Exception as erro:
                            st.session_state[
                                "erro_reidentificacao"
                            ] = str(erro)
                            st.rerun()

                st.info(
                    "Revise os dados antes de salvar. "
                    "A toxicidade e a raridade exigem "
                    "verificação."
                )

                if (
                    st.session_state.get("foto_salva")
                    == assinatura
                ):
                    st.success(
                        "Planta salva no Supabase!"
                    )

                else:
                    inicial = inicial_da_ficha(ficha)

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
                        try:
                            with st.spinner(
                                "Salvando no Supabase..."
                            ):
                                criar_planta(dados, foto)

                            st.session_state[
                                "foto_salva"
                            ] = assinatura

                            st.rerun()

                        except Exception as erro:
                            st.error(
                                "Erro ao salvar: " + str(erro)
                            )

            erro_reidentificacao = st.session_state.get(
                "erro_reidentificacao"
            )

            if erro_reidentificacao:
                st.warning(
                    "Não foi possível encontrar outra "
                    "identificação: "
                    + erro_reidentificacao
                )

                if st.button(
                    "🔄 Tentar novamente",
                    use_container_width=True
                ):
                    try:
                        with st.spinner(
                            "Reavaliando a fotografia..."
                        ):
                            realizar_identificacao(
                                foto,
                                st.session_state.get(
                                    "identificacoes_rejeitadas", []
                                )
                            )

                        st.rerun()

                    except Exception as erro:
                        st.session_state[
                            "erro_reidentificacao"
                        ] = str(erro)
                        st.rerun()

        except (OSError, ValueError) as erro:
            st.error(
                "Erro ao processar fotografia: "
                + str(erro)
            )


# ============================================================
# CATÁLOGO
# ============================================================

with aba_catalogo:
    try:
        plantas = listar_plantas()
    except Exception as erro:
        st.error(
            "Não foi possível consultar o catálogo: "
            + str(erro)
        )
        st.stop()

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

    if st.session_state.pop(
        "limpar_filtros", False
    ):
        st.session_state["filtro_busca"] = ""
        st.session_state["filtro_status"] = [
            "No catálogo", "Pendente"
        ]
        st.session_state["filtro_luz"] = "Todas"
        st.session_state["filtro_solo"] = "Todos"
        st.session_state["filtro_tox"] = "Todas"
        st.session_state["filtro_raridade"] = "Todas"

    busca = st.text_input(
        "🔎 Buscar planta",
        placeholder="Nome popular ou científico",
        key="filtro_busca"
    )

    colunas_galeria = st.selectbox(
        "Fotos por linha no computador",
        [5, 6, 4, 3],
        index=0
    )

    st.caption(
        "No celular, a galeria utiliza duas colunas."
    )

    with st.expander(
        "🎛️ Filtrar coleção",
        expanded=True
    ):
        filtro_status = st.multiselect(
            "Situação",
            STATUS,
            default=["No catálogo", "Pendente"],
            key="filtro_status"
        )

        filtro_luz = st.selectbox(
            "☀️ Luminosidade",
            ["Todas", "Não definida"] + GRUPOS,
            key="filtro_luz"
        )

        filtro_solo = st.selectbox(
            "🌱 Tipo de solo",
            ["Todos"] + SOLOS,
            key="filtro_solo"
        )

        filtro_tox = st.selectbox(
            "🛡️ Toxicidade",
            ["Todas"] + TOXICIDADES,
            key="filtro_tox"
        )

        filtro_raridade = st.selectbox(
            "💎 Raridade",
            ["Todas"] + RARIDADES,
            key="filtro_raridade"
        )

        if st.button(
            "Limpar filtros",
            use_container_width=True
        ):
            st.session_state[
                "limpar_filtros"
            ] = True
            st.rerun()

    visiveis = []

    for planta in plantas:
        if planta["status"] not in filtro_status:
            continue

        luz = planta.get("grupo") or "Não definida"
        solo = planta.get("solo_tipo") or "Não definido"
        tox = planta.get("toxicidade") or "Não verificada"
        rar = planta.get("raridade") or "Não avaliada"

        if filtro_luz != "Todas" and luz != filtro_luz:
            continue

        if filtro_solo != "Todos" and solo != filtro_solo:
            continue

        if filtro_tox != "Todas" and tox != filtro_tox:
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

    # ------------------------------------
    # RELATÓRIOS PDF
    # ------------------------------------

    with st.expander("📄 Gerar relatório em PDF"):
        formato = st.radio(
            "Formato",
            [
                "Catálogo resumido",
                "Fichas completas"
            ],
            horizontal=True
        )

        abrangencia = st.radio(
            "Incluir",
            [
                "Somente plantas filtradas",
                "Todas as plantas"
            ],
            horizontal=True
        )

        plantas_pdf = (
            plantas
            if abrangencia == "Todas as plantas"
            else visiveis
        )

        st.caption(
            f"{len(plantas_pdf)} planta(s) no relatório."
        )

        if plantas_pdf:
            assinatura_pdf = hashlib.sha256(
                json.dumps(
                    plantas_pdf,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str
                ).encode("utf-8")
            ).hexdigest()

            chave_pdf = (
                formato, abrangencia, assinatura_pdf
            )

            if st.button(
                "Preparar relatório",
                type="primary",
                use_container_width=True
            ):
                try:
                    with st.spinner(
                        "Gerando PDF..."
                    ):
                        if formato == "Catálogo resumido":
                            pdf = gerar_pdf_resumido(
                                plantas_pdf
                            )
                        else:
                            pdf = gerar_pdf_completo(
                                plantas_pdf
                            )

                    st.session_state[
                        "pdf_gerado"
                    ] = pdf

                    st.session_state[
                        "pdf_chave"
                    ] = chave_pdf

                    st.success(
                        "Relatório preparado!"
                    )

                except Exception as erro:
                    st.error(
                        "Erro ao gerar PDF: " + str(erro)
                    )

            if (
                st.session_state.get("pdf_chave")
                == chave_pdf
                and st.session_state.get("pdf_gerado")
            ):
                nome_pdf = (
                    "meu_jardim_resumido.pdf"
                    if formato == "Catálogo resumido"
                    else "meu_jardim_fichas.pdf"
                )

                st.download_button(
                    "⬇️ Baixar PDF",
                    data=st.session_state[
                        "pdf_gerado"
                    ],
                    file_name=nome_pdf,
                    mime="application/pdf",
                    use_container_width=True
                )

        else:
            st.info(
                "Nenhuma planta selecionada."
            )

    # ------------------------------------
    # GALERIA
    # ------------------------------------

    if not visiveis:
        st.info(
            "Seu catálogo está vazio ou nenhuma "
            "planta corresponde aos filtros."
        )

    with st.container(
        key="galeria_responsiva"
    ):
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
                colunas, linha
            ):
                with coluna:
                    cartao_compacto(planta)

    st.caption(
        "As fichas e fotografias são armazenadas "
        "no Supabase."
    )
