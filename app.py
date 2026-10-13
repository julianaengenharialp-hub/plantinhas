
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
            SET nome_comum=?,
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


def identificar(foto):
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

    resultados = resposta.json().get("results", [])

    if not resultados:
        raise ValueError(
            "Nenhuma identificação encontrada."
        )

    return resultados


def taxon(valor):
    if isinstance(valor, dict):
        return (
            valor.get("scientificNameWithoutAuthor")
            or valor.get("scientificName")
            or ""
        )

    return str(valor or "")


def pesquisar_perenual(nome):
    chave = st.secrets.get("PERENUAL_API_KEY")

    if not chave:
        raise ValueError(
            "PERENUAL_API_KEY não encontrada nos Secrets."
        )

    resposta = requests.get(
        "https://perenual.com/api/v2/species-list",
        params={
            "key": chave,
            "q": nome
        },
        timeout=35
    )

    if not resposta.ok:
        raise ValueError(
            f"Perenual retornou HTTP "
            f"{resposta.status_code}: "
            f"{resposta.text[:250]}"
        )

    dados = resposta.json()

    if not isinstance(dados, dict):
        raise ValueError(
            "Resposta inesperada da Perenual."
        )

    return dados


def ficha_campos(prefixo, inicial):
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
        "Luminosidade",
        opcoes,
        index=(
            opcoes.index(grupo_atual)
            if grupo_atual in opcoes else 0
        ),
        key=prefixo + "grupo"
    )

    cuidados = st.text_area(
        "Cuidados (opcional)",
        value=inicial.get("cuidados", ""),
        key=prefixo + "cuidados"
    )

    observacoes = st.text_area(
        "Observações (opcional)",
        value=inicial.get("observacoes", ""),
        key=prefixo + "observacoes"
    )

    situacao = inicial.get("status", "Pendente")

    status = st.selectbox(
        "Situação",
        STATUS,
        index=STATUS.index(situacao),
        key=prefixo + "status"
    )

    return {
        "nome_comum": nome.strip(),
        "nome_cientifico": cientifico.strip(),
        "familia": familia.strip(),
        "grupo": (
            "" if grupo == "Não definido" else grupo
        ),
        "cuidados": cuidados.strip(),
        "observacoes": observacoes.strip(),
        "status": status,
        "score": inicial.get("score")
    }


# INICIALIZAÇÃO

preparar_banco()

st.title("🪴 Meu Catálogo de Plantas")

st.caption(
    "Versão de teste: identificação + consulta à Perenual"
)

st.warning(
    "Os registros ainda são armazenados localmente "
    "e podem ser perdidos quando o Streamlit reiniciar."
)

aba_identificar, aba_catalogo, aba_teste = st.tabs([
    "📸 Identificar",
    "🪴 Meu catálogo",
    "🔬 Testar Perenual"
])


# TESTE DA PERENUAL

with aba_teste:
    st.subheader("Verificar cobertura da Perenual")

    st.write(
        "Vamos consultar as duas espécies sem adicioná-las "
        "automaticamente ao catálogo."
    )

    if st.button(
        "🔎 Testar as duas espécies",
        type="primary"
    ):
        for nome in [
            "Sedum deppeanum",
            "Crassula pellucida"
        ]:
            st.markdown(f"#### *{nome}*")

            try:
                with st.spinner("Consultando Perenual..."):
                    resposta = pesquisar_perenual(nome)

                itens = resposta.get("data") or []

                if not itens:
                    st.warning(
                        "Nenhum registro retornado "
                        "para esta pesquisa."
                    )

                else:
                    st.write(
                        f"Registros retornados: {len(itens)}"
                    )

                    for item in itens[:5]:
                        st.write(
                            "**Nome comum:**",
                            item.get("common_name")
                            or "Não informado"
                        )

                        nomes_cientificos = (
                            item.get("scientific_name") or []
                        )

                        if isinstance(
                            nomes_cientificos, str
                        ):
                            nomes_cientificos = [
                                nomes_cientificos
                            ]

                        st.write(
                            "**Nome científico:**",
                            ", ".join(nomes_cientificos)
                            or "Não informado"
                        )

                        st.write(
                            "**Luminosidade (sunlight):**",
                            item.get("sunlight")
                            or "Não informada"
                        )

                        st.write(
                            "**Rega (watering):**",
                            item.get("watering")
                            or "Não informada"
                        )

                        st.write(
                            "**ID Perenual:**",
                            item.get("id")
                        )

                        st.divider()

                with st.expander(
                    "Detalhes técnicos da resposta"
                ):
                    st.json({
                        "total": resposta.get("total"),
                        "per_page": resposta.get("per_page"),
                        "current_page": resposta.get(
                            "current_page"
                        )
                    })

            except (
                ValueError,
                requests.RequestException
            ) as erro:
                st.error(str(erro))


# IDENTIFICAÇÃO PELO PLANTNET

with aba_identificar:
    origem = st.radio(
        "Fotografia",
        [
            "Carregar do dispositivo",
            "Tirar foto"
        ]
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
            imagem = Image.open(arquivo).convert("RGB")
            imagem.thumbnail((1600, 1600))

            buffer = io.BytesIO()

            imagem.save(
                buffer,
                format="JPEG",
                quality=85
            )

            foto = buffer.getvalue()

            st.image(
                foto,
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
                "🔎 Identificar planta"
            ):
                try:
                    with st.spinner(
                        "Consultando Pl@ntNet..."
                    ):
                        st.session_state[
                            "resultados_plantnet"
                        ] = identificar(foto)

                except (
                    ValueError,
                    requests.RequestException
                ) as erro:
                    st.error(str(erro))

            resultados = st.session_state.get(
                "resultados_plantnet"
            )

            if resultados:
                principal = resultados[0]
                especie = (
                    principal.get("species") or {}
                )

                nomes = (
                    especie.get("commonNames") or []
                )

                cientifico = taxon(
                    especie.get(
                        "scientificNameWithoutAuthor"
                    )
                    or especie.get("scientificName")
                )

                score = float(
                    principal.get("score") or 0
                )

                st.subheader(
                    "Identificação sugerida"
                )

                st.write(
                    "**Nome:**",
                    nomes[0] if nomes
                    else "Não informado"
                )

                st.write(
                    "**Nome científico:**",
                    cientifico
                )

                st.write(
                    f"**Score Pl@ntNet:** "
                    f"{score * 100:.1f}%"
                )

                st.caption(
                    "O score não garante que a "
                    "identificação esteja correta."
                )

                with st.expander(
                    "Outras possibilidades"
                ):
                    for item in resultados[1:5]:
                        esp = item.get(
                            "species"
                        ) or {}

                        nome_alt = taxon(
                            esp.get(
                                "scientificNameWithoutAuthor"
                            )
                            or esp.get(
                                "scientificName"
                            )
                        )

                        score_alt = float(
                            item.get("score") or 0
                        )

                        st.write(
                            nome_alt,
                            f"({score_alt * 100:.1f}%)"
                        )

                if st.session_state.get(
                    "salvo_assinatura"
                ) == assinatura:
                    st.success(
                        "Planta salva! Veja a aba "
                        "Meu catálogo."
                    )

                else:
                    st.info(
                        "A luminosidade ainda não será "
                        "preenchida automaticamente. "
                        "Estamos validando a Perenual primeiro."
                    )

                    inicial = {
                        "nome_comum": (
                            nomes[0] if nomes else ""
                        ),
                        "nome_cientifico": cientifico,
                        "familia": taxon(
                            especie.get("family")
                        ),
                        "score": score,
                        "status": "Pendente"
                    }

                    with st.form(
                        "nova_planta"
                    ):
                        dados = ficha_campos(
                            "nova_",
                            inicial
                        )

                        enviado = (
                            st.form_submit_button(
                                "💾 Salvar planta"
                            )
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
                                "Para entrar no catálogo, "
                                "a luminosidade precisa estar "
                                "definida. Por enquanto, "
                                "salve como Pendente."
                            )

                        else:
                            salvar(dados, foto)

                            st.session_state[
                                "salvo_assinatura"
                            ] = assinatura

                            st.rerun()

        except (
            OSError,
            ValueError
        ) as erro:
            st.error(
                "Não foi possível processar "
                f"a imagem: {erro}"
            )


# CATÁLOGO UNIFICADO

with aba_catalogo:
    with conectar() as con:
        plantas = [
            dict(x)
            for x in con.execute(
                "SELECT * FROM catalogo_v04 "
                "ORDER BY id DESC"
            ).fetchall()
        ]

    st.subheader("Minhas plantas")

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

    st.caption(
        f"{total_catalogo} no catálogo • "
        f"{total_pendentes} pendentes • "
        f"{total_arquivadas} arquivadas"
    )

    situacoes = st.multiselect(
        "Situação",
        STATUS,
        default=[
            "No catálogo",
            "Pendente"
        ]
    )

    grupo_filtro = st.selectbox(
        "Luminosidade",
        ["Todas"] + GRUPOS + [
            "Não definida"
        ]
    )

    busca = st.text_input(
        "Buscar planta",
        placeholder=(
            "Nome comum ou científico"
        )
    )

    visiveis = [
        p for p in plantas
        if p["status"] in situacoes
        and (
            grupo_filtro == "Todas"
            or (
                p["grupo"] == ""
                if grupo_filtro == "Não definida"
                else p["grupo"] == grupo_filtro
            )
        )
        and (
            not busca
            or busca.casefold() in (
                p["nome_comum"]
                + " "
                + (p["nome_cientifico"] or "")
            ).casefold()
        )
    ]

    if not visiveis:
        st.info(
            "Nenhuma planta corresponde aos filtros."
        )

    for planta in visiveis:
        with st.container(border=True):

            if planta["imagem"]:
                st.image(
                    planta["imagem"],
                    width=220
                )

            st.markdown(
                f"**{planta['nome_comum']}**"
            )

            st.caption(
                f"{planta['nome_cientifico'] or 'Sem identificação'}"
                f" • {planta['grupo'] or 'Luminosidade não definida'}"
                f" • {planta['status']}"
            )

            with st.expander(
                "Ver e editar ficha"
            ):
                with st.form(
                    f"editar_{planta['id']}"
                ):
                    dados = ficha_campos(
                        f"edit_{planta['id']}_",
                        planta
                    )

                    gravar = (
                        st.form_submit_button(
                            "💾 Salvar alterações"
                        )
                    )

                if gravar:
                    if not dados["nome_comum"]:
                        st.error(
                            "Informe um nome."
                        )

                    elif (
                        dados["status"] == "No catálogo"
                        and not dados["grupo"]
                    ):
                        st.error(
                            "Defina a luminosidade "
                            "ou mantenha como Pendente."
                        )

                    else:
                        atualizar(
                            planta["id"],
                            dados
                        )

                        st.rerun()

                confirmar = st.checkbox(
                    "Confirmo a exclusão definitiva",
                    key=f"confirmar_{planta['id']}"
                )

                if st.button(
                    "🗑 Excluir",
                    key=f"excluir_{planta['id']}",
                    disabled=not confirmar
                ):
                    excluir(planta["id"])
                    st.rerun()
