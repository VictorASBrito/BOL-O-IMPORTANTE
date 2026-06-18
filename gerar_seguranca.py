from getpass import getpass
from pathlib import Path
from secrets import token_hex

from werkzeug.security import generate_password_hash


def main() -> None:
    caminho_env = Path(__file__).with_name(".env")

    if caminho_env.exists():
        resposta = input(
            (
                "O arquivo .env já existe. "
                "Deseja sobrescrever? [s/N]: "
            )
        ).strip().lower()

        if resposta != "s":
            print("Operação cancelada.")
            return

    usuario = input(
        "Usuário do administrador [victor]: "
    ).strip() or "victor"

    senha = getpass(
        "Digite a senha do administrador: "
    )

    confirmacao = getpass(
        "Confirme a senha: "
    )

    if not senha:
        raise ValueError(
            "A senha não pode ficar vazia."
        )

    if senha != confirmacao:
        raise ValueError(
            "As senhas informadas não são iguais."
        )

    conteudo = "\n".join([
        f"SECRET_KEY={token_hex(32)}",
        "NOME_SITE=Bolão da Copa",
        f"ADMIN_USERNAME={usuario}",
        (
            "ADMIN_PASSWORD_HASH="
            + generate_password_hash(senha)
        ),
        "SESSION_COOKIE_SECURE=false",
        "FLASK_DEBUG=false",
        "",
    ])

    caminho_env.write_text(
        conteudo,
        encoding="utf-8",
    )

    print()
    print(f"Arquivo criado em: {caminho_env}")
    print(
        (
            "Para acesso local, mantenha "
            "SESSION_COOKIE_SECURE=false."
        )
    )
    print(
        (
            "Ao usar somente o endereço HTTPS do "
            "Cloudflare, altere para true."
        )
    )


if __name__ == "__main__":
    main()
