import re
import unicodedata
from typing import Any

from services.json_service import gerar_proximo_id


GRUPOS_ALIASES = {
    "republica tcheca": {
        "republica tcheca",
        "republica checa",
        "tcheca",
        "chequia",
    },
    "africa do sul": {
        "africa do sul",
        "africa sul",
        "africa",
    },
    "coreia do sul": {
        "coreia do sul",
        "coreia sul",
        "coreia",
    },
    "bosnia": {
        "bosnia",
        "bosnia e herzegovina",
    },
    "catar": {
        "catar",
        "qatar",
    },
}


PADRAO_PLACAR = re.compile(
    r"^(?P<time_1>.+?)\s+"
    r"(?P<gols_1>\d+)\s*"
    r"(?:a|x|-)\s*"
    r"(?P<gols_2>\d+)\s*"
    r"(?P<time_2>.+?)$",
    flags=re.IGNORECASE,
)


def normalizar_texto(valor: str) -> str:
    texto = unicodedata.normalize(
        "NFKD",
        valor or ""
    )

    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )

    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)

    return re.sub(r"\s+", " ", texto).strip()


MAPA_ALIASES = {
    normalizar_texto(alias): nome_canonico
    for nome_canonico, aliases in GRUPOS_ALIASES.items()
    for alias in aliases | {nome_canonico}
}


def normalizar_time(nome: str) -> str:
    nome_normalizado = normalizar_texto(nome)

    return MAPA_ALIASES.get(
        nome_normalizado,
        nome_normalizado
    )


def obter_identificadores_participante(
    participante: dict
) -> set[str]:
    identificadores = set()

    nome = participante.get("nome", "")

    if nome:
        identificadores.add(
            normalizar_texto(nome)
        )

    # Compatibilidade com o formato antigo.
    apelido_antigo = participante.get(
        "apelido",
        ""
    )

    if apelido_antigo:
        identificadores.add(
            normalizar_texto(apelido_antigo)
        )

    # Novo formato com vários apelidos.
    for apelido in participante.get(
        "apelidos",
        []
    ):
        if apelido:
            identificadores.add(
                normalizar_texto(apelido)
            )

    identificadores.discard("")

    return identificadores


def buscar_participante(
    dados: dict[str, Any],
    nome_informado: str
) -> dict | None:
    nome_normalizado = normalizar_texto(
        nome_informado
    )

    for participante in dados["participantes"]:
        identificadores = (
            obter_identificadores_participante(
                participante
            )
        )

        if nome_normalizado in identificadores:
            return participante

    return None


def criar_participante(
    dados: dict[str, Any],
    nome: str
) -> dict:
    participante = {
        "id": gerar_proximo_id(
            dados["participantes"]
        ),
        "nome": nome.strip(),
        "apelidos": [],
        "ativo": True,
    }

    dados["participantes"].append(
        participante
    )

    return participante


def buscar_jogo(
    dados: dict[str, Any],
    primeiro_time: str,
    segundo_time: str,
) -> tuple[dict | None, bool]:
    time_1 = normalizar_time(
        primeiro_time
    )

    time_2 = normalizar_time(
        segundo_time
    )

    for jogo in dados["jogos"]:
        time_casa = normalizar_time(
            jogo.get("time_casa", "")
        )

        time_visitante = normalizar_time(
            jogo.get("time_visitante", "")
        )

        if (
            time_1 == time_casa
            and time_2 == time_visitante
        ):
            return jogo, False

        if (
            time_1 == time_visitante
            and time_2 == time_casa
        ):
            return jogo, True

    return None, False


def importar_mensagem_whatsapp(
    mensagem: str,
    dados: dict[str, Any],
    permitir_jogos_fechados: bool = False,
) -> dict[str, Any]:
    resultado = {
        "participantes_criados": 0,
        "palpites_criados": 0,
        "palpites_atualizados": 0,
        "erros": [],
    }

    participante_atual = None

    palpites_por_chave = {
        (
            palpite["participante_id"],
            palpite["jogo_id"],
        ): palpite
        for palpite in dados["palpites"]
    }

    for numero_linha, linha_original in enumerate(
        mensagem.splitlines(),
        start=1,
    ):
        linha = linha_original.strip()

        if not linha:
            continue

        placar_encontrado = PADRAO_PLACAR.match(
            linha
        )

        if not placar_encontrado:
            if re.search(r"\d", linha):
                resultado["erros"].append(
                    (
                        f"Linha {numero_linha}: formato "
                        f"não reconhecido: {linha}"
                    )
                )

                continue

            participante_atual = buscar_participante(
                dados,
                linha
            )

            if participante_atual is None:
                participante_atual = criar_participante(
                    dados,
                    linha
                )

                resultado[
                    "participantes_criados"
                ] += 1

            continue

        if participante_atual is None:
            resultado["erros"].append(
                (
                    f"Linha {numero_linha}: informe o "
                    f"participante antes dos palpites."
                )
            )

            continue

        time_1 = placar_encontrado.group(
            "time_1"
        ).strip()

        time_2 = placar_encontrado.group(
            "time_2"
        ).strip()

        gols_1 = int(
            placar_encontrado.group("gols_1")
        )

        gols_2 = int(
            placar_encontrado.group("gols_2")
        )

        jogo, ordem_invertida = buscar_jogo(
            dados,
            time_1,
            time_2
        )

        if jogo is None:
            resultado["erros"].append(
                (
                    f"Linha {numero_linha}: jogo não "
                    f"encontrado: {time_1} x {time_2}."
                )
            )

            continue

        situacao_jogo = jogo.get(
            "situacao",
            "ABERTO"
        )

        if situacao_jogo == "CANCELADO":
            resultado["erros"].append(
                (
                    f"Linha {numero_linha}: o jogo "
                    f"{jogo['codigo']} está cancelado."
                )
            )

            continue

        if (
            situacao_jogo != "ABERTO"
            and not permitir_jogos_fechados
        ):
            resultado["erros"].append(
                (
                    f"Linha {numero_linha}: o jogo "
                    f"{jogo['codigo']} está fechado. "
                    "Ative a opção de permitir jogos "
                    "fechados para importar este palpite."
                )
            )

            continue

        if ordem_invertida:
            gols_casa = gols_2
            gols_visitante = gols_1
        else:
            gols_casa = gols_1
            gols_visitante = gols_2

        chave = (
            participante_atual["id"],
            jogo["id"],
        )

        palpite_existente = palpites_por_chave.get(
            chave
        )

        if palpite_existente:
            palpite_existente[
                "gols_casa"
            ] = gols_casa

            palpite_existente[
                "gols_visitante"
            ] = gols_visitante

            resultado[
                "palpites_atualizados"
            ] += 1

        else:
            novo_palpite = {
                "id": gerar_proximo_id(
                    dados["palpites"]
                ),
                "participante_id": participante_atual[
                    "id"
                ],
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

            resultado[
                "palpites_criados"
            ] += 1

    return resultado