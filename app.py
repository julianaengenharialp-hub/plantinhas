
# Meu Catálogo de Plantas - versão 0.4
# Armazenamento local provisório

import io
import sqlite3
import hashlib
from datetime import datetime

import requests
import streamlit as st
from PIL import Image

st.set_page_config(
    page_title="Meu Catálogo de Plantas",
    page_icon="🪴",
    layout="centered"
)

DB = "plantas.db"
GRUPOS = ["Sol pleno", "Luz indireta", "Pouca luz"]
STATUS = ["Pendente", "No catálogo", "Arquivada"]


def conectar():
    conexao = sqlite3.connect(DB, timeout=20)
    conexao.row_factory = sqlite3.Row
    return conexao


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
            (nome_comum, nome_cientifico, familia, grupo,
             score, status, local, observacoes, cuidados,
             imagem, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            dados["nome_comum"],
            dados["nome_cientifico"],
            dados["familia"],
            dados["grupo"],
            dados["score"],
            dados["status"],
            dados["local"],
            dados["observacoes"],
            dados["cuidados"],
            foto,
            datetime.now().strftime("%d/%m/%Y %H:%M")
        ))


def atualizar(id_, dados):
    with conectar() as con:
        con.execute("""
            UPDATE catalogo_v04
            SET nome_comum=?, nome_cientifico=?,
                familia=?, grupo=?, status=?,
                local=?, observacoes=?, cuidados=?
            WHERE id=?
        """, (
            dados["nome_comum"],
            dados["nome_cientifico"],
            dados["familia"],
            dados["grupo"],
            dados["status"],
            dados["local"],
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


def identificar(imagem_bytes):
    try:
        chave = st.secrets["PLANTNET_API_KEY"]
    except (KeyError, FileNotFoundError):
        raise ValueError(
            "Chave PLANTNET_API_KEY não encontrada "
            "nos Secrets do Streamlit."
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
                imagem_bytes,
                "image/jpeg"
            )
        },
        data={"organs": "auto"},
        timeout=60
    )

    if resposta.status_code == 429:
        raise ValueError(
            "Limite de identificações atingido. "
            "Tente novamente mais tarde."
        )

    if resposta.status_code in (401, 403):
        raise ValueError(
            "A chave Pl@ntNet foi recusada. "
            "Verifique os Secrets."
        )

    if resposta.status_code >= 500:
        raise ValueError(
            "Pl@ntNet temporariamente indisponível."
        )

    if not resposta.ok:
        raise ValueError(
            f"Pl@ntNet retornou erro "
            f"{resposta.status_code}: "
            f"{resposta.text[:250]}"
        )

    resultados = resposta.json().get("results", [])

    if not resultados:
        raise ValueError(
            "Nenhuma identificação encontrada. "
            "Tente outra fotografia."
        )

    return resultados


def texto_taxon(taxon):
    if isinstance(taxon, dict):
        return (
            taxon.get("scientificNameWithoutAuthor")
            or taxon.get("scientificName")
            or ""
        )
    return str(taxon or "")


def campos_formulario(prefixo, inicial):
    nome = st.text_input(
        "Nome comum",
        value=inicial.get("nome_comum", ""),
        key=prefixo + "nome"
    )

    cientifico = st.text_input(
        "Nome científico",
        value=inicial.get("nome_cientifico", ""),
        key=prefixo + "cientifico"
    )

    familia = st.text_input(
        "Família botânica",
        value=inicial.get("familia", ""),
        key=prefixo + "familia"
    )

    grupo_atual = inicial.get("grupo", "")
    opcoes = ["Não definido"] + GRUPOS

    grupo = st.selectbox(
        "Grupo de luminosidade",
        opcoes,
        index=(
            opcoes.index(grupo_atual)
            if grupo_atual in opcoes else 0
        ),
        key=prefixo + "grupo"
    )

    local = st.text_input(
        "Local na casa (opcional)",
        value=inicial.get("local", ""),
        key=prefixo + "local"
    )

    cuidados = st.text_area(
        "Cuidados verificados por você (opcional)",
        value=inicial.get("cuidados", ""),
        key=prefixo + "cuidados"
    )

    observacoes = st.text_area(
        "Observações pessoais (opcional)",
        value=inicial.get("observacoes", ""),
        key=prefixo + "observacoes"
    )

    status_atual = inicial.get("status", "Pendente")

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
        "grupo": "" if grupo == "Não definido" else grupo,
        "local": local.strip(),
        "cuidados": cuidados.strip(),
        "observacoes": observacoes.strip(),
        "status": status,
        "score": inicial.get("score")
    }


# INICIALIZAÇÃO

preparar_banco()

st.title("🪴 Meu Catálogo de Plantas")

st.caption(
    "Versão 0.4 • Identificação Pl@ntNet"
)

st.warning(
    "Os cadastros desta versão usam armazenamento "
    "local provisório e podem ser perdidos quando "
    "o Streamlit reiniciar. Utilize para testes."
)

aba_identificar, aba_catalogo, aba_pendentes, aba_arquivadas = st.tabs([
    "📸 Identificar",
    "🪴 Catálogo",
    "⏳ Pendentes",
    "📦 Arquivadas"
])


# ABA IDENTIFICAR

with aba_identificar:

    origem = st.radio(
        "Como deseja enviar a fotografia?",
        ["Carregar do dispositivo", "Tirar foto"]
    )

    if origem == "Carregar do dispositivo":
        arquivo = st.file_uploader(
            "Escolha uma fotografia",
            type=["jpg", "jpeg", "png"]
        )
    else:
        arquivo = st.camera_input(
            "Fotografe a planta"
        )

    if arquivo is not None:

        try:
            imagem = Image.open(arquivo)
            imagem.thumbnail((1600, 1600))

            if imagem.mode != "RGB":
                imagem = imagem.convert("RGB")

            buffer = io.BytesIO()
            imagem.save(
                buffer,
                format="JPEG",
                quality=85
            )

            foto = buffer.getvalue()

            st.image(
                foto,
                caption="Fotografia selecionada",
                use_container_width=True
            )

            assinatura = hashlib.sha256(
                foto
            ).hexdigest()

            if st.session_state.get(
                "assinatura_foto"
            ) != assinatura:

                st.session_state[
                    "assinatura_foto"
                ] = assinatura

                st.session_state.pop(
                    "resultados_plantnet", None
                )

                st.session_state.pop(
                    "salvo_assinatura", None
                )

            if st.button(
                "🔎 Identificar planta",
                type="primary"
            ):

                try:
                    with st.spinner(
                        "Identificando com Pl@ntNet..."
                    ):
                        st.session_state[
                            "resultados_plantnet"
                        ] = identificar(foto)

                    st.session_state.pop(
                        "salvo_assinatura", None
                    )

                except (
                    requests.RequestException,
                    ValueError
                ) as erro:
                    st.error(str(erro))

            resultados = st.session_state.get(
                "resultados_plantnet"
            )

            if resultados:

                principal = resultados[0]
                especie = principal.get("species") or {}
                nomes = especie.get("commonNames") or []

                score = float(
                    principal.get("score") or 0
                )

                st.subheader(
                    "Identificação sugerida"
                )

                st.write(
                    f"**{nomes[0] if nomes else 'Nome comum não informado'}**"
                )

                nome_cientifico = texto_taxon(
                    especie.get("scientificNameWithoutAuthor")
                    or especie.get("scientificName")
                )

                st.write(f"*{nome_cientifico}*")

                st.progress(
                    max(0.0, min(score, 1.0))
                )

                st.write(
                    f"Score Pl@ntNet: **{score * 100:.1f}%**"
                )

                st.caption(
                    "O score é uma medida de compatibilidade "
                    "do Pl@ntNet, não uma garantia de acerto."
                )

                if len(resultados) > 1:

                    with st.expander(
                        "Outras identificações possíveis"
                    ):

                        for item in resultados[1:5]:

                            sp = item.get("species") or {}

                            nome_alt = texto_taxon(
                                sp.get("scientificNameWithoutAuthor")
                                or sp.get("scientificName")
                            )

                            score_alt = float(
                                item.get("score") or 0
                            )

                            st.write(
                                f"{nome_alt} • "
                                f"{score_alt * 100:.1f}%"
                            )

                if st.session_state.get(
                    "salvo_assinatura"
                ) == assinatura:

                    st.success(
                        "Planta salva! Confira a aba "
                        "correspondente."
                    )

                else:

                    st.info(
                        "Revise os dados antes de salvar. "
                        "O Pl@ntNet não fornece orientações "
                        "de cultivo nem classifica os três "
                        "grupos de luminosidade."
                    )

                    inicial = {
                        "nome_comum": (
                            nomes[0] if nomes else ""
                        ),
                        "nome_cientifico": nome_cientifico,
                        "familia": texto_taxon(
                            especie.get("family")
                        ),
                        "score": score,
                        "status": "Pendente"
                    }

                    with st.form("cadastro_nova_planta"):

                        dados = campos_formulario(
                            "nova_", inicial
                        )

                        enviado = st.form_submit_button(
                            "💾 Salvar planta"
                        )

                    if enviado:

                        if not dados["nome_comum"]:

                            st.error(
                                "Informe um nome comum "
                                "ou provisório."
                            )

                        elif (
                            dados["status"] == "No catálogo"
                            and not dados["grupo"]
                        ):

                            st.error(
                                "Selecione o grupo de "
                                "luminosidade para incluir "
                                "a planta no catálogo."
                            )

                        else:

                            salvar(dados, foto)

                            st.session_state[
                                "salvo_assinatura"
                            ] = assinatura

                            st.rerun()

        except (OSError, ValueError) as erro:

            st.error(
                f"Não foi possível processar "
                f"a fotografia: {erro}"
            )


# CONSULTA AO BANCO

with conectar() as con:
    registros = [
        dict(r)
        for r in con.execute(
            "SELECT * FROM catalogo_v04 "
            "ORDER BY id DESC"
        ).fetchall()
    ]


# ABAS DO CATÁLOGO

for aba, situacao in [
    (aba_catalogo, "No catálogo"),
    (aba_pendentes, "Pendente"),
    (aba_arquivadas, "Arquivada")
]:

    with aba:

        st.subheader(
            situacao
            if situacao != "No catálogo"
            else "Minhas plantas"
        )

        selecionados = [
            r for r in registros
            if r["status"] == situacao
        ]

        if situacao == "No catálogo":

            filtro = st.selectbox(
                "Filtrar por luminosidade",
                ["Todos"] + GRUPOS
            )

            if filtro != "Todos":

                selecionados = [
                    r for r in selecionados
                    if r["grupo"] == filtro
                ]

        if not selecionados:
            st.info(
                "Nenhuma planta nesta seção."
            )

        for planta in selecionados:

            with st.expander(
                f"{planta['nome_comum']} • "
                f"{planta['nome_cientifico'] or 'Não identificado'}"
            ):

                if planta["imagem"]:
                    st.image(
                        planta["imagem"],
                        width=250
                    )

                if planta["score"] is not None:

                    st.caption(
                        f"Score original Pl@ntNet: "
                        f"{planta['score'] * 100:.1f}%"
                    )

                st.caption(
                    f"Registrada em {planta['criado_em']}"
                )

                with st.form(
                    f"editar_{planta['id']}"
                ):

                    dados = campos_formulario(
                        f"edit_{planta['id']}_",
                        planta
                    )

                    gravar = st.form_submit_button(
                        "💾 Salvar alterações"
                    )

                if gravar:

                    if not dados["nome_comum"]:

                        st.error(
                            "O nome comum não pode "
                            "ficar vazio."
                        )

                    elif (
                        dados["status"] == "No catálogo"
                        and not dados["grupo"]
                    ):

                        st.error(
                            "Selecione o grupo de "
                            "luminosidade."
                        )

                    else:

                        atualizar(
                            planta["id"],
                            dados
                        )

                        st.rerun()

                st.divider()

                confirmar = st.checkbox(
                    "Confirmo que quero excluir "
                    "esta planta permanentemente",
                    key=f"confirmar_{planta['id']}"
                )

                if st.button(
                    "🗑 Excluir definitivamente",
                    key=f"excluir_{planta['id']}",
                    disabled=not confirmar
                ):

                    excluir(planta["id"])
                    st.rerun()
