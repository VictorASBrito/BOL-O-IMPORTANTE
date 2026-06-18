def identificar_resultado(
    gols_casa: int,
    gols_visitante: int
) -> str:
    if gols_casa > gols_visitante:
        return "CASA"

    if gols_casa < gols_visitante:
        return "VISITANTE"

    return "EMPATE"


def calcular_pontos(
    palpite_casa: int,
    palpite_visitante: int,
    resultado_casa: int,
    resultado_visitante: int
) -> int:
    """
    Regra de pontuação:

    - Placar exato: 3 pontos;
    - Acerto apenas do resultado: 1 ponto;
    - Resultado incorreto: 0 pontos.
    """

    acertou_placar = (
        palpite_casa == resultado_casa
        and palpite_visitante == resultado_visitante
    )

    if acertou_placar:
        return 3

    resultado_palpite = identificar_resultado(
        palpite_casa,
        palpite_visitante
    )

    resultado_oficial = identificar_resultado(
        resultado_casa,
        resultado_visitante
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
                jogo["gols_visitante"]
            )

            total_pontos += pontos

            if pontos == 3:
                placares_exatos += 1
            elif pontos == 1:
                resultados_corretos += 1

        ranking.append({
            "participante_id": participante["id"],
            "nome": participante["nome"],
            "pontos": total_pontos,
            "placares_exatos": placares_exatos,
            "resultados_corretos": resultados_corretos
        })

    ranking.sort(
        key=lambda item: (
            -item["pontos"],
            -item["placares_exatos"],
            -item["resultados_corretos"],
            item["nome"].lower()
        )
    )

    for posicao, item in enumerate(
        ranking,
        start=1
    ):
        item["posicao"] = posicao

    return ranking
