
import base64
import hashlib
import io
import json
import re
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
API = "https://generativelanguage.googleapis.com/v1beta"

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


# ============================================================
# BANCO
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

        existentes = {
            r["name"] for r in con.execute(
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
            dict(r) for r in con.execute(
                "SELECT * FROM catalogo_v04 ORDER BY id DESC"
            )
        ]


# ============================================================
# IMAGEM
# ============================================================

def tratar_foto(arquivo):
    imagem = Image.open(arquivo).convert("RGB")
    imagem.thumbnail((1200, 1200))

    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=82)

    return buffer.getvalue()


# ============================================================
# GEMINI AUTOMÁTICO
# ============================================================

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
            chave, "[CHAVE OCULTA]"
        )

    return f"HTTP {resposta.status_code}: {mensagem[:350]}"


def modelo_elegivel(nome):
    """
    Mantém modelos de texto multimodal,
    excluindo modalidades especializadas.
    """

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

    # Os modelos Flash são preferidos para o
    # uso gratuito. Pro fica fora da varredura
    # automática para evitar modelos sem cota.
    if "pro" in nome:
        return False

    return (
        "flash" in nome
        or "lite" in nome
    )


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
                "Não foi possível consultar modelos: "
                + texto_erro(resposta)
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
- Informe cuidados de luminosidade, rega,
  substrato, crescimento, porte adulto,
  propagação, adubação e problemas comuns.
- Não invente dados de toxicidade.
- Diferencie cães, gatos e coelhos e declare
  quando a segurança não for conhecida.
- "Não verificada" não significa não tóxica.
- Raridade significa frequência no cultivo
  ornamental brasileiro, não ameaça de extinção.
- Não confunda aparência exótica com raridade.
- Se não houver fundamento para a raridade,
  use "Não avaliada".
- Não afirme ter consultado fontes externas.
- Não preencha lacunas com afirmações inventadas.
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
        return None, (
            "Falha de conexão: "
            + type(erro).__name__
        ), False

    if not resposta.ok:
        codigo = resposta.status_code

        # Erros de cota/autenticação interrompem
        # a varredura para proteger o projeto.
        interromper = codigo in (401, 403, 429)

        return (
            None,
            texto_erro(resposta),
            interromper
        )

    try:
        retorno = resposta.json()
        candidatos = retorno.get("candidates") or []

        if not candidatos:
            return (
                None,
                "Resposta sem candidatos.",
                False
            )

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
                "A resposta não é um objeto JSON.",
                False
            )

        if not (
            ficha.get("nome_comum")
            or ficha.get("nome_cientifico")
        ):
            return (
                None,
                "Ficha sem identificação botânica.",
                False
            )

        return ficha, None, False

    except (ValueError, TypeError, KeyError):
        return (
            None,
            "Resposta recebida, mas ficha inválida "
            "ou incompleta.",
            False
        )


def identificar_automaticamente(foto):
    modelos = listar_modelos_elegiveis()

    if not modelos:
        raise ValueError(
            "Nenhum modelo Gemini Flash compatível "
            "foi anunciado para esta chave."
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
                foto, modelo
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

    ultimo = tentativas[-1] if tentativas else {}

    raise ValueError(
        "Nenhum modelo conseguiu gerar a ficha. "
        f"Foram realizadas {len(tentativas)} tentativa(s). "
        "Consulte o diagnóstico abaixo. "
        "Último resultado: "
        + str(ultimo.get("resultado", "Desconhecido"))
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
            f"Pl@ntNet retornou HTTP "
            f"{resposta.status_code}."
        )

    return resposta.json().get("results", [])


# ============================================================
# FICHAS E FORMULÁRIOS
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
            ficha.get("grupo"), GRUPOS, ""
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


# ============================================================
# CATÁLOGO VISUAL
# ============================================================

def indicador(icone, titulo, valor):
    st.markdown(
        "<div style='text-align:center;"
        "min-height:85px'>"
        f"<div style='font-size:25px'>{icone}</div>"
        f"<div style='font-size:11px;font-weight:600'>"
        f"{titulo}</div>"
        f"<div style='font-size:11px'>{valor}</div>"
        "</div>",
        unsafe_allow_html=True
    )


def cartao_planta(planta):
    id_ = planta["id"]

    with st.container(border=True):
        if planta.get("imagem"):
            st.image(
                planta["imagem"],
                use_container_width=True
            )

        st.markdown(
            f"**{planta['nome_comum']}**"
        )

        st.caption(
            texto(planta.get("nome_cientifico"))
            or "Identificação pendente"
        )

        st.caption(
            "🟡 Pendente"
            if planta["status"] == "Pendente"
            else (
                "📦 Arquivada"
                if planta["status"] == "Arquivada"
                else "🌿 No catálogo"
            )
        )

        luz = planta.get("grupo") or "Não definida"
        solo = planta.get("solo_tipo") or "Não definido"
        tox = planta.get("toxicidade") or "Não verificada"
        rar = planta.get("raridade") or "Não avaliada"

        colunas = st.columns(4, gap="small")

        with colunas[0]:
            indicador(
                {
                    "Sol pleno": "☀️",
                    "Luz indireta": "🌤️",
                    "Pouca luz": "🌥️"
                }.get(luz, "❔"),
                "LUZ", luz
            )

        with colunas[1]:
            indicador(
                {
                    "Bem drenado": "🏜️",
                    "Orgânico": "🌱",
                    "Úmido": "💧",
                    "Arenoso": "⏳"
                }.get(solo, "🪴"),
                "SOLO", solo
            )

        with colunas[2]:
            indicador(
                {
                    "Não verificada": "❔",
                    "Potencialmente tóxica": "⚠️",
                    "Tóxica": "☠️",
                    "Sem toxicidade conhecida": "🛡️"
                }.get(tox, "❔"),
                "TOXIC.", tox
            )

        with colunas[3]:
            indicador(
                {
                    "Não avaliada": "❔",
                    "Comum": "🌿",
                    "Incomum": "💎",
                    "Rara": "✨"
                }.get(rar, "❔"),
                "RARIDADE", rar
            )

        with st.expander("📖 Ficha completa"):
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
                st.markdown("**Observações**")
                st.write(planta["observacoes"])

        with st.expander("✏️ Editar planta"):
            with st.form(f"editar_{id_}"):
                dados = campos_formulario(
                    f"edit_{id_}_",
                    planta
                )

                gravar = st.form_submit_button(
                    "💾 Salvar alterações"
                )

            if gravar and validar(dados):
                atualizar(id_, dados)
                st.rerun()

            confirmar = st.checkbox(
                "Confirmo a exclusão definitiva",
                key=f"confirmar_{id_}"
            )

            if st.button(
                "Excluir planta",
                key=f"excluir_{id_}",
                disabled=not confirmar
            ):
                excluir(id_)
                st.rerun()


# ============================================================
# APLICATIVO
# ============================================================

preparar_banco()

st.title("🪴 Meu Jardim")
st.caption("Seu catálogo pessoal de plantas")

st.warning(
    "O armazenamento ainda é provisório. "
    "Os registros podem ser perdidos quando "
    "o Streamlit Cloud reiniciar."
)

aba_identificar, aba_catalogo = st.tabs([
    "📸 Identificar planta",
    "🌿 Meu catálogo"
])


# ============================================================
# IDENTIFICAR
# ============================================================

with aba_identificar:
    modelo_ativo = st.session_state.get(
        "modelo_gemini_funcionando"
    )

    if modelo_ativo:
        st.caption(
            f"Gemini automático • "
            f"Último modelo funcional: {modelo_ativo}"
        )
    else:
        st.caption(
            "Gemini automático • O aplicativo "
            "selecionará um modelo compatível."
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

            col_foto, col_acoes = st.columns([1, 1])

            with col_foto:
                st.image(
                    foto,
                    use_container_width=True
                )

            with col_acoes:
                st.subheader("Análise da fotografia")

                if st.button(
                    "✨ Gerar ficha automaticamente",
                    type="primary",
                    use_container_width=True
                ):
                    try:
                        with st.spinner(
                            "Procurando um modelo Gemini "
                            "compatível e analisando a planta..."
                        ):
                            ficha, modelo_usado = (
                                identificar_automaticamente(foto)
                            )

                        st.session_state["ficha_ia"] = ficha
                        st.session_state.pop(
                            "foto_salva", None
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
                    "Segunda opinião do Pl@ntNet",
                    expanded=True
                ):
                    if not resultados:
                        st.info(
                            "Nenhuma sugestão encontrada."
                        )

                    for item in resultados[:5]:
                        especie = item.get("species") or {}

                        nome = (
                            especie.get(
                                "scientificNameWithoutAuthor"
                            )
                            or especie.get("scientificName")
                            or "Não informado"
                        )

                        score = float(
                            item.get("score") or 0
                        )

                        st.write(
                            f"*{nome}* • "
                            f"score: {score * 100:.1f}%"
                        )

                    st.caption(
                        "O score não confirma a espécie."
                    )

            ficha = st.session_state.get("ficha_ia")

            if ficha:
                st.divider()
                st.subheader("🌿 Ficha botânica sugerida")

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


# ============================================================
# CATÁLOGO
# ============================================================

with aba_catalogo:
    plantas = plantas_salvas()

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "🌿 No catálogo",
        sum(
            p["status"] == "No catálogo"
            for p in plantas
        )
    )

    c2.metric(
        "🟡 Pendentes",
        sum(
            p["status"] == "Pendente"
            for p in plantas
        )
    )

    c3.metric(
        "📦 Arquivadas",
        sum(
            p["status"] == "Arquivada"
            for p in plantas
        )
    )

    st.subheader("Minha coleção")

    busca = st.text_input(
        "🔎 Buscar planta",
        placeholder="Nome popular ou científico"
    )

    with st.expander("🎛️ Filtrar coleção"):
        f1, f2 = st.columns(2)

        with f1:
            filtro_status = st.multiselect(
                "Situação",
                STATUS,
                default=["No catálogo", "Pendente"]
            )

            filtro_luz = st.selectbox(
                "Luminosidade",
                ["Todas", "Não definida"] + GRUPOS
            )

        with f2:
            filtro_solo = st.selectbox(
                "Tipo de solo",
                ["Todos"] + SOLOS
            )

            filtro_tox = st.selectbox(
                "Toxicidade",
                ["Todas"] + TOXICIDADES
            )

        filtro_raridade = st.selectbox(
            "Raridade",
            ["Todas"] + RARIDADES
        )

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

    if not visiveis:
        st.info(
            "Nenhuma planta encontrada."
        )

    for inicio in range(0, len(visiveis), 2):
        colunas = st.columns(2, gap="medium")

        for coluna, planta in zip(
            colunas,
            visiveis[inicio:inicio + 2]
        ):
            with coluna:
                cartao_planta(planta)

    st.caption(
        "Os indicadores resumem informações "
        "editáveis. 'Não verificada' não significa "
        "segura para animais. Raridade refere-se "
        "ao cultivo ornamental, não à conservação."
    )
