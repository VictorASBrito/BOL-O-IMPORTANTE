document.addEventListener("DOMContentLoaded", function () {
    configurarJogosFechados();
    configurarPesquisas();
    configurarConfirmacoes();
});


function configurarJogosFechados() {
    const toggleFechados = document.getElementById(
        "permitirJogosFechados"
    );

    if (!toggleFechados) {
        return;
    }

    const camposOcultos = document.querySelectorAll(
        ".campo-permitir-fechados"
    );

    const jogosFechados = document.querySelectorAll(
        ".manual-closed-game"
    );

    const textoToggle = document.getElementById(
        "textoPermitirFechados"
    );

    const aviso = document.getElementById(
        "avisoJogosFechados"
    );

    function atualizarPermissao() {
        const permitido = toggleFechados.checked;

        camposOcultos.forEach(function (campo) {
            campo.value = permitido ? "1" : "0";
        });

        jogosFechados.forEach(function (linha) {
            linha.classList.toggle(
                "d-none",
                !permitido
            );

            linha
                .querySelectorAll("input[type='number']")
                .forEach(function (campo) {
                    campo.disabled = !permitido;
                });
        });

        if (textoToggle) {
            textoToggle.textContent = permitido
                ? "Ligado"
                : "Desligado";
        }

        if (aviso) {
            aviso.classList.toggle(
                "d-none",
                !permitido
            );
        }

        const url = new URL(
            window.location.href
        );

        if (permitido) {
            url.searchParams.set(
                "permitir_fechados",
                "1"
            );
        } else {
            url.searchParams.delete(
                "permitir_fechados"
            );
        }

        window.history.replaceState(
            {},
            "",
            url
        );
    }

    toggleFechados.addEventListener(
        "change",
        atualizarPermissao
    );

    atualizarPermissao();
}


function normalizarPesquisa(texto) {
    return String(texto || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .trim();
}


function configurarPesquisas() {
    const camposPesquisa = document.querySelectorAll(
        "[data-filter-input]"
    );

    camposPesquisa.forEach(function (campo) {
        const grupo = campo.dataset.filterInput;

        const itens = document.querySelectorAll(
            `[data-filter-item="${grupo}"]`
        );

        function filtrar() {
            const pesquisa = normalizarPesquisa(
                campo.value
            );

            let encontrados = 0;

            itens.forEach(function (item) {
                const texto = normalizarPesquisa(
                    item.dataset.searchText
                );

                const exibir = (
                    !pesquisa
                    || texto.includes(pesquisa)
                );

                item.classList.toggle(
                    "d-none",
                    !exibir
                );

                if (exibir) {
                    encontrados += 1;
                }
            });

            const contador = document.querySelector(
                `[data-filter-counter="${grupo}"]`
            );

            if (contador) {
                contador.textContent = encontrados;
            }

            if (
                grupo === "jogos"
                && pesquisa
            ) {
                const fechados = document.getElementById(
                    "jogosFechados"
                );

                if (
                    fechados
                    && fechados.querySelector(
                        '[data-filter-item="jogos"]:not(.d-none)'
                    )
                ) {
                    bootstrap.Collapse.getOrCreateInstance(
                        fechados,
                        { toggle: false }
                    ).show();
                }
            }
        }

        campo.addEventListener(
            "input",
            filtrar
        );
    });
}


function configurarConfirmacoes() {
    document
        .querySelectorAll(
            "form[data-confirm-message]"
        )
        .forEach(function (formulario) {
            formulario.addEventListener(
                "submit",
                function (evento) {
                    const mensagem = (
                        formulario.dataset.confirmMessage
                        || "Deseja continuar?"
                    );

                    if (!window.confirm(mensagem)) {
                        evento.preventDefault();
                    }
                }
            );
        });

    document
        .querySelectorAll(
            "[data-delete-button]"
        )
        .forEach(function (botao) {
            botao.addEventListener(
                "click",
                function (evento) {
                    const mensagem = (
                        botao.dataset.confirmMessage
                        || "Deseja excluir este registro?"
                    );

                    if (!window.confirm(mensagem)) {
                        evento.preventDefault();
                    }
                }
            );
        });
}