import json
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CAMINHO_JSON = RAIZ / "data" / "bolao.json"

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
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caractere
        for caractere in texto
        if unicodedata.category(caractere) != "Mn"
    )
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def parece_participante_passa(nome: str) -> bool:
    return PADRAO_PASSA.match(str(nome or "").strip()) is not None


def main() -> None:
    if not CAMINHO_JSON.exists():
        print(f"Arquivo não encontrado: {CAMINHO_JSON}")
        return

    dados = json.loads(CAMINHO_JSON.read_text(encoding="utf-8"))
    participantes = dados.get("participantes", [])
    palpites = dados.get("palpites", [])

    suspeitos = [
        participante
        for participante in participantes
        if parece_participante_passa(participante.get("nome", ""))
    ]

    if not suspeitos:
        print("Nenhum participante com padrão 'time passa' foi encontrado.")
        return

    print("Participantes suspeitos encontrados:")
    for participante in suspeitos:
        total_palpites = sum(
            1
            for palpite in palpites
            if palpite.get("participante_id") == participante.get("id")
        )
        print(
            f"- ID {participante.get('id')}: {participante.get('nome')} "
            f"({total_palpites} palpite(s) vinculado(s))"
        )

    resposta = input("\nRemover esses participantes e seus palpites? [s/N]: ").strip().lower()

    if resposta != "s":
        print("Operação cancelada.")
        return

    backup = CAMINHO_JSON.with_name(
        f"bolao_backup_antes_limpar_passa_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    shutil.copy2(CAMINHO_JSON, backup)

    ids_suspeitos = {participante.get("id") for participante in suspeitos}

    dados["participantes"] = [
        participante
        for participante in participantes
        if participante.get("id") not in ids_suspeitos
    ]

    dados["palpites"] = [
        palpite
        for palpite in palpites
        if palpite.get("participante_id") not in ids_suspeitos
    ]

    CAMINHO_JSON.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Backup criado em: {backup}")
    print(f"Removidos: {len(suspeitos)} participante(s) suspeito(s).")


if __name__ == "__main__":
    main()
