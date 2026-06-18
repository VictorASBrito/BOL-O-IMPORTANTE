import hmac
import os
import time
from functools import wraps
from threading import Lock
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/admin",
)

_MAX_TENTATIVAS = 5
_JANELA_SEGUNDOS = 10 * 60
_tentativas_por_ip: dict[str, list[float]] = {}
_tentativas_lock = Lock()


def admin_esta_logado() -> bool:
    return bool(
        session.get(
            "admin_logado",
            False,
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
                    "auth.login",
                    next=request.url,
                )
            )

        return funcao(*args, **kwargs)

    return funcao_protegida


def _ip_atual() -> str:
    return request.remote_addr or "desconhecido"


def _remover_tentativas_expiradas(
    ip: str,
) -> list[float]:
    agora = time.time()
    limite = agora - _JANELA_SEGUNDOS

    with _tentativas_lock:
        tentativas = [
            instante
            for instante in _tentativas_por_ip.get(ip, [])
            if instante >= limite
        ]

        _tentativas_por_ip[ip] = tentativas
        return tentativas


def _login_bloqueado(ip: str) -> bool:
    return (
        len(_remover_tentativas_expiradas(ip))
        >= _MAX_TENTATIVAS
    )


def _registrar_falha(ip: str) -> None:
    with _tentativas_lock:
        _tentativas_por_ip.setdefault(
            ip,
            [],
        ).append(time.time())


def _limpar_falhas(ip: str) -> None:
    with _tentativas_lock:
        _tentativas_por_ip.pop(ip, None)


def _url_interna_segura(destino: str) -> bool:
    if not destino:
        return False

    url_base = urlparse(request.host_url)

    url_destino = urlparse(
        urljoin(
            request.host_url,
            destino,
        )
    )

    return (
        url_destino.scheme in {"http", "https"}
        and url_base.netloc == url_destino.netloc
    )


@auth_bp.route(
    "/login",
    methods=["GET", "POST"],
)
def login():
    proximo = request.values.get("next", "")

    if admin_esta_logado():
        return redirect(
            proximo
            if _url_interna_segura(proximo)
            else url_for("dashboard")
        )

    if request.method == "POST":
        ip = _ip_atual()

        if _login_bloqueado(ip):
            flash(
                (
                    "Muitas tentativas de login. "
                    "Aguarde alguns minutos."
                ),
                "danger",
            )

            return render_template(
                "login.html",
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

        senha_valida = (
            bool(senha_hash)
            and bool(senha)
            and check_password_hash(
                senha_hash,
                senha,
            )
        )

        if usuario_valido and senha_valida:
            _limpar_falhas(ip)

            session.clear()
            session["admin_logado"] = True
            session["admin_usuario"] = usuario_correto
            session.permanent = True

            flash(
                (
                    "Login administrativo "
                    "realizado com sucesso."
                ),
                "success",
            )

            return redirect(
                proximo
                if _url_interna_segura(proximo)
                else url_for("dashboard")
            )

        _registrar_falha(ip)

        flash(
            "Usuário ou senha inválidos.",
            "danger",
        )

    return render_template(
        "login.html",
        proximo=proximo,
    )


@auth_bp.route(
    "/logout",
    methods=["POST"],
)
@admin_required
def logout():
    session.clear()

    flash(
        "Você saiu da área administrativa.",
        "success",
    )

    return redirect(url_for("dashboard"))
