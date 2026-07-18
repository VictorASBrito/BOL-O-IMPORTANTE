TIPO_JOGO_GRUPO = "GRUPO"
TIPO_JOGO_MATA_MATA = "MATA_MATA"

VENCEDOR_CASA = "CASA"
VENCEDOR_VISITANTE = "VISITANTE"
EMPATE = "EMPATE"


def normalizar_tipo_jogo(tipo_jogo: str | None) -> str:
    tipo = str(tipo_jogo or TIPO_JOGO_GRUPO).strip().upper()

    if tipo in {"MATA_MATA", "MATA-MATA", "MATA MATA"}:
        return TIPO_JOGO_MATA_MATA

    return TIPO_JOGO_GRUPO


def jogo_e_mata_mata(jogo: dict | None) -> bool:
    if not jogo:
        return False

    return (
        normalizar_tipo_jogo(
            jogo.get("tipo_jogo")
        )
        == TIPO_JOGO_MATA_MATA
    )


def pontuacao_placar_exato(jogo: dict | None) -> int:
    return 5 if jogo_e_mata_mata(jogo) else 3


def identificar_resultado(
    gols_casa: int,
    gols_visitante: int,
) -> str:
    if gols_casa > gols_visitante:
        return VENCEDOR_CASA

    if gols_casa < gols_visitante:
        return VENCEDOR_VISITANTE

    return EMPATE


def identificar_vencedor_mata_mata(
    gols_casa: int,
    gols_visitante: int,
    vencedor: str | None = None,
) -> str:
    resultado = identificar_resultado(
        gols_casa,
        gols_visitante,
    )

    if resultado != EMPATE:
        return resultado

    vencedor_normalizado = str(
        vencedor or ""
    ).strip().upper()

    if vencedor_normalizado in {
        VENCEDOR_CASA,
        VENCEDOR_VISITANTE,
    }:
        return vencedor_normalizado

    return EMPATE


def calcular_pontos(
    palpite_casa: int,
    palpite_visitante: int,
    resultado_casa: int,
    resultado_visitante: int,
    tipo_jogo: str | None = TIPO_JOGO_GRUPO,
    palpite_vencedor: str | None = None,
    resultado_vencedor: str | None = None,
) -> int:
    """
    Regras de pontuação:

    Jogo normal:
    - Placar exato: 3 pontos;
    - Acerto apenas do resultado: 1 ponto;
    - Resultado incorreto: 0 pontos.

    Mata-mata:
    - Placar exato: 5 pontos;
    - Acerto apenas do classificado/resultado: 1 ponto;
    - Resultado incorreto: 0 pontos.
    """

    tipo_normalizado = normalizar_tipo_jogo(
        tipo_jogo
    )

    acertou_placar = (
        palpite_casa == resultado_casa
        and palpite_visitante == resultado_visitante
    )

    if tipo_normalizado == TIPO_JOGO_MATA_MATA:
        if acertou_placar:
            return 5

        vencedor_palpite = identificar_vencedor_mata_mata(
            palpite_casa,
            palpite_visitante,
            palpite_vencedor,
        )

        vencedor_resultado = identificar_vencedor_mata_mata(
            resultado_casa,
            resultado_visitante,
            resultado_vencedor,
        )

        if (
            vencedor_palpite in {
                VENCEDOR_CASA,
                VENCEDOR_VISITANTE,
            }
            and vencedor_palpite == vencedor_resultado
        ):
            return 1

        return 0

    if acertou_placar:
        return 3

    resultado_palpite = identificar_resultado(
        palpite_casa,
        palpite_visitante,
    )

    resultado_oficial = identificar_resultado(
        resultado_casa,
        resultado_visitante,
    )

    if resultado_palpite == resultado_oficial:
        return 1

    return 0


def montar_ranking(dados: dict) -> list[dict]:
    ranking = []

    jogos_por_id = {
        jogo["id"]: jogo
        for jogo in dados["jogos"]
    }

    for participante in dados["participantes"]:
        if not participante.get("ativo", True):
            continue

        total_pontos = 0
        placares_exatos = 0
        resultados_corretos = 0

        for palpite in dados["palpites"]:
            if (
                palpite["participante_id"]
                != participante["id"]
            ):
                continue

            jogo = jogos_por_id.get(
                palpite["jogo_id"]
            )

            if not jogo:
                continue

            if (
                jogo.get("gols_casa") is None
                or jogo.get("gols_visitante") is None
                or jogo.get("situacao") == "CANCELADO"
            ):
                continue

            pontos = calcular_pontos(
                palpite["gols_casa"],
                palpite["gols_visitante"],
                jogo["gols_casa"],
                jogo["gols_visitante"],
                tipo_jogo=jogo.get("tipo_jogo"),
                palpite_vencedor=palpite.get("vencedor"),
                resultado_vencedor=jogo.get("vencedor"),
            )

            total_pontos += pontos

            if pontos == pontuacao_placar_exato(jogo):
                placares_exatos += 1
            elif pontos == 1:
                resultados_corretos += 1

        ranking.append({
            "participante_id": participante["id"],
            "nome": participante["nome"],
            "pontos": total_pontos,
            "placares_exatos": placares_exatos,
            "resultados_corretos": resultados_corretos,
        })

    ranking.sort(
        key=lambda item: (
            -item["pontos"],
            -item["placares_exatos"],
            -item["resultados_corretos"],
            item["nome"].lower(),
        )
    )

    for posicao, item in enumerate(
        ranking,
        start=1,
    ):
        item["posicao"] = posicao

    return ranking
