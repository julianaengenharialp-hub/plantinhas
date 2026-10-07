# ============================================================
# CATÁLOGO DE PLANTAS
# Versão: 0.2
# Etapa 1: Identificação + análise + conferência
# ============================================================

import base64
import io
import json
import sqlite3
import requests

from PIL import Image
import streamlit as st


# ============================================================
# CONFIGURAÇÃO DO STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Meu Catálogo de Plantas",
    page_icon="🪴",
    layout="centered"
)


# ============================================================
# BANCO DE DADOS TEMPORÁRIO
#
# Por enquanto mantemos o SQLite apenas para preservar
# compatibilidade com a versão anterior.
# Nas próximas etapas migraremos para banco permanente.
# ============================================================

conn = sqlite3.connect(
    "plantas.db",
    check_same_thread=False
)

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

conn.commit()


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def converter_imagem_para_base64(imagem_pil):
    """
    Redimensiona e converte a imagem para JPEG em Base64.
    """

    imagem_copia = imagem_pil.copy()

    if imagem_copia.mode not in ("RGB",):
        imagem_copia = imagem_copia.convert("RGB")

    imagem_copia.thumbnail((1000, 1000))

    buffered = io.BytesIO()

    imagem_copia.save(
        buffered,
        format="JPEG",
        quality=85
    )

    return base64.b64encode(
        buffered.getvalue()
    ).decode("utf-8")


def extrair_texto_da_resposta(dados):
    """
    Extrai o conteúdo textual retornado pela API do Gemini.
    """

    if not isinstance(dados, dict):
        return None

    candidates = dados.get("candidates", [])

    if not candidates:
        return None

    for candidate in candidates:

        content = candidate.get("content", {})
        parts = content.get("parts", [])

        for part in parts:

            if (
                isinstance(part, dict)
                and "text" in part
            ):
                return part["text"].strip()

    return None


# ============================================================
# ANÁLISE DA PLANTA
# ============================================================

def analisar_planta(imagem_pil, api_key):

    imagem_base64 = converter_imagem_para_base64(
        imagem_pil
    )

    modelo = "gemini-3.8-flash"

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{modelo}:generateContent"
        f"?key={api_key}"
    )

    prompt = """
Você atua como assistente para identificação visual de plantas.

Analise cuidadosamente SOMENTE a planta visível na fotografia.

O objetivo é auxiliar o usuário a identificar uma planta doméstica
e posteriormente catalogá-la.

REGRAS IMPORTANTES:

1. Não invente informações para completar campos.

2. Quando uma informação não puder ser determinada com segurança,
use exatamente:
"Não determinado com segurança"

3. A identificação feita por fotografia não deve ser apresentada
como confirmação botânica definitiva.

4. Informe um percentual de 0 a 100 representando SUA CONFIANÇA
ESTIMADA na identificação visual.

Esse percentual é uma autoavaliação da identificação e não uma
probabilidade científica ou estatisticamente calibrada.

5. Considere características realmente visíveis na fotografia,
como:
- formato das folhas;
- coloração;
- nervuras;
- disposição das folhas;
- caule;
- padrão de crescimento;
- flores;
- frutos;
- outras características morfológicas observáveis.

Não diga que observou uma característica que não esteja visível.

6. Se houver outra espécie ou gênero visualmente semelhante,
informe como identificação alternativa.

7. Para o grupo de luminosidade escolha EXATAMENTE UMA destas
três categorias:

Sol pleno
Luz indireta
Pouca luz

Critérios gerais:

SOL PLENO:
plantas cujo cultivo normalmente requer ou se beneficia de várias
horas de incidência direta de sol.

LUZ INDIRETA:
plantas normalmente cultivadas em ambiente claro, mas protegidas
da incidência direta intensa durante grande parte do dia.

POUCA LUZ:
plantas capazes de tolerar ambientes com menor intensidade de
luz natural.

"Pouca luz" nunca significa ausência completa de luz.

Escolha a categoria que melhor representa a condição recomendada
para cultivo doméstico da planta identificada.

8. As recomendações de cultivo devem ser compatíveis com a
identificação realizada.

9. Caso a identificação esteja muito incerta, não apresente
cuidados altamente específicos como fatos.

10. Se fotografias adicionais puderem melhorar a identificação,
informe isso e explique quais partes da planta deveriam ser
fotografadas.

11. Curiosidades somente devem ser apresentadas quando você
tiver segurança razoável sobre a informação.

12. Para toxicidade, não presuma segurança.
Se não houver segurança suficiente, responda:
"Não determinado com segurança"

13. Nome científico deve ser informado somente quando houver
base suficiente para determinar pelo menos a espécie ou gênero.

14. Diferencie claramente aquilo que consegue observar na imagem
daquilo que está inferindo com base na identificação provável.
"""

    esquema = {
        "type": "object",
        "properties": {

            "nome_comum": {
                "type": "string"
            },

            "nome_cientifico": {
                "type": "string"
            },

            "familia": {
                "type": "string"
            },

            "grupo_luminosidade": {
                "type": "string",
                "enum": [
                    "Sol pleno",
                    "Luz indireta",
                    "Pouca luz"
                ]
            },

            "confianca": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100
            },

            "caracteristicas_observadas": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            },

            "identificacoes_alternativas": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            },

            "luminosidade": {
                "type": "string"
            },

            "rega": {
                "type": "string"
            },

            "substrato": {
                "type": "string"
            },

            "umidade": {
                "type": "string"
            },

            "toxicidade": {
                "type": "string"
            },

            "porte": {
                "type": "string"
            },

            "curiosidades": {
                "type": "string"
            },

            "observacoes": {
                "type": "string"
            },

            "precisa_mais_fotos": {
                "type": "boolean"
            },

            "fotos_recomendadas": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            }
        },

        "required": [
            "nome_comum",
            "nome_cientifico",
            "familia",
            "grupo_luminosidade",
            "confianca",
            "caracteristicas_observadas",
            "identificacoes_alternativas",
            "luminosidade",
            "rega",
            "substrato",
            "umidade",
            "toxicidade",
            "porte",
            "curiosidades",
            "observacoes",
            "precisa_mais_fotos",
            "fotos_recomendadas"
        ]
    }

    payload = {

        "contents": [
            {
                "parts": [

                    {
                        "text": prompt
                    },

                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": imagem_base64
                        }
                    }
                ]
            }
        ],

        "generationConfig": {

            "responseMimeType": "application/json",

            "responseSchema": esquema,

            # Queremos comportamento conservador,
            # não criatividade.
            "temperature": 0.1
        }
    }

    try:

        response = requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json"
            },
            timeout=60
        )

    except requests.exceptions.Timeout:

        raise Exception(
            "O serviço de identificação demorou demais "
            "para responder. Tente novamente mais tarde."
        )

    except requests.exceptions.ConnectionError:

        raise Exception(
            "Não foi possível conectar ao serviço "
            "de identificação."
        )

    try:

        dados = response.json()

    except ValueError:

        raise Exception(
            "O serviço retornou uma resposta que o "
            "aplicativo não conseguiu interpretar."
        )

    # --------------------------------------------------------
    # TRATAMENTO DO ERRO DE COTA
    # --------------------------------------------------------

    if response.status_code == 429:

        raise Exception(
            "O limite disponível de análises do Gemini "
            "foi atingido. Aguarde a renovação da cota "
            "antes de realizar uma nova identificação."
        )

    # --------------------------------------------------------
    # OUTROS ERROS
    # --------------------------------------------------------

    if response.status_code != 200:

        mensagem = (
            dados
            .get("error", {})
            .get(
                "message",
                "Erro desconhecido."
            )
        )

        raise Exception(
            f"Erro do serviço de identificação "
            f"({response.status_code}): {mensagem}"
        )

    texto = extrair_texto_da_resposta(dados)

    if not texto:

        raise Exception(
            "A inteligência artificial respondeu, mas "
            "não forneceu uma identificação utilizável."
        )

    try:

        resultado = json.loads(texto)

    except json.JSONDecodeError:

        raise Exception(
            "A resposta recebida não pôde ser "
            "interpretada corretamente."
        )

    return resultado, imagem_base64


# ============================================================
# CABEÇALHO
# ============================================================

st.title("🪴 Meu Catálogo de Plantas")

st.write(
    "Fotografe ou envie a imagem de uma planta para "
    "receber uma sugestão de identificação."
)

st.caption(
    "Nenhuma identificação será adicionada automaticamente "
    "ao seu catálogo."
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

st.sidebar.header("Configurações")

api_key = st.sidebar.text_input(
    "Chave da API Gemini",
    type="password",
    help=(
        "Use a chave criada no Google AI Studio. "
        "Em uma etapa posterior ela ficará armazenada "
        "de forma segura."
    )
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
# ABA IDENTIFICAR
# ============================================================

with tab_identificar:

    st.subheader("Identificar uma planta")

    origem = st.radio(
        "Como deseja enviar a fotografia?",
        [
            "Tirar foto",
            "Carregar do dispositivo"
        ]
    )

    imagem = None

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

    if arquivo:

        try:

            imagem = Image.open(arquivo)

            st.image(
                imagem,
                caption="Fotografia selecionada",
                use_container_width=True
            )

        except Exception:

            st.error(
                "Não foi possível abrir esta imagem."
            )

            imagem = None

    # --------------------------------------------------------
    # BOTÃO DE ANÁLISE
    # --------------------------------------------------------

    if imagem is not None:

        if not api_key:

            st.warning(
                "Informe sua chave da API Gemini "
                "na barra lateral para realizar a análise."
            )

        else:

            if st.button(
                "✨ Identificar planta",
                type="primary"
            ):

                try:

                    with st.spinner(
                        "Observando folhas, caule e "
                        "outras características..."
                    ):

                        resultado, imagem_b64 = (
                            analisar_planta(
                                imagem,
                                api_key
                            )
                        )

                    st.session_state[
                        "analise_planta"
                    ] = resultado

                    st.session_state[
                        "imagem_analise"
                    ] = imagem_b64

                except Exception as erro:

                    st.error(str(erro))


    # ========================================================
    # RESULTADO DA ANÁLISE
    # ========================================================

    if "analise_planta" in st.session_state:

        resultado = st.session_state[
            "analise_planta"
        ]

        st.divider()

        st.header(
            "Resultado da identificação"
        )

        nome_comum = resultado.get(
            "nome_comum",
            "Não determinado com segurança"
        )

        nome_cientifico = resultado.get(
            "nome_cientifico",
            "Não determinado com segurança"
        )

        familia = resultado.get(
            "familia",
            "Não determinado com segurança"
        )

        grupo = resultado.get(
            "grupo_luminosidade",
            "Não determinado com segurança"
        )

        confianca = resultado.get(
            "confianca",
            0
        )

        # Garantia adicional para evitar
        # valores inválidos no componente visual.

        try:
            confianca = int(confianca)
        except (TypeError, ValueError):
            confianca = 0

        confianca = max(
            0,
            min(
                confianca,
                100
            )
        )

        # ----------------------------------------------------
        # IDENTIFICAÇÃO PRINCIPAL
        # ----------------------------------------------------

        st.subheader(nome_comum)

        if (
            nome_cientifico
            != "Não determinado com segurança"
        ):

            st.markdown(
                f"*{nome_cientifico}*"
            )

        st.write(
            f"**Família botânica:** {familia}"
        )

        st.write(
            f"**Grupo:** {grupo}"
        )

        # ----------------------------------------------------
        # CONFIANÇA
        # ----------------------------------------------------

        st.write(
            "**Confiança estimada da identificação**"
        )

        st.progress(
            confianca / 100
        )

        st.write(
            f"**{confianca}%**"
        )

        if confianca >= 80:

            st.success(
                "Confiança estimada alta. "
                "Ainda assim, confira a identificação "
                "antes de adicioná-la ao catálogo."
            )

        elif confianca >= 60:

            st.warning(
                "Confiança estimada moderada. "
                "É recomendável conferir a identificação."
            )

        else:

            st.error(
                "Confiança estimada baixa. "
                "Recomendamos obter mais evidências "
                "antes de confirmar a espécie."
            )

        st.caption(
            "Este percentual representa uma estimativa "
            "do próprio modelo sobre a identificação "
            "visual. Não corresponde a uma confirmação "
            "botânica ou probabilidade estatística."
        )

        # ----------------------------------------------------
        # EVIDÊNCIAS VISUAIS
        # ----------------------------------------------------

        st.subheader(
            "🔎 Características observadas"
        )

        caracteristicas = resultado.get(
            "caracteristicas_observadas",
            []
        )

        if caracteristicas:

            for item in caracteristicas:

                st.write(
                    f"• {item}"
                )

        else:

            st.write(
                "Não foram informadas características "
                "visuais conclusivas."
            )

        # ----------------------------------------------------
        # IDENTIFICAÇÕES ALTERNATIVAS
        # ----------------------------------------------------

        alternativas = resultado.get(
            "identificacoes_alternativas",
            []
        )

        if alternativas:

            st.subheader(
                "Outras identificações possíveis"
            )

            for alternativa in alternativas:

                st.write(
                    f"• {alternativa}"
                )

        # ----------------------------------------------------
        # CULTIVO
        # ----------------------------------------------------

        st.subheader(
            "🌱 Orientações de cultivo"
        )

        st.write(
            "**Luminosidade:** "
            + resultado.get(
                "luminosidade",
                "Não determinado com segurança"
            )
        )

        st.write(
            "**Rega:** "
            + resultado.get(
                "rega",
                "Não determinado com segurança"
            )
        )

        st.write(
            "**Substrato:** "
            + resultado.get(
                "substrato",
                "Não determinado com segurança"
            )
        )

        st.write(
            "**Umidade:** "
            + resultado.get(
                "umidade",
                "Não determinado com segurança"
            )
        )

        st.write(
            "**Porte:** "
            + resultado.get(
                "porte",
                "Não determinado com segurança"
            )
        )

        st.write(
            "**Toxicidade:** "
            + resultado.get(
                "toxicidade",
                "Não determinado com segurança"
            )
        )

        # ----------------------------------------------------
        # CURIOSIDADES
        # ----------------------------------------------------

        curiosidades = resultado.get(
            "curiosidades",
            ""
        )

        if (
            curiosidades
            and curiosidades
            != "Não determinado com segurança"
        ):

            st.subheader(
                "💡 Curiosidades"
            )

            st.write(
                curiosidades
            )

        # ----------------------------------------------------
        # OBSERVAÇÕES
        # ----------------------------------------------------

        observacoes = resultado.get(
            "observacoes",
            ""
        )

        if observacoes:

            st.subheader(
                "📝 Observações"
            )

            st.write(
                observacoes
            )

        # ----------------------------------------------------
        # MAIS FOTOS
        # ----------------------------------------------------

        precisa_mais_fotos = resultado.get(
            "precisa_mais_fotos",
            False
        )

        if precisa_mais_fotos:

            st.warning(
                "Fotografias adicionais podem ajudar "
                "a melhorar a identificação."
            )

            fotos_recomendadas = resultado.get(
                "fotos_recomendadas",
                []
            )

            if fotos_recomendadas:

                st.write(
                    "**Tente fotografar:**"
                )

                for sugestao in fotos_recomendadas:

                    st.write(
                        f"• {sugestao}"
                    )

        # ----------------------------------------------------
        # AVISO FINAL
        # ----------------------------------------------------

        st.info(
            "Esta análise ainda NÃO foi adicionada "
            "ao seu catálogo. Nas próximas etapas você "
            "poderá revisar as informações e decidir "
            "se deseja mantê-la pendente ou confirmar "
            "o cadastro."
        )


# ============================================================
# ABA CATÁLOGO
# ============================================================

with tab_catalogo:

    st.header(
        "🪴 Meu Catálogo"
    )

    st.info(
        "Nesta etapa ainda não estamos gravando novas "
        "identificações. Primeiro estamos validando "
        "o sistema de reconhecimento e conferência."
    )

    st.subheader(
        "Como o catálogo será organizado"
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
        "Na próxima etapa também teremos:"
    )

    st.write(
        "⏳ **Pendentes** — plantas aguardando sua conferência"
    )

    st.write(
        "📦 **Arquivadas** — plantas que já fizeram parte "
        "da coleção"
    )

    st.write(
        "🗑️ **Excluir** — remoção definitiva do registro"
    )
