import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from services.pontuacao_service import (
    TIPO_JOGO_GRUPO,
    TIPO_JOGO_MATA_MATA,
    VENCEDOR_CASA,
    VENCEDOR_VISITANTE,
    jogo_e_mata_mata,
)


@dataclass
class ResultadoImportacao:
    participantes_criados: int = 0
    palpites_criados: int = 0
    palpites_atualizados: int = 0
    erros: list[str] = field(default_factory=list)


@dataclass
class LinhaPalpite:
    time_1: str
    gols_1: int
    gols_2: int
    time_2: str


@dataclass
class JogoEncontrado:
    jogo: dict[str, Any]
    invertido: bool


@dataclass
class PalpitePendente:
    participante: dict[str, Any]
    jogo: dict[str, Any]
    palpite: dict[str, Any]
    linha_origem: str


PADRAO_PLACAR = re.compile(
    r"^(.+?)\s+(\d+)\s*(?:a|x|X|-)\s*(\d+)\s*(.+?)\s*$",
    re.IGNORECASE,
)

PADRAO_PASSA = re.compile(
    r"""
    ^\s*(?:(?:quem\s+)?passa|classificado|classifica|avanca|avança)\s*[:\-]\s*(.+?)\s*[.!?]*\s*$
    |
    ^\s*(.+?)\s+(?:passa|passou|classifica|classificou|avanca|avança|avancou|avançou)\s*[.!?]*\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalizar_texto(texto: str) -> str:
    texto = str(texto or "").strip().lower()

    texto = unicodedata.normalize(
        "NFD",
        texto,
    )

    texto = "".join(
        caractere
        for caractere in texto
        if unicodedata.category(caractere) != "Mn"
    )

    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    substituicoes = {
        "coréia": "coreia",
        "republica checa": "republica tcheca",
        "tchequia": "republica tcheca",
        "chequia": "republica tcheca",
        "africa sul": "africa do sul",
        "catar": "qatar",
        "rd congo": "dr congo",
        "r d congo": "dr congo",
        "congo rd": "dr congo",
        "congo dr": "dr congo",
    }

    return substituicoes.get(texto, texto)


def gerar_proximo_id(itens: list[dict[str, Any]]) -> int:
    if not itens:
        return 1

    return max(
        int(item.get("id", 0))
        for item in itens
    ) + 1


def obter_apelidos_participante(participante: dict[str, Any]) -> list[str]:
    apelidos = []

    if participante.get("apelido"):
        apelidos.append(str(participante["apelido"]))

    apelidos.extend(
        str(apelido)
        for apelido in participante.get("apelidos", [])
        if str(apelido).strip()
    )

    return apelidos


def identificadores_participante(participante: dict[str, Any]) -> set[str]:
    identificadores = {
        normalizar_texto(
            participante.get("nome", "")
        )
    }

    identificadores.update(
        normalizar_texto(apelido)
        for apelido in obter_apelidos_participante(participante)
    )

    identificadores.discard("")

    return identificadores


def obter_ou_criar_participante(
    nome: str,
    dados: dict[str, list[dict[str, Any]]],
    resultado: ResultadoImportacao,
) -> dict[str, Any]:
    nome_normalizado = normalizar_texto(nome)

    for participante in dados["participantes"]:
        if nome_normalizado in identificadores_participante(participante):
            return participante

    participante = {
        "id": gerar_proximo_id(dados["participantes"]),
        "nome": nome.strip(),
        "apelidos": [],
        "ativo": True,
    }

    dados["participantes"].append(participante)
    resultado.participantes_criados += 1

    return participante


def pontuar_nome_time(nome_informado: str, nome_oficial: str) -> int:
    informado = normalizar_texto(nome_informado)
    oficial = normalizar_texto(nome_oficial)

    if not informado or not oficial:
        return 0

    if informado == oficial:
        return 100

    if informado in oficial or oficial in informado:
        return 85

    tokens_informado = set(informado.split())
    tokens_oficial = set(oficial.split())

    if tokens_informado and tokens_informado.issubset(tokens_oficial):
        return 75

    if tokens_informado and tokens_oficial and tokens_informado == tokens_oficial:
        return 70

    if (
        tokens_informado
        and tokens_oficial
        and max(len(token) for token in tokens_informado) >= 4
        and tokens_informado.intersection(tokens_oficial)
    ):
        return 45

    return 0


def nome_time_combina(nome_informado: str, nome_oficial: str) -> bool:
    return pontuar_nome_time(nome_informado, nome_oficial) >= 70


def parse_linha_palpite(linha: str) -> LinhaPalpite | None:
    match = PADRAO_PLACAR.match(linha.strip())

    if not match:
        return None

    return LinhaPalpite(
        time_1=match.group(1).strip(),
        gols_1=int(match.group(2)),
        gols_2=int(match.group(3)),
        time_2=match.group(4).strip(),
    )


def parse_linha_passa(linha: str) -> str | None:
    match = PADRAO_PASSA.match(linha.strip())

    if not match:
        return None

    # O regex aceita tanto "Canadá passa" quanto
    # "Passa: Canadá". Apenas um dos grupos será preenchido.
    return (match.group(1) or match.group(2) or "").strip()


def linha_e_indicacao_de_classificado(linha: str) -> bool:
    """
    Proteção extra: qualquer linha com cara de "time passa"
    nunca deve cair no fluxo de criação de participante.
    """

    return parse_linha_passa(linha) is not None


def jogos_disponiveis(
    dados: dict[str, list[dict[str, Any]]],
    permitir_jogos_fechados: bool,
) -> list[dict[str, Any]]:
    jogos = []

    for jogo in dados["jogos"]:
        situacao = jogo.get("situacao", "ABERTO")

        if situacao == "CANCELADO":
            continue

        if situacao != "ABERTO" and not permitir_jogos_fechados:
            continue

        jogos.append(jogo)

    jogos.sort(
        key=lambda item: (
            0 if item.get("situacao", "ABERTO") == "ABERTO" else 1,
            item.get("rodada", 0),
            item.get("data_hora", ""),
            item.get("id", 0),
        )
    )

    return jogos


def encontrar_jogo(
    linha_palpite: LinhaPalpite,
    dados: dict[str, list[dict[str, Any]]],
    permitir_jogos_fechados: bool,
) -> JogoEncontrado | None:
    candidatos = []

    for jogo in jogos_disponiveis(
        dados,
        permitir_jogos_fechados,
    ):
        casa = jogo.get("time_casa", "")
        visitante = jogo.get("time_visitante", "")

        direto = (
            pontuar_nome_time(linha_palpite.time_1, casa)
            + pontuar_nome_time(linha_palpite.time_2, visitante)
        )

        invertido = (
            pontuar_nome_time(linha_palpite.time_1, visitante)
            + pontuar_nome_time(linha_palpite.time_2, casa)
        )

        if direto >= 140:
            candidatos.append((direto, jogo, False))

        if invertido >= 140:
            candidatos.append((invertido, jogo, True))

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda item: (
            -item[0],
            0 if item[1].get("situacao", "ABERTO") == "ABERTO" else 1,
            item[1].get("rodada", 0),
            item[1].get("data_hora", ""),
            item[1].get("id", 0),
        )
    )

    melhor = candidatos[0]

    return JogoEncontrado(
        jogo=melhor[1],
        invertido=melhor[2],
    )


def identificar_lado_time_no_jogo(
    nome_time: str,
    jogo: dict[str, Any],
) -> str | None:
    if nome_time_combina(
        nome_time,
        jogo.get("time_casa", ""),
    ):
        return VENCEDOR_CASA

    if nome_time_combina(
        nome_time,
        jogo.get("time_visitante", ""),
    ):
        return VENCEDOR_VISITANTE

    return None


def vencedor_por_placar(
    gols_casa: int,
    gols_visitante: int,
) -> str | None:
    if gols_casa > gols_visitante:
        return VENCEDOR_CASA

    if gols_visitante > gols_casa:
        return VENCEDOR_VISITANTE

    return None


def salvar_palpite(
    participante: dict[str, Any],
    jogo: dict[str, Any],
    gols_casa: int,
    gols_visitante: int,
    vencedor: str | None,
    dados: dict[str, list[dict[str, Any]]],
    resultado: ResultadoImportacao,
) -> dict[str, Any]:
    existente = next(
        (
            palpite
            for palpite in dados["palpites"]
            if palpite.get("participante_id") == participante["id"]
            and palpite.get("jogo_id") == jogo["id"]
        ),
        None,
    )

    if existente:
        existente["gols_casa"] = gols_casa
        existente["gols_visitante"] = gols_visitante

        if jogo_e_mata_mata(jogo):
            existente["vencedor"] = vencedor
        else:
            existente.pop("vencedor", None)

        resultado.palpites_atualizados += 1
        return existente

    novo_palpite = {
        "id": gerar_proximo_id(dados["palpites"]),
        "participante_id": participante["id"],
        "jogo_id": jogo["id"],
        "gols_casa": gols_casa,
        "gols_visitante": gols_visitante,
    }

    if jogo_e_mata_mata(jogo):
        novo_palpite["vencedor"] = vencedor

    dados["palpites"].append(novo_palpite)
    resultado.palpites_criados += 1

    return novo_palpite


def erro_pendente_sem_vencedor(
    pendente: PalpitePendente | None,
    resultado: ResultadoImportacao,
) -> None:
    if not pendente:
        return

    resultado.erros.append(
        (
            f"{pendente.participante['nome']}: o palpite "
            f"'{pendente.linha_origem}' terminou empatado em jogo mata-mata, "
            "mas não foi informado quem passa. Use uma linha como "
            f"'{pendente.jogo['time_casa']} passa' ou "
            f"'{pendente.jogo['time_visitante']} passa'."
        )
    )


def importar_mensagem_whatsapp(
    mensagem: str,
    dados: dict[str, list[dict[str, Any]]],
    permitir_jogos_fechados: bool = False,
) -> ResultadoImportacao:
    resultado = ResultadoImportacao()

    participante_atual: dict[str, Any] | None = None
    palpite_pendente: PalpitePendente | None = None

    linhas = [
        linha.strip()
        for linha in str(mensagem or "").splitlines()
    ]

    for numero_linha, linha in enumerate(linhas, start=1):
        if not linha:
            continue

        linha_palpite = parse_linha_palpite(linha)
        time_que_passa = parse_linha_passa(linha)

        if linha_palpite:
            if participante_atual is None:
                resultado.erros.append(
                    f"Linha {numero_linha}: palpite sem participante antes: '{linha}'."
                )
                continue

            erro_pendente_sem_vencedor(
                palpite_pendente,
                resultado,
            )
            palpite_pendente = None

            jogo_encontrado = encontrar_jogo(
                linha_palpite,
                dados,
                permitir_jogos_fechados,
            )

            if not jogo_encontrado:
                resultado.erros.append(
                    f"{participante_atual['nome']}: jogo não encontrado para a linha '{linha}'."
                )
                continue

            jogo = jogo_encontrado.jogo

            if jogo_encontrado.invertido:
                gols_casa = linha_palpite.gols_2
                gols_visitante = linha_palpite.gols_1
            else:
                gols_casa = linha_palpite.gols_1
                gols_visitante = linha_palpite.gols_2

            vencedor = None

            if jogo_e_mata_mata(jogo):
                vencedor = vencedor_por_placar(
                    gols_casa,
                    gols_visitante,
                )

            palpite = salvar_palpite(
                participante=participante_atual,
                jogo=jogo,
                gols_casa=gols_casa,
                gols_visitante=gols_visitante,
                vencedor=vencedor,
                dados=dados,
                resultado=resultado,
            )

            if jogo_e_mata_mata(jogo) and vencedor is None:
                palpite_pendente = PalpitePendente(
                    participante=participante_atual,
                    jogo=jogo,
                    palpite=palpite,
                    linha_origem=linha,
                )

            continue

        if time_que_passa:
            if participante_atual is None:
                resultado.erros.append(
                    f"Linha {numero_linha}: classificado sem participante antes: '{linha}'."
                )
                continue

            if not palpite_pendente:
                resultado.erros.append(
                    (
                        f"{participante_atual['nome']}: a linha '{linha}' informa quem passa, "
                        "mas não há um palpite empatado de mata-mata imediatamente antes."
                    )
                )
                continue

            vencedor = identificar_lado_time_no_jogo(
                time_que_passa,
                palpite_pendente.jogo,
            )

            if vencedor is None:
                resultado.erros.append(
                    (
                        f"{participante_atual['nome']}: não consegui identificar '{time_que_passa}' "
                        f"como time do jogo {palpite_pendente.jogo['time_casa']} x "
                        f"{palpite_pendente.jogo['time_visitante']}."
                    )
                )
                continue

            palpite_pendente.palpite["vencedor"] = vencedor
            palpite_pendente = None
            continue

        if linha_e_indicacao_de_classificado(linha):
            # Se chegou aqui, é uma linha de classificado fora do contexto
            # esperado. Ela deve gerar aviso, mas nunca criar um participante
            # chamado, por exemplo, "Canadá passa".
            resultado.erros.append(
                (
                    f"Linha {numero_linha}: a linha '{linha}' informa quem passa, "
                    "mas não foi vinculada a um palpite empatado de mata-mata."
                )
            )
            continue

        erro_pendente_sem_vencedor(
            palpite_pendente,
            resultado,
        )
        palpite_pendente = None

        participante_atual = obter_ou_criar_participante(
            linha,
            dados,
            resultado,
        )

    erro_pendente_sem_vencedor(
        palpite_pendente,
        resultado,
    )

    return resultado
