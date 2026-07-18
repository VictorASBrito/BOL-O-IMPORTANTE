import hmac
import os
import time
from functools import wraps
from threading import Lock
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)

from services.acesso_service import (
    AcessoInvalidoError,
    atualizar_senha_participante,
    obter_acesso_por_participante,
    obter_acesso_por_usuario,
)
from services.json_service import carregar_dados


auth_bp = Blueprint(
    "auth",
    __name__,
)

_MAX_TENTATIVAS = 5
_JANELA_SEGUNDOS = 10 * 60
_tentativas_por_chave: dict[
    tuple[str, str],
    list[float],
] = {}
_tentativas_lock = Lock()


def admin_esta_logado() -> bool:
    return (
        session.get("tipo_usuario")
        == "admin"
    )


def participante_esta_logado() -> bool:
    return (
        session.get("tipo_usuario")
        == "participante"
        and isinstance(
            session.get("participante_id"),
            int,
        )
    )


def admin_required(
    funcao: Callable[..., Any],
) -> Callable[..., Any]:
    @wraps(funcao)
    def funcao_protegida(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not admin_esta_logado():
            flash(
                (
                    "Entre como administrador "
                    "para fazer alterações."
                ),
                "warning",
            )

            return redirect(
                url_for(
                    "auth.login_admin",
                    next=request.url,
                )
            )

        return funcao(*args, **kwargs)

    return funcao_protegida


def usuario_required(
    funcao: Callable[..., Any],
) -> Callable[..., Any]:
    @wraps(funcao)
    def funcao_protegida(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not participante_esta_logado():
            flash(
                (
                    "Entre com sua conta de participante "
                    "para cadastrar seus palpites."
                ),
                "warning",
            )

            return redirect(
                url_for(
                    "auth.login_usuario",
                    next=request.url,
                )
            )

        return funcao(*args, **kwargs)

    return funcao_protegida


def _ip_atual() -> str:
    return request.remote_addr or "desconhecido"


def _chave_tentativa(
    tipo: str,
) -> tuple[str, str]:
    return (
        tipo,
        _ip_atual(),
    )


def _remover_tentativas_expiradas(
    chave: tuple[str, str],
) -> list[float]:
    limite = time.time() - _JANELA_SEGUNDOS

    with _tentativas_lock:
        tentativas = [
            instante
            for instante in _tentativas_por_chave.get(
                chave,
                [],
            )
            if instante >= limite
        ]

        _tentativas_por_chave[chave] = (
            tentativas
        )

        return tentativas


def _login_bloqueado(
    chave: tuple[str, str],
) -> bool:
    return (
        len(
            _remover_tentativas_expiradas(
                chave
            )
        )
        >= _MAX_TENTATIVAS
    )


def _registrar_falha(
    chave: tuple[str, str],
) -> None:
    with _tentativas_lock:
        _tentativas_por_chave.setdefault(
            chave,
            [],
        ).append(time.time())


def _limpar_falhas(
    chave: tuple[str, str],
) -> None:
    with _tentativas_lock:
        _tentativas_por_chave.pop(
            chave,
            None,
        )


def _url_interna_segura(
    destino: str,
) -> bool:
    if not destino:
        return False

    url_base = urlparse(
        request.host_url
    )

    url_destino = urlparse(
        urljoin(
            request.host_url,
            destino,
        )
    )

    return (
        url_destino.scheme
        in {"http", "https"}
        and url_base.netloc
        == url_destino.netloc
    )


def _senha_confere(
    senha_hash: str,
    senha: str,
) -> bool:
    if not senha_hash or not senha:
        return False

    try:
        return check_password_hash(
            senha_hash,
            senha,
        )
    except (ValueError, TypeError) as erro:
        current_app.logger.exception(
            "Hash de senha inválido.",
            exc_info=erro,
        )

        return False


def _destino_ou_padrao(
    destino: str,
    endpoint_padrao: str,
) -> str:
    if _url_interna_segura(destino):
        return destino

    return url_for(endpoint_padrao)


@auth_bp.route(
    "/login",
    methods=["GET", "POST"],
)
def login_usuario():
    proximo = request.values.get(
        "next",
        "",
    )

    if participante_esta_logado():
        return redirect(
            _destino_ou_padrao(
                proximo,
                "meus_palpites",
            )
        )

    if request.method == "POST":
        chave = _chave_tentativa(
            "participante"
        )

        if _login_bloqueado(chave):
            flash(
                (
                    "Muitas tentativas de login. "
                    "Aguarde alguns minutos."
                ),
                "danger",
            )

            return render_template(
                "login_usuario.html",
                proximo=proximo,
            ), 429

        usuario = request.form.get(
            "usuario",
            "",
        ).strip()

        senha = request.form.get(
            "senha",
            "",
        )

        acesso = obter_acesso_por_usuario(
            usuario
        )

        acesso_valido = (
            acesso is not None
            and acesso.get("ativo", False)
            and _senha_confere(
                acesso.get("senha_hash", ""),
                senha,
            )
        )

        participante = None

        if acesso_valido:
            dados = carregar_dados()

            participante = next(
                (
                    item
                    for item in dados[
                        "participantes"
                    ]
                    if item.get("id")
                    == acesso.get(
                        "participante_id"
                    )
                    and item.get(
                        "ativo",
                        True,
                    )
                ),
                None,
            )

        if acesso_valido and participante:
            _limpar_falhas(chave)

            session.clear()
            session["tipo_usuario"] = (
                "participante"
            )
            session["participante_id"] = (
                participante["id"]
            )
            session["participante_nome"] = (
                participante["nome"]
            )
            session["login_usuario"] = (
                acesso["usuario"]
            )
            session.permanent = True

            flash(
                (
                    f"Bem-vindo, "
                    f"{participante['nome']}!"
                ),
                "success",
            )

            return redirect(
                _destino_ou_padrao(
                    proximo,
                    "meus_palpites",
                )
            )

        _registrar_falha(chave)

        flash(
            "Usuário ou senha inválidos.",
            "danger",
        )

    return render_template(
        "login_usuario.html",
        proximo=proximo,
    )


@auth_bp.route(
    "/alterar-senha",
    methods=["GET", "POST"],
)
@usuario_required
def alterar_senha():
    participante_id = session[
        "participante_id"
    ]

    acesso = obter_acesso_por_participante(
        participante_id
    )

    if (
        acesso is None
        or not acesso.get(
            "ativo",
            False,
        )
    ):
        session.clear()

        flash(
            (
                "Seu acesso não está disponível. "
                "Procure o administrador do bolão."
            ),
            "danger",
        )

        return redirect(
            url_for(
                "auth.login_usuario"
            )
        )

    if request.method == "POST":
        senha_atual = request.form.get(
            "senha_atual",
            "",
        )

        nova_senha = request.form.get(
            "nova_senha",
            "",
        )

        confirmacao = request.form.get(
            "confirmacao_senha",
            "",
        )

        if not _senha_confere(
            acesso.get(
                "senha_hash",
                "",
            ),
            senha_atual,
        ):
            flash(
                "A senha atual está incorreta.",
                "danger",
            )

            return render_template(
                "alterar_senha.html"
            )

        if len(nova_senha) < 8:
            flash(
                (
                    "A nova senha precisa possuir "
                    "pelo menos 8 caracteres."
                ),
                "danger",
            )

            return render_template(
                "alterar_senha.html"
            )

        if nova_senha != confirmacao:
            flash(
                (
                    "A nova senha e a confirmação "
                    "não são iguais."
                ),
                "danger",
            )

            return render_template(
                "alterar_senha.html"
            )

        if _senha_confere(
            acesso.get(
                "senha_hash",
                "",
            ),
            nova_senha,
        ):
            flash(
                (
                    "A nova senha precisa ser "
                    "diferente da senha atual."
                ),
                "danger",
            )

            return render_template(
                "alterar_senha.html"
            )

        senha_hash = generate_password_hash(
            nova_senha,
            method="pbkdf2:sha256",
            salt_length=16,
        )

        try:
            atualizar_senha_participante(
                participante_id=(
                    participante_id
                ),
                senha_hash=senha_hash,
            )
        except AcessoInvalidoError as erro:
            flash(
                str(erro),
                "danger",
            )

            return render_template(
                "alterar_senha.html"
            )

        flash(
            (
                "Sua senha foi alterada "
                "com sucesso."
            ),
            "success",
        )

        return redirect(
            url_for(
                "meus_palpites"
            )
        )

    return render_template(
        "alterar_senha.html"
    )


@auth_bp.route(
    "/logout",
    methods=["POST"],
)
@usuario_required
def logout_usuario():
    session.clear()

    flash(
        "Você saiu da sua conta.",
        "success",
    )

    return redirect(
        url_for("dashboard")
    )


@auth_bp.route(
    "/admin/login",
    methods=["GET", "POST"],
)
def login_admin():
    proximo = request.values.get(
        "next",
        "",
    )

    if admin_esta_logado():
        return redirect(
            _destino_ou_padrao(
                proximo,
                "dashboard",
            )
        )

    if request.method == "POST":
        chave = _chave_tentativa(
            "admin"
        )

        if _login_bloqueado(chave):
            flash(
                (
                    "Muitas tentativas de login. "
                    "Aguarde alguns minutos."
                ),
                "danger",
            )

            return render_template(
                "login_admin.html",
                proximo=proximo,
            ), 429

        usuario = request.form.get(
            "usuario",
            "",
        ).strip()

        senha = request.form.get(
            "senha",
            "",
        )

        usuario_correto = os.getenv(
            "ADMIN_USERNAME",
            "",
        )

        senha_hash = os.getenv(
            "ADMIN_PASSWORD_HASH",
            "",
        )

        usuario_valido = (
            bool(usuario_correto)
            and hmac.compare_digest(
                usuario,
                usuario_correto,
            )
        )

        senha_valida = _senha_confere(
            senha_hash,
            senha,
        )

        if usuario_valido and senha_valida:
            _limpar_falhas(chave)

            session.clear()
            session["tipo_usuario"] = "admin"
            session["admin_usuario"] = (
                usuario_correto
            )
            session.permanent = True

            flash(
                (
                    "Login administrativo "
                    "realizado com sucesso."
                ),
                "success",
            )

            return redirect(
                _destino_ou_padrao(
                    proximo,
                    "dashboard",
                )
            )

        _registrar_falha(chave)

        flash(
            "Usuário ou senha inválidos.",
            "danger",
        )

    return render_template(
        "login_admin.html",
        proximo=proximo,
    )


@auth_bp.route(
    "/admin/logout",
    methods=["POST"],
)
@admin_required
def logout_admin():
    session.clear()

    flash(
        (
            "Você saiu da área "
            "administrativa."
        ),
        "success",
    )

    return redirect(
        url_for("dashboard")
    )
