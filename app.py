import os
import re
from datetime import timedelta
from typing import Any

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from auth import (
    admin_esta_logado,
    admin_required,
    auth_bp,
    participante_esta_logado,
    usuario_required,
)
from services.acesso_service import (
    AcessoInvalidoError,
    UsuarioDuplicadoError,
    obter_acesso_por_participante,
    remover_acesso_participante,
    salvar_acesso_participante,
)
from services.importacao_service import (
    importar_mensagem_whatsapp,
    normalizar_texto,
)
from services.json_service import (
    carregar_dados,
    executar_transacao,
    gerar_proximo_id,
    salvar_dados,
)
from services.pontuacao_service import (
    TIPO_JOGO_GRUPO,
    TIPO_JOGO_MATA_MATA,
    VENCEDOR_CASA,
    VENCEDOR_VISITANTE,
    calcular_pontos,
    jogo_e_mata_mata,
    montar_ranking,
    pontuacao_placar_exato,
)


load_dotenv()

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)

secret_key = os.getenv("SECRET_KEY", "").strip()
admin_username = os.getenv("ADMIN_USERNAME", "").strip()
admin_password_hash = os.getenv(
    "ADMIN_PASSWORD_HASH",
    "",
).strip()

if not secret_key:
    raise RuntimeError(
        "SECRET_KEY não configurada. Crie o arquivo .env."
    )

if not admin_username or not admin_password_hash:
    raise RuntimeError(
        "ADMIN_USERNAME ou ADMIN_PASSWORD_HASH não configurados no .env."
    )

app.config.update(
    SECRET_KEY=secret_key,
    NOME_SITE=os.getenv(
        "NOME_SITE",
        "Bolão da Copa",
    ).strip() or "Bolão da Copa",
    SESSION_COOKIE_NAME="bolao_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        os.getenv(
            "SESSION_COOKIE_SECURE",
            "false",
        ).lower()
        == "true"
    ),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    WTF_CSRF_TIME_LIMIT=8 * 60 * 60,
    MAX_CONTENT_LENGTH=1024 * 1024,
)

csrf = CSRFProtect(app)
app.register_blueprint(auth_bp)


@app.context_processor
def disponibilizar_contexto_global() -> dict[str, Any]:
    return {
        "nome_site": app.config["NOME_SITE"],
        "admin_logado": admin_esta_logado(),
        "participante_logado": (
            participante_esta_logado()
        ),
        "participante_logado_id": session.get(
            "participante_id"
        ),
        "participante_logado_nome": session.get(
            "participante_nome"
        ),
        "admin_usuario": session.get(
            "admin_usuario"
        ),
    }


@app.errorhandler(CSRFError)
def tratar_erro_csrf(erro: CSRFError):
    flash(
        (
            "A sessão do formulário expirou ou a "
            "requisição não é válida. Atualize a página "
            "e tente novamente."
        ),
        "danger",
    )

    return redirect(url_for("dashboard"))


@app.after_request
def adicionar_cabecalhos_seguranca(resposta):
    resposta.headers.setdefault(
        "X-Content-Type-Options",
        "nosniff",
    )

    resposta.headers.setdefault(
        "X-Frame-Options",
        "SAMEORIGIN",
    )

    resposta.headers.setdefault(
        "Referrer-Policy",
        "strict-origin-when-cross-origin",
    )

    resposta.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )

    resposta.headers.setdefault(
        "Content-Security-Policy",
        (
            "default-src 'self'; "
            "style-src 'self' "
            "https://cdn.jsdelivr.net 'unsafe-inline'; "
            "script-src 'self' "
            "https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src 'self' "
            "https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        ),
    )

    if request.is_secure:
        resposta.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

    return resposta


def converter_inteiro_form(nome_campo: str) -> int | None:
    valor = request.form.get(nome_campo, "").strip()

    if not valor.isdigit():
        return None

    return int(valor)


def tipo_jogo_form() -> str:
    tipo = request.form.get(
        "tipo_jogo",
        TIPO_JOGO_GRUPO,
    ).strip().upper()

    if tipo == TIPO_JOGO_MATA_MATA:
        return TIPO_JOGO_MATA_MATA

    return TIPO_JOGO_GRUPO


def vencedor_por_placar(
    gols_casa: int,
    gols_visitante: int,
) -> str | None:
    if gols_casa > gols_visitante:
        return VENCEDOR_CASA

    if gols_visitante > gols_casa:
        return VENCEDOR_VISITANTE

    return None


def vencedor_form_valido() -> str | None:
    vencedor = request.form.get(
        "vencedor",
        "",
    ).strip().upper()

    if vencedor in {
        VENCEDOR_CASA,
        VENCEDOR_VISITANTE,
    }:
        return vencedor

    return None


def vencedor_palpite_form(
    jogo: dict,
    gols_casa: int,
    gols_visitante: int,
) -> str | None:
    if not jogo_e_mata_mata(jogo):
        return None

    vencedor_placar = vencedor_por_placar(
        gols_casa,
        gols_visitante,
    )

    if vencedor_placar:
        return vencedor_placar

    vencedor = request.form.get(
        f"vencedor_{jogo['id']}",
        "",
    ).strip().upper()

    if vencedor in {
        VENCEDOR_CASA,
        VENCEDOR_VISITANTE,
    }:
        return vencedor

    return None


def calcular_pontos_do_palpite(
    palpite: dict,
    jogo: dict,
) -> int:
    return calcular_pontos(
        palpite["gols_casa"],
        palpite["gols_visitante"],
        jogo["gols_casa"],
        jogo["gols_visitante"],
        tipo_jogo=jogo.get("tipo_jogo"),
        palpite_vencedor=palpite.get("vencedor"),
        resultado_vencedor=jogo.get("vencedor"),
    )


def montar_vencedor_nome(
    jogo: dict,
    vencedor: str | None,
) -> str | None:
    if vencedor == VENCEDOR_CASA:
        return jogo.get("time_casa")

    if vencedor == VENCEDOR_VISITANTE:
        return jogo.get("time_visitante")

    return None


def separar_apelidos(
    texto: str,
    nome_principal: str,
) -> list[str]:
    apelidos: list[str] = []
    identificadores_adicionados: set[str] = set()

    nome_normalizado = normalizar_texto(nome_principal)

    partes = re.split(r"[,;\n]+", texto or "")

    for parte in partes:
        apelido = parte.strip()

        if not apelido:
            continue

        apelido_normalizado = normalizar_texto(apelido)

        if not apelido_normalizado:
            continue

        if apelido_normalizado == nome_normalizado:
            continue

        if apelido_normalizado in identificadores_adicionados:
            continue

        identificadores_adicionados.add(apelido_normalizado)
        apelidos.append(apelido)

    return apelidos


def obter_apelidos_participante(
    participante: dict,
) -> list[str]:
    apelidos: list[str] = []
    identificadores_adicionados: set[str] = set()

    nome_normalizado = normalizar_texto(
        participante.get("nome", "")
    )

    valores: list[str] = []

    apelido_antigo = participante.get("apelido", "")

    if apelido_antigo:
        valores.append(str(apelido_antigo))

    valores.extend(
        str(apelido)
        for apelido in participante.get("apelidos", [])
    )

    for valor in valores:
        apelido = valor.strip()

        if not apelido:
            continue

        apelido_normalizado = normalizar_texto(apelido)

        if apelido_normalizado == nome_normalizado:
            continue

        if apelido_normalizado in identificadores_adicionados:
            continue

        identificadores_adicionados.add(apelido_normalizado)
        apelidos.append(apelido)

    return apelidos


def obter_identificadores_participante(
    participante: dict,
) -> set[str]:
    identificadores = {
        normalizar_texto(
            participante.get("nome", "")
        )
    }

    for apelido in obter_apelidos_participante(participante):
        identificadores.add(normalizar_texto(apelido))

    identificadores.discard("")

    return identificadores


def verificar_identificador_em_uso(
    dados: dict,
    nome: str,
    apelidos: list[str],
    participante_ignorado_id: int | None = None,
) -> str | None:
    candidatos = {normalizar_texto(nome)}

    candidatos.update(
        normalizar_texto(apelido)
        for apelido in apelidos
    )

    candidatos.discard("")

    for participante in dados["participantes"]:
        if (
            participante_ignorado_id is not None
            and participante["id"] == participante_ignorado_id
        ):
            continue

        identificadores_existentes = (
            obter_identificadores_participante(participante)
        )

        if candidatos.intersection(identificadores_existentes):
            return participante["nome"]

    return None


def montar_contexto_palpites(
    resultado_importacao=None,
    permitir_fechados: bool = False,
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

    participante_sessao_id = session.get(
        "participante_id"
    )

    palpites_exibicao: list[dict] = []

    for palpite in dados["palpites"]:
        participante = participantes_por_id.get(
            palpite["participante_id"]
        )

        jogo = jogos_por_id.get(
            palpite["jogo_id"]
        )

        if not participante or not jogo:
            continue

        jogo_aberto = (
            jogo.get(
                "situacao",
                "ABERTO",
            )
            == "ABERTO"
        )

        pode_ver_palpite_aberto = (
            admin_esta_logado()
            or (
                participante_esta_logado()
                and participante_sessao_id
                == palpite["participante_id"]
            )
        )

        if (
            jogo_aberto
            and not pode_ver_palpite_aberto
        ):
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
            "rodada": jogo.get(
                "rodada",
                0,
            ),
            "situacao_jogo": jogo.get(
                "situacao",
                "ABERTO",
            ),
            "tipo_jogo": jogo.get(
                "tipo_jogo",
                TIPO_JOGO_GRUPO,
            ),
            "mata_mata": jogo_e_mata_mata(jogo),
            "vencedor": palpite.get("vencedor"),
            "vencedor_nome": montar_vencedor_nome(
                jogo,
                palpite.get("vencedor"),
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
        ].lower(),
    )

    jogos_ordenados = sorted(
        dados["jogos"],
        key=lambda jogo: (
            0
            if jogo.get(
                "situacao",
                "ABERTO",
            )
            == "ABERTO"
            else 1,
            jogo.get(
                "rodada",
                0,
            ),
            jogo.get(
                "data_hora",
                "",
            ),
            jogo["id"],
        ),
    )

    jogos_manuais: list[dict] = []

    for jogo_original in jogos_ordenados:
        situacao = jogo_original.get(
            "situacao",
            "ABERTO",
        )

        if situacao == "CANCELADO":
            continue

        jogos_manuais.append({
            **jogo_original,
            "fechado": situacao != "ABERTO",
        })

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
        quantidade_jogos=len(dados["jogos"]),
        quantidade_palpites=len(dados["palpites"]),
        jogos_abertos=jogos_abertos,
        jogos_finalizados=jogos_finalizados,
        lider=lider,
    )


@app.route("/participantes")
def listar_participantes():
    dados = carregar_dados()
    participantes: list[dict] = []

    for participante_original in dados["participantes"]:
        participantes.append({
            **participante_original,
            "apelidos_exibicao": (
                obter_apelidos_participante(
                    participante_original
                )
            ),
            "acesso": (
                obter_acesso_por_participante(
                    participante_original["id"]
                )
            ),
        })

    participantes.sort(
        key=lambda participante: participante["nome"].lower()
    )

    return render_template(
        "participantes.html",
        participantes=participantes,
    )


@app.route(
    "/participantes/<int:participante_id>/acesso",
    methods=["GET", "POST"],
)
@admin_required
def gerenciar_acesso_participante(
    participante_id: int,
):
    dados = carregar_dados()

    participante = next(
        (
            item
            for item in dados["participantes"]
            if item["id"] == participante_id
        ),
        None,
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger",
        )

        return redirect(
            url_for("listar_participantes")
        )

    acesso = obter_acesso_por_participante(
        participante_id
    )

    if request.method == "POST":
        usuario = request.form.get(
            "usuario",
            "",
        ).strip()

        senha = request.form.get(
            "senha",
            "",
        )

        confirmacao = request.form.get(
            "confirmacao_senha",
            "",
        )

        ativo = (
            request.form.get("ativo")
            == "1"
        )

        if not re.fullmatch(
            r"[A-Za-z0-9._-]{3,30}",
            usuario,
        ):
            flash(
                (
                    "O usuário deve possuir de 3 a "
                    "30 caracteres e usar somente "
                    "letras, números, ponto, hífen "
                    "ou sublinhado."
                ),
                "danger",
            )

            return render_template(
                "acesso_participante.html",
                participante=participante,
                acesso=acesso,
            )

        senha_hash = None

        if senha or confirmacao:
            if len(senha) < 8:
                flash(
                    (
                        "A senha precisa possuir "
                        "pelo menos 8 caracteres."
                    ),
                    "danger",
                )

                return render_template(
                    "acesso_participante.html",
                    participante=participante,
                    acesso=acesso,
                )

            if senha != confirmacao:
                flash(
                    (
                        "A senha e a confirmação "
                        "não são iguais."
                    ),
                    "danger",
                )

                return render_template(
                    "acesso_participante.html",
                    participante=participante,
                    acesso=acesso,
                )

            senha_hash = generate_password_hash(
                senha,
                method="pbkdf2:sha256",
                salt_length=16,
            )

        try:
            salvar_acesso_participante(
                participante_id=participante_id,
                usuario=usuario,
                senha_hash=senha_hash,
                ativo=ativo,
            )
        except (
            UsuarioDuplicadoError,
            AcessoInvalidoError,
        ) as erro:
            flash(
                str(erro),
                "danger",
            )

            return render_template(
                "acesso_participante.html",
                participante=participante,
                acesso=acesso,
            )

        flash(
            (
                f"Acesso de {participante['nome']} "
                "atualizado."
            ),
            "success",
        )

        return redirect(
            url_for(
                "gerenciar_acesso_participante",
                participante_id=participante_id,
            )
        )

    return render_template(
        "acesso_participante.html",
        participante=participante,
        acesso=acesso,
    )


@app.route(
    "/participantes/<int:participante_id>/acesso/remover",
    methods=["POST"],
)
@admin_required
def remover_acesso_usuario(
    participante_id: int,
):
    removido = remover_acesso_participante(
        participante_id
    )

    flash(
        (
            "Acesso removido."
            if removido
            else "Este participante não possuía acesso."
        ),
        (
            "success"
            if removido
            else "warning"
        ),
    )

    return redirect(
        url_for("listar_participantes")
    )


@app.route(
    "/participantes/adicionar",
    methods=["POST"],
)
@admin_required
def adicionar_participante():
    nome = request.form.get("nome", "").strip()
    apelidos_texto = request.form.get(
        "apelidos",
        "",
    ).strip()

    if not nome:
        flash(
            "O nome do participante é obrigatório.",
            "danger",
        )
        return redirect(url_for("listar_participantes"))

    dados = carregar_dados()
    apelidos = separar_apelidos(apelidos_texto, nome)

    participante_em_conflito = (
        verificar_identificador_em_uso(
            dados,
            nome,
            apelidos,
        )
    )

    if participante_em_conflito:
        flash(
            (
                "O nome ou um dos apelidos informados "
                f"já pertence a {participante_em_conflito}."
            ),
            "danger",
        )
        return redirect(url_for("listar_participantes"))

    dados["participantes"].append({
        "id": gerar_proximo_id(dados["participantes"]),
        "nome": nome,
        "apelidos": apelidos,
        "ativo": True,
    })

    salvar_dados(dados)

    flash(
        f"Participante {nome} adicionado.",
        "success",
    )

    return redirect(url_for("listar_participantes"))


@app.route(
    "/participantes/<int:participante_id>/apelidos",
    methods=["POST"],
)
@admin_required
def atualizar_apelidos(participante_id: int):
    dados = carregar_dados()

    participante = next(
        (
            item
            for item in dados["participantes"]
            if item["id"] == participante_id
        ),
        None,
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger",
        )
        return redirect(url_for("listar_participantes"))

    apelidos = separar_apelidos(
        request.form.get("apelidos", ""),
        participante["nome"],
    )

    participante_em_conflito = (
        verificar_identificador_em_uso(
            dados,
            participante["nome"],
            apelidos,
            participante_ignorado_id=participante_id,
        )
    )

    if participante_em_conflito:
        flash(
            (
                "Um dos apelidos informados já "
                f"pertence a {participante_em_conflito}."
            ),
            "danger",
        )
        return redirect(url_for("listar_participantes"))

    participante["apelidos"] = apelidos
    participante.pop("apelido", None)

    salvar_dados(dados)

    flash(
        f"Apelidos de {participante['nome']} atualizados.",
        "success",
    )

    return redirect(url_for("listar_participantes"))


@app.route(
    "/participantes/<int:participante_id>/excluir",
    methods=["POST"],
)
@admin_required
def excluir_participante(participante_id: int):
    dados = carregar_dados()

    participante = next(
        (
            item
            for item in dados["participantes"]
            if item["id"] == participante_id
        ),
        None,
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger",
        )
        return redirect(url_for("listar_participantes"))

    quantidade_anterior = len(dados["palpites"])

    dados["palpites"] = [
        palpite
        for palpite in dados["palpites"]
        if palpite["participante_id"] != participante_id
    ]

    palpites_removidos = (
        quantidade_anterior - len(dados["palpites"])
    )

    dados["participantes"] = [
        item
        for item in dados["participantes"]
        if item["id"] != participante_id
    ]

    salvar_dados(dados)
    remover_acesso_participante(
        participante_id
    )

    flash(
        (
            f"Participante {participante['nome']} "
            f"excluído. {palpites_removidos} "
            "palpite(s) também foram removidos."
        ),
        "success",
    )

    return redirect(url_for("listar_participantes"))


@app.route("/participantes/<int:participante_id>")
def perfil_participante(participante_id: int):
    dados = carregar_dados()

    participante = next(
        (
            item
            for item in dados["participantes"]
            if item["id"] == participante_id
        ),
        None,
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger",
        )
        return redirect(url_for("listar_participantes"))

    jogos_por_id = {
        jogo["id"]: jogo
        for jogo in dados["jogos"]
    }

    historico: list[dict] = []
    total_pontos = 0
    placares_exatos = 0
    resultados_corretos = 0
    resultados_errados = 0
    jogos_pontuados = 0
    pontuacao_maxima = 0
    palpites_pendentes = 0

    for palpite in dados["palpites"]:
        if palpite["participante_id"] != participante_id:
            continue

        jogo = jogos_por_id.get(palpite["jogo_id"])

        if jogo is None:
            continue

        resultado_definido = (
            jogo.get("gols_casa") is not None
            and jogo.get("gols_visitante") is not None
            and jogo.get("situacao") != "CANCELADO"
        )

        pontos = None

        if resultado_definido:
            pontos = calcular_pontos_do_palpite(
                palpite,
                jogo,
            )

            total_pontos += pontos
            jogos_pontuados += 1
            pontuacao_maxima += pontuacao_placar_exato(jogo)

            if pontos == pontuacao_placar_exato(jogo):
                placares_exatos += 1
            elif pontos == 1:
                resultados_corretos += 1
            else:
                resultados_errados += 1
        else:
            palpites_pendentes += 1

        palpite_visivel = (
            admin_esta_logado()
            or (
                participante_esta_logado()
                and session.get(
                    "participante_id"
                )
                == participante_id
            )
            or jogo.get(
                "situacao",
                "ABERTO",
            )
            != "ABERTO"
        )

        historico.append({
            "palpite_id": palpite["id"],
            "jogo_id": jogo["id"],
            "codigo": jogo["codigo"],
            "rodada": jogo.get("rodada", 0),
            "time_casa": jogo["time_casa"],
            "time_visitante": jogo["time_visitante"],
            "palpite_casa": palpite["gols_casa"],
            "palpite_visitante": palpite["gols_visitante"],
            "resultado_casa": jogo.get("gols_casa"),
            "resultado_visitante": jogo.get(
                "gols_visitante"
            ),
            "situacao": jogo.get(
                "situacao",
                "ABERTO",
            ),
            "data_hora": jogo.get("data_hora", ""),
            "pontos": pontos,
            "palpite_visivel": palpite_visivel,
            "tipo_jogo": jogo.get(
                "tipo_jogo",
                TIPO_JOGO_GRUPO,
            ),
            "mata_mata": jogo_e_mata_mata(jogo),
            "vencedor": jogo.get("vencedor"),
            "vencedor_nome": montar_vencedor_nome(
                jogo,
                jogo.get("vencedor"),
            ),
            "palpite_vencedor": palpite.get("vencedor"),
            "palpite_vencedor_nome": montar_vencedor_nome(
                jogo,
                palpite.get("vencedor"),
            ),
        })

    historico.sort(
        key=lambda item: (
            item["rodada"],
            item["jogo_id"],
        ),
        reverse=True,
    )

    ranking = montar_ranking(dados)

    classificacao = next(
        (
            item
            for item in ranking
            if item["participante_id"] == participante_id
        ),
        None,
    )

    aproveitamento = (
        round(
            total_pontos / pontuacao_maxima * 100,
            1,
        )
        if pontuacao_maxima > 0
        else 0
    )

    participante_exibicao = {
        **participante,
        "apelidos_exibicao": (
            obter_apelidos_participante(participante)
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
        "resultados_corretos": resultados_corretos,
        "resultados_errados": resultados_errados,
        "palpites_pendentes": palpites_pendentes,
        "aproveitamento": aproveitamento,
    }

    return render_template(
        "perfil_participante.html",
        participante=participante_exibicao,
        estatisticas=estatisticas,
        historico=historico,
    )


@app.route("/jogos")
def listar_jogos():
    dados = carregar_dados()

    for jogo in dados["jogos"]:
        jogo.setdefault(
            "tipo_jogo",
            TIPO_JOGO_GRUPO,
        )
        jogo.setdefault(
            "vencedor",
            None,
        )

    jogos_abertos = [
        jogo
        for jogo in dados["jogos"]
        if jogo.get("situacao", "ABERTO") == "ABERTO"
    ]

    jogos_fechados = [
        jogo
        for jogo in dados["jogos"]
        if jogo.get("situacao", "ABERTO") != "ABERTO"
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
        jogos_fechados=jogos_fechados,
    )


@app.route(
    "/jogos/adicionar",
    methods=["POST"],
)
@admin_required
def adicionar_jogo():
    dados = carregar_dados()

    rodada = converter_inteiro_form("rodada")
    time_casa = request.form.get("time_casa", "").strip()
    time_visitante = request.form.get(
        "time_visitante",
        "",
    ).strip()
    data_hora = request.form.get(
        "data_hora",
        "",
    ).strip()
    tipo_jogo = tipo_jogo_form()

    if rodada is None or rodada < 1:
        flash(
            "A rodada deve ser um número válido.",
            "danger",
        )
        return redirect(url_for("listar_jogos"))

    if not time_casa or not time_visitante:
        flash(
            "Os dois times são obrigatórios.",
            "danger",
        )
        return redirect(url_for("listar_jogos"))

    if (
        normalizar_texto(time_casa)
        == normalizar_texto(time_visitante)
    ):
        flash(
            "Os times do jogo devem ser diferentes.",
            "danger",
        )
        return redirect(url_for("listar_jogos"))

    proximo_id = gerar_proximo_id(dados["jogos"])

    dados["jogos"].append({
        "id": proximo_id,
        "codigo": f"J{proximo_id:02d}",
        "rodada": rodada,
        "time_casa": time_casa,
        "time_visitante": time_visitante,
        "data_hora": data_hora,
        "gols_casa": None,
        "gols_visitante": None,
        "situacao": "ABERTO",
        "tipo_jogo": tipo_jogo,
        "vencedor": None,
    })

    salvar_dados(dados)

    descricao_tipo = (
        "Mata-mata"
        if tipo_jogo == TIPO_JOGO_MATA_MATA
        else "Jogo normal"
    )

    flash(
        (
            f"Jogo {time_casa} x {time_visitante} "
            f"adicionado como {descricao_tipo}."
        ),
        "success",
    )

    return redirect(url_for("listar_jogos"))


@app.route(
    "/jogos/<int:jogo_id>/resultado",
    methods=["POST"],
)
@admin_required
def informar_resultado(jogo_id: int):
    gols_casa = converter_inteiro_form("gols_casa")
    gols_visitante = converter_inteiro_form(
        "gols_visitante"
    )

    if gols_casa is None or gols_visitante is None:
        flash(
            "Informe números válidos para o resultado final.",
            "danger",
        )
        return redirect(url_for("listar_jogos"))

    dados = carregar_dados()

    jogo = next(
        (
            item
            for item in dados["jogos"]
            if item["id"] == jogo_id
        ),
        None,
    )

    if jogo is None:
        flash(
            "Jogo não encontrado.",
            "danger",
        )
        return redirect(url_for("listar_jogos"))

    vencedor = None

    if jogo_e_mata_mata(jogo):
        vencedor = vencedor_por_placar(
            gols_casa,
            gols_visitante,
        )

        if vencedor is None:
            vencedor = vencedor_form_valido()

            if vencedor is None:
                flash(
                    (
                        "Em jogo mata-mata empatado, "
                        "selecione quem avançou."
                    ),
                    "danger",
                )
                return redirect(url_for("listar_jogos"))

    jogo["gols_casa"] = gols_casa
    jogo["gols_visitante"] = gols_visitante
    jogo["situacao"] = "FINALIZADO"
    jogo["vencedor"] = vencedor

    salvar_dados(dados)

    mensagem = (
        f"Resultado salvo: {jogo['time_casa']} "
        f"{gols_casa} x {gols_visitante} "
        f"{jogo['time_visitante']}."
    )

    vencedor_nome = montar_vencedor_nome(
        jogo,
        vencedor,
    )

    if vencedor_nome:
        mensagem += f" Classificado: {vencedor_nome}."

    flash(
        mensagem,
        "success",
    )

    return redirect(url_for("listar_jogos"))


@app.route(
    "/jogos/<int:jogo_id>/excluir",
    methods=["POST"],
)
@admin_required
def excluir_jogo(jogo_id: int):
    dados = carregar_dados()

    jogo = next(
        (
            item
            for item in dados["jogos"]
            if item["id"] == jogo_id
        ),
        None,
    )

    if jogo is None:
        flash(
            "Jogo não encontrado.",
            "danger",
        )
        return redirect(url_for("listar_jogos"))

    quantidade_anterior = len(dados["palpites"])

    dados["palpites"] = [
        palpite
        for palpite in dados["palpites"]
        if palpite["jogo_id"] != jogo_id
    ]

    palpites_removidos = (
        quantidade_anterior - len(dados["palpites"])
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
            f"{palpites_removidos} palpite(s) removido(s)."
        ),
        "success",
    )

    return redirect(url_for("listar_jogos"))


@app.route("/palpites")
def listar_palpites():
    permitir_fechados = (
        request.args.get(
            "permitir_fechados",
            "0",
        )
        == "1"
    )

    contexto = montar_contexto_palpites(
        permitir_fechados=permitir_fechados
    )

    return render_template(
        "palpites.html",
        **contexto,
    )


@app.route("/meus-palpites")
@usuario_required
def meus_palpites():
    participante_id = session[
        "participante_id"
    ]

    dados = carregar_dados()

    participante = next(
        (
            item
            for item in dados["participantes"]
            if item["id"] == participante_id
            and item.get("ativo", True)
        ),
        None,
    )

    if participante is None:
        session.clear()

        flash(
            (
                "Seu participante não está mais "
                "disponível. Entre novamente."
            ),
            "warning",
        )

        return redirect(
            url_for("auth.login_usuario")
        )

    palpites_por_jogo = {
        palpite["jogo_id"]: palpite
        for palpite in dados["palpites"]
        if palpite["participante_id"]
        == participante_id
    }

    jogos_abertos = []

    for jogo in sorted(
        dados["jogos"],
        key=lambda item: (
            item.get("rodada", 0),
            item.get("data_hora", ""),
            item["id"],
        ),
    ):
        if (
            jogo.get(
                "situacao",
                "ABERTO",
            )
            != "ABERTO"
        ):
            continue

        palpite = palpites_por_jogo.get(
            jogo["id"]
        )

        jogos_abertos.append({
            **jogo,
            "palpite_casa": (
                palpite.get("gols_casa")
                if palpite
                else None
            ),
            "palpite_visitante": (
                palpite.get(
                    "gols_visitante"
                )
                if palpite
                else None
            ),
            "palpite_vencedor": (
                palpite.get("vencedor")
                if palpite
                else None
            ),
            "mata_mata": jogo_e_mata_mata(jogo),
        })

    historico = []
    jogos_por_id = {
        jogo["id"]: jogo
        for jogo in dados["jogos"]
    }

    for palpite in dados["palpites"]:
        if (
            palpite["participante_id"]
            != participante_id
        ):
            continue

        jogo = jogos_por_id.get(
            palpite["jogo_id"]
        )

        if (
            not jogo
            or jogo.get(
                "situacao",
                "ABERTO",
            )
            == "ABERTO"
        ):
            continue

        pontos = None

        if (
            jogo.get("gols_casa")
            is not None
            and jogo.get(
                "gols_visitante"
            )
            is not None
            and jogo.get("situacao")
            != "CANCELADO"
        ):
            pontos = calcular_pontos_do_palpite(
                palpite,
                jogo,
            )

        historico.append({
            "codigo": jogo["codigo"],
            "rodada": jogo.get(
                "rodada",
                0,
            ),
            "time_casa": jogo[
                "time_casa"
            ],
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
                "ABERTO",
            ),
            "pontos": pontos,
            "tipo_jogo": jogo.get(
                "tipo_jogo",
                TIPO_JOGO_GRUPO,
            ),
            "mata_mata": jogo_e_mata_mata(jogo),
            "vencedor": jogo.get("vencedor"),
            "vencedor_nome": montar_vencedor_nome(
                jogo,
                jogo.get("vencedor"),
            ),
            "palpite_vencedor": palpite.get("vencedor"),
            "palpite_vencedor_nome": montar_vencedor_nome(
                jogo,
                palpite.get("vencedor"),
            ),
        })

    historico.sort(
        key=lambda item: (
            item["rodada"],
            item["codigo"],
        ),
        reverse=True,
    )

    return render_template(
        "meus_palpites.html",
        participante=participante,
        jogos_abertos=jogos_abertos,
        historico=historico,
    )


@app.route(
    "/meus-palpites/salvar",
    methods=["POST"],
)
@usuario_required
def salvar_meus_palpites():
    participante_id = session[
        "participante_id"
    ]

    def operacao(dados: dict) -> dict:
        participante = next(
            (
                item
                for item in dados[
                    "participantes"
                ]
                if item["id"]
                == participante_id
                and item.get(
                    "ativo",
                    True,
                )
            ),
            None,
        )

        if participante is None:
            return {
                "erro_conta": True,
                "criados": 0,
                "atualizados": 0,
                "erros": [],
            }

        palpites_por_jogo = {
            palpite["jogo_id"]: palpite
            for palpite in dados["palpites"]
            if palpite[
                "participante_id"
            ]
            == participante_id
        }

        criados = 0
        atualizados = 0
        erros = []

        for jogo in dados["jogos"]:
            if (
                jogo.get(
                    "situacao",
                    "ABERTO",
                )
                != "ABERTO"
            ):
                continue

            casa_texto = request.form.get(
                f"gols_casa_{jogo['id']}",
                "",
            ).strip()

            visitante_texto = request.form.get(
                f"gols_visitante_{jogo['id']}",
                "",
            ).strip()

            if (
                not casa_texto
                and not visitante_texto
            ):
                continue

            if (
                not casa_texto
                or not visitante_texto
                or not casa_texto.isdigit()
                or not visitante_texto.isdigit()
            ):
                erros.append(
                    (
                        f"{jogo['time_casa']} x "
                        f"{jogo['time_visitante']}: "
                        "preencha os dois gols "
                        "com números inteiros."
                    )
                )

                continue

            gols_casa = int(casa_texto)
            gols_visitante = int(
                visitante_texto
            )

            vencedor = vencedor_palpite_form(
                jogo,
                gols_casa,
                gols_visitante,
            )

            existente = palpites_por_jogo.get(
                jogo["id"]
            )

            if existente:
                existente[
                    "gols_casa"
                ] = gols_casa

                existente[
                    "gols_visitante"
                ] = gols_visitante
                existente["vencedor"] = vencedor

                atualizados += 1
            else:
                novo = {
                    "id": gerar_proximo_id(
                        dados["palpites"]
                    ),
                    "participante_id": (
                        participante_id
                    ),
                    "jogo_id": jogo["id"],
                    "gols_casa": gols_casa,
                    "gols_visitante": (
                        gols_visitante
                    ),
                    "vencedor": vencedor,
                }

                dados["palpites"].append(
                    novo
                )

                palpites_por_jogo[
                    jogo["id"]
                ] = novo

                criados += 1

        return {
            "erro_conta": False,
            "criados": criados,
            "atualizados": atualizados,
            "erros": erros,
        }

    resultado = executar_transacao(
        operacao
    )

    if resultado["erro_conta"]:
        session.clear()

        flash(
            "Sua conta não está mais disponível.",
            "danger",
        )

        return redirect(
            url_for("auth.login_usuario")
        )

    if (
        resultado["criados"] == 0
        and resultado["atualizados"]
        == 0
        and not resultado["erros"]
    ):
        flash(
            (
                "Nenhum palpite foi preenchido "
                "ou alterado."
            ),
            "warning",
        )
    elif (
        resultado["criados"] > 0
        or resultado["atualizados"] > 0
    ):
        flash(
            (
                f"{resultado['criados']} "
                "palpite(s) criado(s) e "
                f"{resultado['atualizados']} "
                "atualizado(s)."
            ),
            "success",
        )

    for erro in resultado["erros"]:
        flash(
            erro,
            "danger",
        )

    return redirect(
        url_for("meus_palpites")
    )


@app.route(
    "/palpites/adicionar",
    methods=["POST"],
)
@admin_required
def adicionar_palpite():
    participante_id = converter_inteiro_form(
        "participante_id"
    )

    permitir_fechados = (
        request.form.get(
            "permitir_jogos_fechados",
            "0",
        )
        == "1"
    )

    parametro_retorno = 1 if permitir_fechados else 0

    if participante_id is None:
        flash(
            "Selecione um participante.",
            "danger",
        )
        return redirect(
            url_for(
                "listar_palpites",
                permitir_fechados=parametro_retorno,
            )
        )

    dados = carregar_dados()

    participante = next(
        (
            item
            for item in dados["participantes"]
            if item["id"] == participante_id
        ),
        None,
    )

    if participante is None:
        flash(
            "Participante não encontrado.",
            "danger",
        )
        return redirect(
            url_for(
                "listar_palpites",
                permitir_fechados=parametro_retorno,
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
    erros: list[str] = []

    for jogo in dados["jogos"]:
        situacao = jogo.get("situacao", "ABERTO")

        if situacao == "CANCELADO":
            continue

        if (
            situacao != "ABERTO"
            and not permitir_fechados
        ):
            continue

        gols_casa_texto = request.form.get(
            f"gols_casa_{jogo['id']}",
            "",
        ).strip()

        gols_visitante_texto = request.form.get(
            f"gols_visitante_{jogo['id']}",
            "",
        ).strip()

        if not gols_casa_texto and not gols_visitante_texto:
            continue

        if not gols_casa_texto or not gols_visitante_texto:
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

        gols_casa = int(gols_casa_texto)
        gols_visitante = int(gols_visitante_texto)

        vencedor = vencedor_palpite_form(
            jogo,
            gols_casa,
            gols_visitante,
        )

        chave = (participante_id, jogo["id"])
        palpite_existente = palpites_por_chave.get(chave)

        if palpite_existente:
            palpite_existente["gols_casa"] = gols_casa
            palpite_existente[
                "gols_visitante"
            ] = gols_visitante
            palpite_existente["vencedor"] = vencedor
            palpites_atualizados += 1
        else:
            novo_palpite = {
                "id": gerar_proximo_id(dados["palpites"]),
                "participante_id": participante_id,
                "jogo_id": jogo["id"],
                "gols_casa": gols_casa,
                "gols_visitante": gols_visitante,
                "vencedor": vencedor,
            }

            dados["palpites"].append(novo_palpite)
            palpites_por_chave[chave] = novo_palpite
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
            "warning",
        )
        return redirect(
            url_for(
                "listar_palpites",
                permitir_fechados=parametro_retorno,
            )
        )

    if palpites_criados > 0 or palpites_atualizados > 0:
        salvar_dados(dados)

        flash(
            (
                f"{palpites_criados} palpite(s) "
                f"adicionado(s) e {palpites_atualizados} "
                "atualizado(s)."
            ),
            "success",
        )

    for erro in erros:
        flash(erro, "danger")

    return redirect(
        url_for(
            "listar_palpites",
            permitir_fechados=parametro_retorno,
        )
    )


@app.route(
    "/palpites/importar",
    methods=["POST"],
)
@admin_required
def importar_palpites():
    mensagem = request.form.get(
        "mensagem_whatsapp",
        "",
    ).strip()

    permitir_fechados = (
        request.form.get(
            "permitir_jogos_fechados",
            "0",
        )
        == "1"
    )

    if not mensagem:
        flash(
            (
                "Cole a mensagem do WhatsApp "
                "antes de importar."
            ),
            "warning",
        )
        return redirect(
            url_for(
                "listar_palpites",
                permitir_fechados=(
                    1 if permitir_fechados else 0
                ),
            )
        )

    dados = carregar_dados()

    resultado_importacao = importar_mensagem_whatsapp(
        mensagem,
        dados,
        permitir_jogos_fechados=permitir_fechados,
    )

    salvar_dados(dados)

    contexto = montar_contexto_palpites(
        resultado_importacao,
        permitir_fechados=permitir_fechados,
    )

    return render_template(
        "palpites.html",
        **contexto,
    )


@app.route(
    "/palpites/<int:palpite_id>/excluir",
    methods=["POST"],
)
@admin_required
def excluir_palpite(palpite_id: int):
    dados = carregar_dados()

    palpite = next(
        (
            item
            for item in dados["palpites"]
            if item["id"] == palpite_id
        ),
        None,
    )

    if palpite is None:
        flash(
            "Palpite não encontrado.",
            "danger",
        )
        return redirect(url_for("listar_palpites"))

    dados["palpites"] = [
        item
        for item in dados["palpites"]
        if item["id"] != palpite_id
    ]

    salvar_dados(dados)

    flash(
        "Palpite excluído.",
        "success",
    )

    return redirect(url_for("listar_palpites"))


@app.route("/ranking")
def exibir_ranking():
    dados = carregar_dados()
    ranking = montar_ranking(dados)

    return render_template(
        "ranking.html",
        ranking=ranking,
    )


if __name__ == "__main__":
    app.run(
        debug=(
            os.getenv(
                "FLASK_DEBUG",
                "false",
            ).lower()
            == "true"
        )
    )
