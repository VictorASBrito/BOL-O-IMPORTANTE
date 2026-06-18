import json
import os
import tempfile
import threading
from copy import deepcopy
from typing import Any


CAMINHO_ARQUIVO = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "bolao.json"
)

_lock = threading.RLock()

ESTRUTURA_INICIAL = {
    "participantes": [],
    "jogos": [],
    "palpites": []
}


def inicializar_arquivo() -> None:
    diretorio = os.path.dirname(CAMINHO_ARQUIVO)

    os.makedirs(diretorio, exist_ok=True)

    if not os.path.exists(CAMINHO_ARQUIVO):
        salvar_dados(deepcopy(ESTRUTURA_INICIAL))


def carregar_dados() -> dict[str, Any]:
    inicializar_arquivo()

    with _lock:
        try:
            with open(
                CAMINHO_ARQUIVO,
                "r",
                encoding="utf-8"
            ) as arquivo:
                dados = json.load(arquivo)

        except json.JSONDecodeError as erro:
            raise ValueError(
                "O arquivo bolao.json possui um JSON inválido."
            ) from erro

        dados.setdefault("participantes", [])
        dados.setdefault("jogos", [])
        dados.setdefault("palpites", [])

        return dados


def salvar_dados(dados: dict[str, Any]) -> None:
    diretorio = os.path.dirname(CAMINHO_ARQUIVO)

    os.makedirs(diretorio, exist_ok=True)

    with _lock:
        caminho_temporario = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=diretorio,
                delete=False,
                suffix=".json"
            ) as arquivo_temporario:
                caminho_temporario = arquivo_temporario.name

                json.dump(
                    dados,
                    arquivo_temporario,
                    ensure_ascii=False,
                    indent=4
                )

            os.replace(
                caminho_temporario,
                CAMINHO_ARQUIVO
            )

        except OSError:
            if (
                caminho_temporario
                and os.path.exists(caminho_temporario)
            ):
                os.remove(caminho_temporario)

            raise


def gerar_proximo_id(registros: list[dict]) -> int:
    if not registros:
        return 1

    return max(
        registro.get("id", 0)
        for registro in registros
    ) + 1