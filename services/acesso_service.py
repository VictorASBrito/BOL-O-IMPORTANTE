import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any


PASTA_RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_ACESSOS = PASTA_RAIZ / "data" / "acessos.json"

_lock_acessos = RLock()


class UsuarioDuplicadoError(ValueError):
    pass


class AcessoInvalidoError(ValueError):
    pass


def _estrutura_padrao() -> dict[str, list[dict[str, Any]]]:
    return {
        "acessos": [],
    }


def _normalizar_usuario(usuario: str) -> str:
    return str(usuario or "").strip().casefold()


def _ler_sem_lock() -> dict[str, list[dict[str, Any]]]:
    CAMINHO_ACESSOS.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not CAMINHO_ACESSOS.exists():
        return _estrutura_padrao()

    try:
        with CAMINHO_ACESSOS.open(
            "r",
            encoding="utf-8",
        ) as arquivo:
            dados = json.load(arquivo)
    except json.JSONDecodeError as erro:
        raise RuntimeError(
            (
                "O arquivo data/acessos.json está "
                "corrompido ou possui JSON inválido."
            )
        ) from erro

    if not isinstance(dados, dict):
        return _estrutura_padrao()

    acessos = dados.get("acessos", [])

    if not isinstance(acessos, list):
        acessos = []

    return {
        "acessos": acessos,
    }


def _salvar_sem_lock(
    dados: dict[str, list[dict[str, Any]]],
) -> None:
    CAMINHO_ACESSOS.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    descritor, caminho_temporario = (
        tempfile.mkstemp(
            prefix="acessos_",
            suffix=".tmp",
            dir=str(CAMINHO_ACESSOS.parent),
        )
    )

    try:
        with os.fdopen(
            descritor,
            "w",
            encoding="utf-8",
        ) as arquivo:
            json.dump(
                dados,
                arquivo,
                ensure_ascii=False,
                indent=2,
            )

            arquivo.flush()
            os.fsync(
                arquivo.fileno()
            )

        os.replace(
            caminho_temporario,
            CAMINHO_ACESSOS,
        )
    finally:
        if os.path.exists(caminho_temporario):
            os.remove(caminho_temporario)


def carregar_acessos() -> list[dict[str, Any]]:
    with _lock_acessos:
        return list(
            _ler_sem_lock()["acessos"]
        )


def obter_acesso_por_usuario(
    usuario: str,
) -> dict[str, Any] | None:
    usuario_normalizado = _normalizar_usuario(
        usuario
    )

    if not usuario_normalizado:
        return None

    with _lock_acessos:
        for acesso in _ler_sem_lock()["acessos"]:
            if (
                _normalizar_usuario(
                    acesso.get("usuario", "")
                )
                == usuario_normalizado
            ):
                return dict(acesso)

    return None


def obter_acesso_por_participante(
    participante_id: int,
) -> dict[str, Any] | None:
    with _lock_acessos:
        for acesso in _ler_sem_lock()["acessos"]:
            if (
                acesso.get("participante_id")
                == participante_id
            ):
                return dict(acesso)

    return None


def salvar_acesso_participante(
    participante_id: int,
    usuario: str,
    senha_hash: str | None,
    ativo: bool,
) -> dict[str, Any]:
    usuario = str(usuario or "").strip()
    usuario_normalizado = _normalizar_usuario(
        usuario
    )

    if not usuario_normalizado:
        raise AcessoInvalidoError(
            "O nome de usuário é obrigatório."
        )

    with _lock_acessos:
        dados = _ler_sem_lock()
        acessos = dados["acessos"]

        acesso_atual = next(
            (
                acesso
                for acesso in acessos
                if acesso.get("participante_id")
                == participante_id
            ),
            None,
        )

        for acesso in acessos:
            if (
                acesso.get("participante_id")
                == participante_id
            ):
                continue

            if (
                _normalizar_usuario(
                    acesso.get("usuario", "")
                )
                == usuario_normalizado
            ):
                raise UsuarioDuplicadoError(
                    (
                        "Este nome de usuário já está "
                        "vinculado a outro participante."
                    )
                )

        if acesso_atual is None:
            if not senha_hash:
                raise AcessoInvalidoError(
                    (
                        "Informe uma senha para criar "
                        "o primeiro acesso."
                    )
                )

            acesso_atual = {
                "participante_id": participante_id,
            }

            acessos.append(acesso_atual)

        acesso_atual["usuario"] = usuario
        acesso_atual["ativo"] = bool(ativo)

        if senha_hash:
            acesso_atual["senha_hash"] = senha_hash

        if not acesso_atual.get("senha_hash"):
            raise AcessoInvalidoError(
                "O acesso precisa possuir uma senha."
            )

        _salvar_sem_lock(dados)

        return dict(acesso_atual)


def atualizar_senha_participante(
    participante_id: int,
    senha_hash: str,
) -> dict[str, Any]:
    if not senha_hash:
        raise AcessoInvalidoError(
            "A nova senha não pode ficar vazia."
        )

    with _lock_acessos:
        dados = _ler_sem_lock()

        acesso = next(
            (
                item
                for item in dados["acessos"]
                if item.get("participante_id")
                == participante_id
            ),
            None,
        )

        if acesso is None:
            raise AcessoInvalidoError(
                "Acesso do participante não encontrado."
            )

        acesso["senha_hash"] = senha_hash

        _salvar_sem_lock(dados)

        return dict(acesso)


def remover_acesso_participante(
    participante_id: int,
) -> bool:
    with _lock_acessos:
        dados = _ler_sem_lock()
        quantidade_anterior = len(
            dados["acessos"]
        )

        dados["acessos"] = [
            acesso
            for acesso in dados["acessos"]
            if acesso.get("participante_id")
            != participante_id
        ]

        removido = (
            len(dados["acessos"])
            != quantidade_anterior
        )

        if removido:
            _salvar_sem_lock(dados)

        return removido
