
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
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

GRUPOS = ["Sol pleno", "Luz indireta", "Pouca luz"]
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
STATUS = ["Pendente", "No catálogo", "Arquivada"]

ICONES_LUZ = {
    "Sol pleno": "☀️",
    "Luz indireta": "🌤️",
    "Pouca luz": "🌥️"
}

ICONES_SOLO = {
    "Bem drenado": "🏜️",
    "Orgânico": "🌱",
    "Úmido": "💧",
    "Arenoso": "⏳",
    "Outro": "🪴",
    "Não definido": "❔"
}

ICONES_TOXICIDADE = {
    "Não verificada": "❔",
    "Potencialmente tóxica": "⚠️",
    "Tóxica": "☠️",
    "Sem toxicidade conhecida": "🛡️"
}

ICONES_RARIDADE = {
    "Não avaliada": "❔",
    "Comum": "🌿",
    "Incomum": "💎",
    "Rara": "✨"
}


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

        colunas = {
            row["name"]
            for row in con.execute(
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
            if nome not in colunas:
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
            UPDATE catalogo_v04
            SET nome_comum=?, nome_cientifico=?,
                familia=?, grupo=?, status=?,
                observacoes=?, cuidados=?,
                solo_tipo=?, toxicidade=?,
                raridade=?, justificativa_raridade=?
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


def obter_plantas():
    with conectar() as con:
        return [
            dict(p)
            for p in con.execute(
                "SELECT * FROM catalogo_v04 ORDER BY id DESC"
            )
        ]


# =====================================================
# FOTOGRAFIA
# =====================================================

def tratar_foto(arquivo):
    imagem = Image.open(arquivo).convert("RGB")
    imagem.thumbnail((1200, 1200))

    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=82)
    return buffer.getvalue()


# =====================================================
# GEMINI
# =====================================================

def chave_gemini():
    chave = st.secrets.get("GEMINI_API_KEY")
    if not chave:
        raise ValueError(
            "GEMINI_API_KEY não encontrada nos Secrets."
        )
    return chave


def diagnosticar_erro_gemini(resposta):
    try:
        erro = resposta.json().get("error", {})
        mensagem = erro.get(
            "message",
            "O Google não forneceu detalhes."
        )
        status = erro.get("status", "Não informado")
    except (ValueError, AttributeError):
        mensagem = "Resposta não estruturada do servidor."
        status = "Não informado"

    # Evita exibir uma chave caso apareça na mensagem.
    chave = st.secrets.get("GEMINI_API_KEY", "")
    if chave:
        mensagem = mensagem.replace(chave, "[CHAVE OCULTA]")

    return (
        f"HTTP {resposta.status_code}\n"
        f"Status: {status}\n\n"
        f"Mensagem original do Google:\n{mensagem}"
    )


def listar_modelos():
    resposta = requests.get(
        GEMINI_BASE + "/models",
        headers={"x-goog-api-key": chave_gemini()},
        params={"pageSize": 1000},
        timeout=30
    )

    if not resposta.ok:
        raise ValueError(
            diagnosticar_erro_gemini(resposta)
        )

    return [
        m["name"].replace("models/", "", 1)
        for m in resposta.json().get("models", [])
        if "generateContent" in (
            m.get("supportedGenerationMethods") or []
        )
        and m.get("name", "").startswith("models/gemini")
    ]


def gerar_ficha_gemini(foto, modelo):
    instrucao = """
Analise a fotografia desta planta para um catálogo
doméstico brasileiro.

Responda SOMENTE com um objeto JSON válido com os campos:

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

grupo:
"Sol pleno", "Luz indireta", "Pouca luz" ou "".

solo_tipo:
"Bem drenado", "Orgânico", "Úmido",
"Arenoso", "Outro", "Não definido".

toxicidade:
"Não verificada", "Potencialmente tóxica",
"Tóxica", "Sem toxicidade conhecida".

raridade:
"Não avaliada", "Comum", "Incomum", "Rara".

REGRAS IMPORTANTES:

1. Identifique a espécie com prudência. Se a foto
não permitir distinguir espécies semelhantes,
marque identificacao_incerta=true.

2. Não invente percentuais de confiança.

3. Explique as características visíveis que
fundamentam a identificação.

4. Classifique a luminosidade considerando as
necessidades de cultivo, não apenas tolerância.

5. Informe rega, substrato, crescimento, porte,
propagação, adubação e problemas comuns.
Se não souber, diga que não foi possível determinar.

6. Para toxicidade, não invente dados. Diferencie
cães, gatos e coelhos na explicação. A ausência
de informações não comprova segurança.

7. Use "Sem toxicidade conhecida" somente se
houver fundamento confiável. Caso contrário,
use "Não verificada".

8. Raridade significa frequência aproximada da
espécie no cultivo ornamental brasileiro, NÃO
risco de extinção ou estado de conservação.

9. Não confunda aparência exótica com raridade.
Na dúvida, use "Não avaliada".

10. Não afirme ter consultado fontes externas.

11. Responda em português do Brasil.
"""

    payload = {
        "contents": [{
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
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 4096
        }
    }

    resposta = requests.post(
        f"{GEMINI_BASE}/models/{modelo}:generateContent",
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
    candidatos = retorno.get("candidates") or []

    if not candidatos:
        raise ValueError(
            "Gemini não retornou uma identificação."
        )

    candidato = candidatos[0]
    partes = candidato.get("content", {}).get("parts", [])

    texto = "".join(
        p.get("text", "") for p in partes
    )

    if not texto.strip():
        raise ValueError(
            "Gemini não retornou texto. Motivo: "
            + str(candidato.get("finishReason", "Desconhecido"))
        )

    try:
        ficha = json.loads(texto)
    except json.JSONDecodeError:
        raise ValueError(
            "Gemini retornou uma ficha incompleta ou inválida."
        )

    if not isinstance(ficha, dict):
        raise ValueError("Formato de ficha inválido.")

    return ficha


# =====================================================
# PLANTNET
# =====================================================

def consultar_plantnet(foto):
    chave = st.secrets.get("PLANTNET_API_KEY")

    if not chave:
        raise ValueError(
            "PLANTNET_API_KEY não encontrada nos Secrets."
        )

    resposta = requests.post(
        "https://my-api.plantnet.org/v2/identify/all",
        params={"api-key": chave, "lang": "pt"},
        files={
            "images": ("planta.jpg", foto, "image/jpeg")
        },
        data={"organs": "auto"},
        timeout=60
    )

    if not resposta.ok:
        raise ValueError(
            f"Pl@ntNet retornou HTTP {resposta.status_code}."
        )

    return resposta.json().get("results", [])


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
            texto(ficha.get(chave)) or "Não informado."
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
        grupo_atual = escolha(
            inicial.get("grupo"),
            GRUPOS,
            "Não definida"
        )
        opcoes_luz = ["Não definida"] + GRUPOS

        grupo = st.selectbox(
            "☀️ Luminosidade",
            opcoes_luz,
            index=opcoes_luz.index(grupo_atual),
            key=prefixo + "grupo"
        )

        solo_atual = escolha(
            inicial.get("solo_tipo"),
            SOLOS,
            "Não definido"
        )

        solo = st.selectbox(
            "🌱 Tipo de solo",
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
            key=prefixo + "toxicidade"
        )

        rar_atual = escolha(
            inicial.get("raridade"),
            RARIDADES,
            "Não avaliada"
        )

        raridade = st.selectbox(
            "💎 Raridade no cultivo",
            RARIDADES,
            index=RARIDADES.index(rar_atual),
            key=prefixo + "raridade"
        )

    justificativa = st.text_area(
        "Justificativa da raridade",
        value=texto(
            inicial.get("justificativa_raridade")
        ),
        height=75,
        key=prefixo + "raridade_just"
    )

    cuidados = st.text_area(
        "Ficha completa de cuidados",
        value=texto(inicial.get("cuidados")),
        height=300,
        key=prefixo + "cuidados"
    )

    observacoes = st.text_area(
        "Observações pessoais",
        value=texto(inicial.get("observacoes")),
        height=90,
        key=prefixo + "observacoes"
    )

    status_atual = escolha(
        inicial.get("status"),
        STATUS,
        "Pendente"
    )

    status = st.selectbox(
        "Situação",
        STATUS,
        index=STATUS.index(status_atual),
        key=prefixo + "status"
    )

    return {
        "nome_comum": nome.strip(),
        "nome_cientifico": cientifico.strip(),
        "familia": familia.strip(),
        "grupo": "" if grupo == "Não definida" else grupo,
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
            "Para classificar a raridade, informe "
            "uma justificativa ou escolha Não avaliada."
        )
        return False

    return True


def indicador(icone, titulo, valor):
    st.markdown(
        f"<div style='text-align:center; min-height:76px;'>"
        f"<div style='font-size:26px'>{icone}</div>"
        f"<div style='font-size:11px; font-weight:600;'>"
        f"{titulo}</div>"
        f"<div style='font-size:11px; opacity:.8;'>"
        f"{valor}</div>"
        f"</div>",
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
            or "Identificação científica pendente"
        )

        if planta["status"] == "Pendente":
            st.caption("🟡 Identificação pendente")
        elif planta["status"] == "Arquivada":
            st.caption("📦 Arquivada")
        else:
            st.caption("🌿 No catálogo")

        grupo = planta.get("grupo") or "Não definida"
        solo = planta.get("solo_tipo") or "Não definido"
        tox = planta.get("toxicidade") or "Não verificada"
        rar = planta.get("raridade") or "Não avaliada"

        st.divider()

        colunas = st.columns(4, gap="small")

        with colunas[0]:
            indicador(
                ICONES_LUZ.get(grupo, "❔"),
                "LUZ",
                grupo
            )

        with colunas[1]:
            indicador(
                ICONES_SOLO.get(solo, "❔"),
                "SOLO",
                solo
            )

        with colunas[2]:
            indicador(
                ICONES_TOXICIDADE.get(tox, "❔"),
                "TOXIC.",
                tox
            )

        with colunas[3]:
            indicador(
                ICONES_RARIDADE.get(rar, "❔"),
                "RARIDADE",
                rar
            )

        with st.expander("📖 Ver ficha completa"):
            st.markdown("**Cuidados e cultivo**")
            st.text(
                texto(planta.get("cuidados"))
                or "Ficha ainda não preenchida."
            )

            if planta.get("justificativa_raridade"):
                st.markdown("**Raridade**")
                st.write(
                    planta["justificativa_raridade"]
                )

            if planta.get("observacoes"):
                st.markdown("**Minhas observações**")
                st.write(planta["observacoes"])

            st.caption(
                "As informações geradas por IA devem "
                "ser verificadas, especialmente "
                "as relativas à toxicidade."
            )

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

            st.divider()

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


# =====================================================
# INICIALIZAÇÃO
# =====================================================

preparar_banco()

st.title("🪴 Meu Jardim")
st.caption(
    "Seu catálogo pessoal de plantas"
)

st.warning(
    "O armazenamento ainda é provisório. "
    "Registros podem ser perdidos quando "
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
    with st.expander("⚙️ Configuração do Gemini"):
        modelo = st.text_input(
            "Modelo Gemini",
            value="gemini-3.1-flash-lite",
            key="modelo_gemini"
        ).strip()

        if st.button("Consultar modelos disponíveis"):
            try:
                with st.spinner("Consultando Google..."):
                    modelos = listar_modelos()

                st.code("\n".join(modelos))

                st.caption(
                    "A listagem não garante acesso "
                    "ou cota gratuita."
                )
            except (
                ValueError,
                requests.RequestException
            ) as erro:
                st.error(str(erro))

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
                    "foto_salva"
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
                    "✨ Gerar ficha com Gemini",
                    type="primary",
                    use_container_width=True
                ):
                    if not modelo:
                        st.error("Informe um modelo Gemini.")
                    else:
                        try:
                            with st.spinner(
                                "Preparando sua ficha botânica..."
                            ):
                                ficha = gerar_ficha_gemini(
                                    foto,
                                    modelo
                                )

                            st.session_state["ficha_ia"] = ficha
                            st.session_state.pop(
                                "foto_salva",
                                None
                            )

                        except ValueError as erro:
                            st.error("Falha no Gemini.")
                            st.code(
                                str(erro),
                                language="text"
                            )

                        except requests.RequestException as erro:
                            st.error(
                                "Falha de conexão com o Gemini."
                            )
                            st.caption(type(erro).__name__)

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

            resultados = st.session_state.get(
                "opiniao_plantnet"
            )

            if resultados is not None:
                with st.expander(
                    "Segunda opinião do Pl@ntNet",
                    expanded=True
                ):
                    if not resultados:
                        st.info("Nenhum resultado encontrado.")

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
                        "O score não garante "
                        "identificação correta."
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

                alternativas = ficha.get("alternativas") or []

                if isinstance(alternativas, list) and alternativas:
                    st.write(
                        "**Outras possibilidades:** "
                        + ", ".join(
                            str(a) for a in alternativas
                        )
                    )

                grupo = escolha(
                    ficha.get("grupo"),
                    GRUPOS,
                    ""
                )

                solo = escolha(
                    ficha.get("solo_tipo"),
                    SOLOS,
                    "Não definido"
                )

                tox = escolha(
                    ficha.get("toxicidade"),
                    TOXICIDADES,
                    "Não verificada"
                )

                rar = escolha(
                    ficha.get("raridade"),
                    RARIDADES,
                    "Não avaliada"
                )

                justificativa_raridade = texto(
                    ficha.get("justificativa_raridade")
                )

                if (
                    rar != "Não avaliada"
                    and not justificativa_raridade.strip()
                ):
                    rar = "Não avaliada"

                inicial = {
                    "nome_comum": (
                        ficha.get("nome_comum")
                        or "Planta a identificar"
                    ),
                    "nome_cientifico": (
                        ficha.get("nome_cientifico") or ""
                    ),
                    "familia": ficha.get("familia") or "",
                    "grupo": grupo,
                    "solo_tipo": solo,
                    "toxicidade": tox,
                    "raridade": rar,
                    "justificativa_raridade": (
                        justificativa_raridade
                    ),
                    "cuidados": montar_cuidados(ficha),
                    "observacoes": "",
                    "status": (
                        "Pendente"
                        if ficha.get("identificacao_incerta")
                        else "No catálogo"
                    )
                }

                st.info(
                    "Revise os indicadores e a ficha "
                    "antes de salvar. A classificação "
                    "de raridade é aproximada, e a "
                    "toxicidade exige confirmação."
                )

                if (
                    st.session_state.get("foto_salva")
                    == assinatura
                ):
                    st.success("Planta salva no catálogo!")

                else:
                    # Uma nova identificação cria
                    # um formulário com chaves próprias.
                    ficha_id = hashlib.sha256(
                        json.dumps(
                            ficha,
                            sort_keys=True,
                            ensure_ascii=False
                        ).encode("utf-8")
                    ).hexdigest()[:12]

                    with st.form(
                        f"nova_planta_{assinatura}_{ficha_id}"
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
                f"Não foi possível processar "
                f"a fotografia: {erro}"
            )


# =====================================================
# CATÁLOGO VISUAL
# =====================================================

with aba_catalogo:
    plantas = obter_plantas()

    cadastradas = sum(
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
    c1.metric("🌿 No catálogo", cadastradas)
    c2.metric("🟡 Pendentes", pendentes)
    c3.metric("📦 Arquivadas", arquivadas)

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

    for p in plantas:
        if p["status"] not in filtro_status:
            continue

        grupo = p.get("grupo") or "Não definida"
        solo = p.get("solo_tipo") or "Não definido"
        tox = p.get("toxicidade") or "Não verificada"
        rar = p.get("raridade") or "Não avaliada"

        if filtro_luz != "Todas" and grupo != filtro_luz:
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
            texto(p.get("nome_comum"))
            + " "
            + texto(p.get("nome_cientifico"))
        ).casefold()

        if busca.casefold() not in nomes:
            continue

        visiveis.append(p)

    st.caption(
        f"{len(visiveis)} planta(s) encontrada(s)"
    )

    if not visiveis:
        st.info(
            "Nenhuma planta encontrada para "
            "os filtros selecionados."
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
        "Legenda: os indicadores resumem informações "
        "revisáveis da ficha. 'Não verificada' não "
        "significa que a planta seja segura para animais. "
        "A raridade se refere ao cultivo ornamental, "
        "não ao risco de extinção."
    )
