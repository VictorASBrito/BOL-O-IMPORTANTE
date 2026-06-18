import os
import re

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from services.importacao_service import (
    importar_mensagem_whatsapp,
    normalizar_texto,
)

from services.json_service import (
    carregar_dados,
    gerar_proximo_id,
    salvar_dados,
)

from services.pontuacao_service import (
    calcular_pontos,
    montar_ranking,
)


app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "chave-local-do-bolao"
)


def converter_inteiro_form(
    nome_campo: str
) -> int | None:
    valor = request.form.get(
        nome_campo,
        ""
    ).strip()

    if not valor.isdigit():
        return None

    return int(valor)

def separar_apelidos(
    texto: str,
    nome_principal: str
) -> list[str]:
    apelidos = []
    identificadores_adicionados = set()

    nome_normalizado = normalizar_texto(
        nome_principal
    )

    partes = re.split(
        r"[,;\n]+",
        texto or ""
    )

    for parte in partes:
        apelido = parte.strip()

        if not apelido:
            continue

        apelido_normalizado = normalizar_texto(
            apelido
        )

        if not apelido_normalizado:
            continue

        if apelido_normalizado == nome_normalizado:
            continue

        if apelido_normalizado in identificadores_adicionados:
            continue

        identificadores_adicionados.add(
            apelido_normalizado
        )

        apelidos.append(apelido)

    return apelidos


def obter_apelidos_participante(
    participante: dict
) -> list[str]:
    apelidos = []
    identificadores_adicionados = set()

    nome_normalizado = normalizar_texto(
        participante.get("nome", "")
    )

    apelido_antigo = participante.get(
        "apelido",
        ""
    )

    valores = []

    if apelido_antigo:
        valores.append(apelido_antigo)

    valores.extend(
        participante.get("apelidos", [])
    )

    for valor in valores:
        apelido = str(valor).strip()

        if not apelido:
            continue

        apelido_normalizado = normalizar_texto(
            apelido
        )

        if apelido_normalizado == nome_normalizado:
            continue

        if apelido_normalizado in identificadores_adicionados:
            continue

        identificadores_adicionados.add(
            apelido_normalizado
        )

        apelidos.append(apelido)

    return apelidos


def obter_identificadores_participante(
    participante: dict
) -> set[str]:
    identificadores = {
        normalizar_texto(
            participante.get("nome", "")
        )
    }

    for apelido in obter_apelidos_participante(
        participante
    ):
        identificadores.add(
            normalizar_texto(apelido)
        )

    identificadores.discard("")

    return identificadores


def verificar_identificador_em_uso(
    dados: dict,
    nome: str,
    apelidos: list[str],
    participante_ignorado_id: int | None = None
) -> str | None:
    candidatos = {
        normalizar_texto(nome)
    }

    candidatos.update(
        normalizar_texto(apelido)
        for apelido in apelidos
    )

    candidatos.discard("")

    for participante in dados["participantes"]:
        if (
            participante_ignorado_id is not None
            and participante["id"]
            == participante_ignorado_id
        ):
            continue

        identificadores_existentes = (
            obter_identificadores_participante(
                participante
            )
        )

        conflito = candidatos.intersection(
            identificadores_existentes
        )

        if conflito:
            return participante["nome"]

    return None

def montar_contexto_palpites(
    resultado_importacao=None,
    permitir_fechados: bool = False
) -> dict:
    dados = carregar_dados()

    participantes_por_id = {
        participante["id"]: participante
        for participante in dados["participantes"]
    }

    jogos_por_id = {
        jogo["id"]: jogo
        for jogo in dados["jogos"]
    }

    palpites_exibicao = []

    for palpite in dados["palpites"]:
        participante = participantes_por_id.get(
            palpite["participante_id"]
        )

        jogo = jogos_por_id.get(
            palpite["jogo_id"]
        )

        if not participante or not jogo:
            continue

        palpites_exibicao.append({
            **palpite,
            "participante_nome": participante[
                "nome"
            ],
            "jogo_codigo": jogo["codigo"],
            "time_casa": jogo["time_casa"],
            "time_visitante": jogo[
                "time_visitante"
            ],
            "rodada": jogo.get("rodada", 0),
            "situacao_jogo": jogo.get(
                "situacao",
                "ABERTO"
            ),
        })

    palpites_exibicao.sort(
        key=lambda item: (
            item["participante_nome"].lower(),
            item["rodada"],
            item["jogo_id"],
        )
    )

    participantes = sorted(
        dados["participantes"],
        key=lambda participante: participante[
            "nome"
        ].lower()
    )

    jogos_ordenados = sorted(
        dados["jogos"],
        key=lambda jogo: (
            0
            if jogo.get("situacao", "ABERTO")
            == "ABERTO"
            else 1,
            jogo.get("rodada", 0),
            jogo.get("data_hora", ""),
            jogo["id"],
        )
    )

    jogos_manuais = []

    for jogo_original in jogos_ordenados:
        situacao = jogo_original.get(
            "situacao",
            "ABERTO"
        )

        # Jogo cancelado nunca aceita palpite.
        if situacao == "CANCELADO":
            continue

        jogo = {
            **jogo_original,
            "fechado": situacao != "ABERTO",
        }

        jogos_manuais.append(jogo)

    return {
        "participantes": participantes,
        "jogos": jogos_ordenados,
        "jogos_manuais": jogos_manuais,
        "palpites": palpites_exibicao,
        "resultado_importacao": (
            resultado_importacao
        ),
        "permitir_fechados": permitir_fechados,
    }


@app.route("/")
def dashboard():
    dados = carregar_dados()
    ranking = montar_ranking(dados)

    lider = ranking[0] if ranking else None

    jogos_abertos = sum(
        1
        for jogo in dados["jogos"]
        if jogo.get("situacao") == "ABERTO"
    )

    jogos_finalizados = sum(
        1
        for jogo in dados["jogos"]
        if jogo.get("situacao") == "FINALIZADO"
    )

    return render_template(
        "dashboard.html",
        quantidade_participantes=len(
            dados["participantes"]
        ),
        quantidade_jogos=len(
            dados["jogos"]
        ),
        quantidade_palpites=len(
            dados["palpites"]
        ),
        jogos_abertos=jogos_abertos,
        jogos_finalizados=jogos_finalizados,
        lider=lider,
    )


@app.route("/participantes")
def listar_participantes():
    dados = carregar_dados()

    participantes = []

    for participante_original in dados["participantes"]:
        participante = {
            **participante_original,
            "apelidos_exibicao": (
                obter_apelidos_participante(
                    participante_original
                )
            ),
        }

        participantes.append(
            participante
        )

    participantes.sort(
        key=lambda participante: participante[
            "nome"
        ].lower()
    )

    return render_template(
        "participantes.html",
        participantes=participantes
    )


@app.route(
    "/participantes/adicionar",
    methods=["POST"]
)
def adicionar_participante():
    nome = request.form.get(
        "nome",
        ""
    ).strip()

    apelidos_texto = request.form.get(
        "apelidos",
        ""
    ).strip()

    if not nome:
        flash(
            "O nome do participante é obrigatório.",
            "danger"
        )

        return redirect(
            url_for("listar_participantes")
        )

    dados = carregar_dados()

    apelidos = separar_apelidos(
        apelidos_texto,
        nome
    )

    participante_em_conflito = (
        verificar_identificador_em_uso(
            dados,
            nome,
            apelidos
        )
    )

    if participante_em_conflito:
        flash(
            (
                "O nome ou um dos apelidos informados "
                f"já pertence a {participante_em_conflito}."
            ),
            "danger"
        )

        return redirect(
            url_for("listar_participantes")
        )

    participante = {
        "id": gerar_proximo_id(
            dados["participantes"]
        ),
        "nome": nome,
        "apelidos": apelidos,
        "ativo": True,
    }

    dados["participantes"].append(
        participante
    )

    salvar_dados(dados)

    flash(
        f"Participante {nome} adicionado.",
        "success"
    )

    return redirect(
        url_for("listar_participantes")
    )


@app.route("/jogos")
def listar_jogos():
    dados = carregar_dados()

    jogos_abertos = [
        jogo
        for jogo in dados["jogos"]
        if jogo.get("situacao", "ABERTO")
        == "ABERTO"
    ]

    jogos_fechados = [
        jogo
        for jogo in dados["jogos"]
        if jogo.get("situacao", "ABERTO")
        != "ABERTO"
    ]

    jogos_abertos.sort(
        key=lambda jogo: (
            jogo.get("rodada", 0),
            jogo.get("data_hora", ""),
            jogo["id"],
        )
    )

    jogos_fechados.sort(
        key=lambda jogo: (
            -jogo.get("rodada", 0),
            -jogo["id"],
        )
    )

    return render_template(
        "jogos.html",
        jogos_abertos=jogos_abertos,
        jogos_fechados=jogos_fechados
    )


@app.route(
    "/jogos/adicionar",
    methods=["POST"]
)
def adicionar_jogo():
    dados = carregar_dados()

    rodada = converter_inteiro_form(
        "rodada"
    )

    time_casa = request.form.get(
        "time_casa",
        ""
    ).strip()

    time_visitante = request.form.get(
        "time_visitante",
        ""
    ).strip()

    data_hora = request.form.get(
        "data_hora",
        ""
    ).strip()

    if rodada is None or rodada < 1:
        flash(
            "A rodada deve ser um número válido.",
            "danger"
        )

        return redirect(
            url_for("listar_jogos")
        )

    if not time_casa or not time_visitante:
        flash(
            "Os dois times são obrigatórios.",
            "danger"
        )

        return redirect(
            url_for("listar_jogos")
        )

    if time_casa.lower() == time_visitante.lower():
        flash(
            "Os times do jogo devem ser diferentes.",
            "danger"
        )

        return redirect(
            url_for("listar_jogos")
        )

    proximo_id = gerar_proximo_id(
        dados["jogos"]
    )

    jogo = {
        "id": proximo_id,
        "codigo": f"J{proximo_id:02d}",
        "rodada": rodada,
        "time_casa": time_casa,
        "time_visitante": time_visitante,
        "data_hora": data_hora,
        "gols_casa": None,
        "gols_visitante": None,
        "situacao": "ABERTO",
    }

    dados["jogos"].append(jogo)

    salvar_dados(dados)

    flash(
        (
            f"Jogo {time_casa} x "
            f"{time_visitante} adicionado."
        ),
        "success"
    )

    return redirect(
        url_for("listar_jogos")
    )

@app.route(
    "/jogos/<int:jogo_id>/excluir",
    methods=["POST"]
)
def excluir_jogo(jogo_id: int):
    dados = carregar_dados()

    jogo = next(
        (
            item
            for item in dados["jogos"]
            if item["id"] == jogo_id
        ),
        None
    )

    if jogo is None:
        flash(
            "Jogo não encontrado.",
            "danger"
        )

        return redirect(
            url_for("listar_jogos")
        )

    quantidade_anterior = len(
        dados["palpites"]
    )

    dados["palpites"] = [
        palpite
        for palpite in dados["palpites"]
        if palpite["jogo_id"] != jogo_id
    ]

    palpites_removidos = (
        quantidade_anterior
        - len(dados["palpites"])
    )

    dados["jogos"] = [
        item
        for item in dados["jogos"]
        if item["id"] != jogo_id
    ]

    salvar_dados(dados)

    flash(
        (
            f"Jogo {jogo['time_casa']} x "
            f"{jogo['time_visitante']} excluído. "
            f"{palpites_removidos} palpite(s) "
            "também foram removidos."
        ),
        "success"
    )

    return redirect(
        url_for("listar_jogos")
    )

@app.route(
    "/palpites/<int:palpite_id>/excluir",
    methods=["POST"]
)
def excluir_palpite(palpite_id: int):
    dados = carregar_dados()

    palpite = next(
        (
            item
            for item in dados["palpites"]
            if item["id"] == palpite_id
        ),
        None
    )

    if palpite is None:
        flash(
            "Palpite não encontrado.",
            "danger"
        )

        return redirect(
            url_for("listar_palpites")
        )

    dados["palpites"] = [
        item
        for item in dados["palpites"]
        if item["id"] != palpite_id
    ]

    salvar_dados(dados)

    flash(
        "Palpite excluído.",
        "success"
    )

    return redirect(
        url_for("listar_palpites")
    )

@app.route(
    "/jogos/<int:jogo_id>/resultado",
    methods=["POST"]
)
def informar_resultado(jogo_id: int):
    gols_casa = converter_inteiro_form(
        "gols_casa"
    )

    gols_visitante = converter_inteiro_form(
        "gols_visitante"
    )

    if (
        gols_casa is None
        or gols_visitante is None
    ):
        flash(
            (
                "Informe números válidos para o "
                "resultado final."
            ),
            "danger"
        )

        return redirect(
            url_for("listar_jogos")
        )

    dados = carregar_dados()

    jogo = next(
        (
            jogo
            for jogo in dados["jogos"]
            if jogo["id"] == jogo_id
        ),
        None
    )

    if jogo is None:
        flash(
            "Jogo não encontrado.",
            "danger"
        )

        return redirect(
            url_for("listar_jogos")
        )

    jogo["gols_casa"] = gols_casa
    jogo["gols_visitante"] = gols_visitante
    jogo["situacao"] = "FINALIZADO"

    salvar_dados(dados)

    flash(
        (
            f"Resultado salvo: "
            f"{jogo['time_casa']} "
            f"{gols_casa} x {gols_visitante} "
            f"{jogo['time_visitante']}."
        ),
        "success"
    )

    return redirect(
        url_for("listar_jogos")
    )


@app.route("/palpites")
def listar_palpites():
    permitir_fechados = (
        request.args.get(
            "permitir_fechados",
            "0"
        ) == "1"
    )

    contexto = montar_contexto_palpites(
        permitir_fechados=permitir_fechados
    )

    return render_template(
        "palpites.html",
        **contexto
    )


@app.route(
    "/palpites/adicionar",
    methods=["POST"]
)
def adicionar_palpite():
    participante_id = converter_inteiro_form(
        "participante_id"
    )

    permitir_fechados = (
        request.form.get(
            "permitir_jogos_fechados",
            "0"
        ) == "1"
    )

    parametro_retorno = (
        1 if permitir_fechados else 0
    )

    if participante_id is None:
        flash(
            "Selecione um participante.",
            "danger"
        )

        return redirect(
            url_for(
                "listar_palpites",
                permitir_fechados=parametro_retorno
            )
        )

    dados = carregar_dados()

    participante = next(
        (
            participante
            for participante in dados[
                "participantes"
            ]
            if participante["id"]
            == participante_id
        ),
        None
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger"
        )

        return redirect(
            url_for(
                "listar_palpites",
                permitir_fechados=parametro_retorno
            )
        )

    palpites_por_chave = {
        (
            palpite["participante_id"],
            palpite["jogo_id"],
        ): palpite
        for palpite in dados["palpites"]
    }

    palpites_criados = 0
    palpites_atualizados = 0
    erros = []

    for jogo in dados["jogos"]:
        situacao = jogo.get(
            "situacao",
            "ABERTO"
        )

        if situacao == "CANCELADO":
            continue

        if (
            situacao != "ABERTO"
            and not permitir_fechados
        ):
            continue

        nome_campo_casa = (
            f"gols_casa_{jogo['id']}"
        )

        nome_campo_visitante = (
            f"gols_visitante_{jogo['id']}"
        )

        gols_casa_texto = request.form.get(
            nome_campo_casa,
            ""
        ).strip()

        gols_visitante_texto = request.form.get(
            nome_campo_visitante,
            ""
        ).strip()

        # Nenhum valor preenchido:
        # apenas ignora este jogo.
        if (
            not gols_casa_texto
            and not gols_visitante_texto
        ):
            continue

        # Apenas um lado preenchido.
        if (
            not gols_casa_texto
            or not gols_visitante_texto
        ):
            erros.append(
                (
                    f"{jogo['time_casa']} x "
                    f"{jogo['time_visitante']}: "
                    "preencha os dois placares."
                )
            )

            continue

        if (
            not gols_casa_texto.isdigit()
            or not gols_visitante_texto.isdigit()
        ):
            erros.append(
                (
                    f"{jogo['time_casa']} x "
                    f"{jogo['time_visitante']}: "
                    "o placar deve conter apenas números."
                )
            )

            continue

        gols_casa = int(
            gols_casa_texto
        )

        gols_visitante = int(
            gols_visitante_texto
        )

        chave = (
            participante_id,
            jogo["id"],
        )

        palpite_existente = (
            palpites_por_chave.get(chave)
        )

        if palpite_existente:
            palpite_existente[
                "gols_casa"
            ] = gols_casa

            palpite_existente[
                "gols_visitante"
            ] = gols_visitante

            palpites_atualizados += 1

        else:
            novo_palpite = {
                "id": gerar_proximo_id(
                    dados["palpites"]
                ),
                "participante_id": participante_id,
                "jogo_id": jogo["id"],
                "gols_casa": gols_casa,
                "gols_visitante": gols_visitante,
            }

            dados["palpites"].append(
                novo_palpite
            )

            palpites_por_chave[chave] = (
                novo_palpite
            )

            palpites_criados += 1

    if (
        palpites_criados == 0
        and palpites_atualizados == 0
        and not erros
    ):
        flash(
            (
                "Nenhum placar foi preenchido. "
                "Informe pelo menos um palpite."
            ),
            "warning"
        )

        return redirect(
            url_for(
                "listar_palpites",
                permitir_fechados=parametro_retorno
            )
        )

    if (
        palpites_criados > 0
        or palpites_atualizados > 0
    ):
        salvar_dados(dados)

        flash(
            (
                f"{palpites_criados} palpite(s) "
                f"adicionado(s) e "
                f"{palpites_atualizados} "
                "atualizado(s)."
            ),
            "success"
        )

    for erro in erros:
        flash(
            erro,
            "danger"
        )

    return redirect(
        url_for(
            "listar_palpites",
            permitir_fechados=parametro_retorno
        )
    )
    participante_id = converter_inteiro_form(
        "participante_id"
    )

    jogo_id = converter_inteiro_form(
        "jogo_id"
    )

    gols_casa = converter_inteiro_form(
        "gols_casa"
    )

    gols_visitante = converter_inteiro_form(
        "gols_visitante"
    )

    if (
        participante_id is None
        or jogo_id is None
        or gols_casa is None
        or gols_visitante is None
    ):
        flash(
            "Preencha todos os dados do palpite.",
            "danger"
        )

        return redirect(
            url_for("listar_palpites")
        )

    dados = carregar_dados()

    participante = next(
        (
            participante
            for participante in dados[
                "participantes"
            ]
            if participante["id"]
            == participante_id
        ),
        None
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger"
        )

        return redirect(
            url_for("listar_palpites")
        )

    jogo = next(
        (
            jogo
            for jogo in dados["jogos"]
            if jogo["id"] == jogo_id
        ),
        None
    )

    if jogo is None:
        flash(
            "Jogo não encontrado.",
            "danger"
        )

        return redirect(
            url_for("listar_palpites")
        )

    if jogo.get("situacao") != "ABERTO":
        flash(
            (
                "Este jogo não aceita mais "
                "palpites."
            ),
            "warning"
        )

        return redirect(
            url_for("listar_palpites")
        )

    palpite_existente = next(
        (
            palpite
            for palpite in dados["palpites"]
            if (
                palpite["participante_id"]
                == participante_id
                and palpite["jogo_id"]
                == jogo_id
            )
        ),
        None
    )

    if palpite_existente:
        palpite_existente[
            "gols_casa"
        ] = gols_casa

        palpite_existente[
            "gols_visitante"
        ] = gols_visitante

        mensagem = "Palpite atualizado."

    else:
        dados["palpites"].append({
            "id": gerar_proximo_id(
                dados["palpites"]
            ),
            "participante_id": participante_id,
            "jogo_id": jogo_id,
            "gols_casa": gols_casa,
            "gols_visitante": gols_visitante,
        })

        mensagem = "Palpite adicionado."

    salvar_dados(dados)

    flash(
        mensagem,
        "success"
    )

    return redirect(
        url_for("listar_palpites")
    )


@app.route(
    "/palpites/importar",
    methods=["POST"]
)
def importar_palpites():
    mensagem = request.form.get(
        "mensagem_whatsapp",
        ""
    ).strip()

    permitir_fechados = (
        request.form.get(
            "permitir_jogos_fechados",
            "0"
        ) == "1"
    )

    if not mensagem:
        flash(
            (
                "Cole a mensagem do WhatsApp "
                "antes de importar."
            ),
            "warning"
        )

        return redirect(
            url_for(
                "listar_palpites",
                permitir_fechados=(
                    1 if permitir_fechados else 0
                )
            )
        )

    dados = carregar_dados()

    resultado_importacao = (
        importar_mensagem_whatsapp(
            mensagem,
            dados,
            permitir_jogos_fechados=(
                permitir_fechados
            )
        )
    )

    salvar_dados(dados)

    contexto = montar_contexto_palpites(
        resultado_importacao,
        permitir_fechados=permitir_fechados
    )

    return render_template(
        "palpites.html",
        **contexto
    )
    mensagem = request.form.get(
        "mensagem_whatsapp",
        ""
    ).strip()

    if not mensagem:
        flash(
            (
                "Cole a mensagem do WhatsApp "
                "antes de importar."
            ),
            "warning"
        )

        return redirect(
            url_for("listar_palpites")
        )

    dados = carregar_dados()

    resultado_importacao = (
        importar_mensagem_whatsapp(
            mensagem,
            dados
        )
    )

    salvar_dados(dados)

    contexto = montar_contexto_palpites(
        resultado_importacao
    )

    return render_template(
        "palpites.html",
        **contexto
    )


@app.route("/ranking")
def exibir_ranking():
    dados = carregar_dados()
    ranking = montar_ranking(dados)

    return render_template(
        "ranking.html",
        ranking=ranking
    )
    
@app.route(
    "/participantes/<int:participante_id>/apelidos",
    methods=["POST"]
)
def atualizar_apelidos(
    participante_id: int
):
    dados = carregar_dados()

    participante = next(
        (
            participante
            for participante in dados["participantes"]
            if participante["id"]
            == participante_id
        ),
        None
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger"
        )

        return redirect(
            url_for("listar_participantes")
        )

    apelidos_texto = request.form.get(
        "apelidos",
        ""
    )

    apelidos = separar_apelidos(
        apelidos_texto,
        participante["nome"]
    )

    participante_em_conflito = (
        verificar_identificador_em_uso(
            dados,
            participante["nome"],
            apelidos,
            participante_ignorado_id=participante_id
        )
    )

    if participante_em_conflito:
        flash(
            (
                "Um dos apelidos informados já "
                f"pertence a {participante_em_conflito}."
            ),
            "danger"
        )

        return redirect(
            url_for("listar_participantes")
        )

    participante["apelidos"] = apelidos

    # Remove o campo antigo após a atualização.
    participante.pop(
        "apelido",
        None
    )

    salvar_dados(dados)

    flash(
        (
            f"Apelidos de {participante['nome']} "
            "atualizados."
        ),
        "success"
    )

    return redirect(
        url_for("listar_participantes")
    )

@app.route("/participantes/<int:participante_id>")
def perfil_participante(participante_id: int):
    dados = carregar_dados()

    participante = next(
        (
            item
            for item in dados["participantes"]
            if item["id"] == participante_id
        ),
        None
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger"
        )

        return redirect(
            url_for("listar_participantes")
        )

    jogos_por_id = {
        jogo["id"]: jogo
        for jogo in dados["jogos"]
    }

    historico = []

    total_pontos = 0
    placares_exatos = 0
    resultados_corretos = 0
    resultados_errados = 0
    jogos_pontuados = 0
    palpites_pendentes = 0

    for palpite in dados["palpites"]:
        if (
            palpite["participante_id"]
            != participante_id
        ):
            continue

        jogo = jogos_por_id.get(
            palpite["jogo_id"]
        )

        if jogo is None:
            continue

        resultado_definido = (
            jogo.get("gols_casa") is not None
            and jogo.get("gols_visitante") is not None
            and jogo.get("situacao") != "CANCELADO"
        )

        pontos = None

        if resultado_definido:
            pontos = calcular_pontos(
                palpite["gols_casa"],
                palpite["gols_visitante"],
                jogo["gols_casa"],
                jogo["gols_visitante"]
            )

            total_pontos += pontos
            jogos_pontuados += 1

            if pontos == 3:
                placares_exatos += 1
            elif pontos == 1:
                resultados_corretos += 1
            else:
                resultados_errados += 1
        else:
            palpites_pendentes += 1

        historico.append({
            "palpite_id": palpite["id"],
            "jogo_id": jogo["id"],
            "codigo": jogo["codigo"],
            "rodada": jogo.get("rodada", 0),
            "time_casa": jogo["time_casa"],
            "time_visitante": jogo[
                "time_visitante"
            ],
            "palpite_casa": palpite[
                "gols_casa"
            ],
            "palpite_visitante": palpite[
                "gols_visitante"
            ],
            "resultado_casa": jogo.get(
                "gols_casa"
            ),
            "resultado_visitante": jogo.get(
                "gols_visitante"
            ),
            "situacao": jogo.get(
                "situacao",
                "ABERTO"
            ),
            "data_hora": jogo.get(
                "data_hora",
                ""
            ),
            "pontos": pontos,
        })

    historico.sort(
        key=lambda item: (
            item["rodada"],
            item["jogo_id"],
        ),
        reverse=True
    )

    ranking = montar_ranking(dados)

    classificacao = next(
        (
            item
            for item in ranking
            if item["participante_id"]
            == participante_id
        ),
        None
    )

    pontuacao_maxima = jogos_pontuados * 3

    aproveitamento = (
        round(
            total_pontos
            / pontuacao_maxima
            * 100,
            1
        )
        if pontuacao_maxima > 0
        else 0
    )

    participante_exibicao = {
        **participante,
        "apelidos_exibicao": (
            obter_apelidos_participante(
                participante
            )
        ),
    }

    estatisticas = {
        "posicao": (
            classificacao["posicao"]
            if classificacao
            else None
        ),
        "pontos": total_pontos,
        "total_palpites": len(historico),
        "jogos_pontuados": jogos_pontuados,
        "placares_exatos": placares_exatos,
        "resultados_corretos": (
            resultados_corretos
        ),
        "resultados_errados": (
            resultados_errados
        ),
        "palpites_pendentes": (
            palpites_pendentes
        ),
        "aproveitamento": aproveitamento,
    }

    return render_template(
        "perfil_participante.html",
        participante=participante_exibicao,
        estatisticas=estatisticas,
        historico=historico
    )


@app.route(
    "/participantes/<int:participante_id>/excluir",
    methods=["POST"]
)
def excluir_participante(
    participante_id: int
):
    dados = carregar_dados()

    participante = next(
        (
            item
            for item in dados["participantes"]
            if item["id"] == participante_id
        ),
        None
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger"
        )

        return redirect(
            url_for("listar_participantes")
        )

    quantidade_anterior = len(
        dados["palpites"]
    )

    dados["palpites"] = [
        palpite
        for palpite in dados["palpites"]
        if palpite["participante_id"]
        != participante_id
    ]

    palpites_removidos = (
        quantidade_anterior
        - len(dados["palpites"])
    )

    dados["participantes"] = [
        item
        for item in dados["participantes"]
        if item["id"] != participante_id
    ]

    salvar_dados(dados)

    flash(
        (
            f"Participante {participante['nome']} "
            f"excluído. {palpites_removidos} "
            "palpite(s) também foram removidos."
        ),
        "success"
    )

    return redirect(
        url_for("listar_participantes")
    )

if __name__ == "__main__":
    app.run(
        debug=True
    )