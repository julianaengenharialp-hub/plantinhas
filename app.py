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
