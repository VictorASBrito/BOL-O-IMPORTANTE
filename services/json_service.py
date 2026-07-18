import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any, Callable, TypeVar


PASTA_RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_ARQUIVO = PASTA_RAIZ / "data" / "bolao.json"

_lock_dados = RLock()
T = TypeVar("T")


def _estrutura_padrao() -> dict[str, list[dict[str, Any]]]:
    return {
        "participantes": [],
        "jogos": [],
        "palpites": [],
    }


def _normalizar_estrutura(
    dados: Any,
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(dados, dict):
        dados = {}

    estrutura = _estrutura_padrao()

    for chave in estrutura:
        valor = dados.get(chave, [])

        estrutura[chave] = (
            valor
            if isinstance(valor, list)
            else []
        )

    return estrutura


def _ler_sem_lock() -> dict[str, list[dict[str, Any]]]:
    CAMINHO_ARQUIVO.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not CAMINHO_ARQUIVO.exists():
        dados = _estrutura_padrao()
        _salvar_sem_lock(dados)
        return dados

    try:
        with CAMINHO_ARQUIVO.open(
            "r",
            encoding="utf-8",
        ) as arquivo:
            return _normalizar_estrutura(
                json.load(arquivo)
            )
    except json.JSONDecodeError as erro:
        raise RuntimeError(
            (
                "O arquivo data/bolao.json está "
                "corrompido ou possui JSON inválido."
            )
        ) from erro


def _salvar_sem_lock(
    dados: dict[str, list[dict[str, Any]]],
) -> None:
    CAMINHO_ARQUIVO.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    dados = _normalizar_estrutura(dados)

    descritor, caminho_temporario = (
        tempfile.mkstemp(
            prefix="bolao_",
            suffix=".tmp",
            dir=str(CAMINHO_ARQUIVO.parent),
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
            CAMINHO_ARQUIVO,
        )
    finally:
        if os.path.exists(caminho_temporario):
            os.remove(caminho_temporario)


def carregar_dados() -> dict[str, list[dict[str, Any]]]:
    with _lock_dados:
        return _ler_sem_lock()


def salvar_dados(
    dados: dict[str, list[dict[str, Any]]],
) -> None:
    with _lock_dados:
        _salvar_sem_lock(dados)


def executar_transacao(
    operacao: Callable[
        [dict[str, list[dict[str, Any]]]],
        T,
    ],
) -> T:
    """
    Executa leitura, alteração e gravação sob o
    mesmo bloqueio.

    Isso evita que dois jogadores salvem ao mesmo
    tempo e um sobrescreva o palpite do outro.
    """

    with _lock_dados:
        dados = _ler_sem_lock()
        resultado = operacao(dados)
        _salvar_sem_lock(dados)
        return resultado


def gerar_proximo_id(
    itens: list[dict[str, Any]],
) -> int:
    if not itens:
        return 1

    return max(
        int(item.get("id", 0))
        for item in itens
    ) + 1
