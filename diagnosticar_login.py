import os
from getpass import getpass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import check_password_hash


def versao_pacote(nome: str) -> str:
    try:
        return version(nome)
    except PackageNotFoundError:
        return "não instalado"


def main() -> None:
    caminho_env = Path(__file__).with_name(
        ".env"
    )

    print("Diagnóstico do login")
    print("=" * 50)
    print(f".env: {caminho_env}")
    print(f"Existe: {caminho_env.exists()}")
    print(f"Flask: {versao_pacote('Flask')}")
    print(f"Werkzeug: {versao_pacote('Werkzeug')}")
    print(f"Flask-WTF: {versao_pacote('Flask-WTF')}")
    print(f"python-dotenv: {versao_pacote('python-dotenv')}")
    print()

    if not caminho_env.exists():
        print(
            "ERRO: o arquivo .env não foi encontrado."
        )
        return

    load_dotenv(
        dotenv_path=caminho_env,
        override=True,
    )

    usuario = os.getenv(
        "ADMIN_USERNAME",
        "",
    )

    senha_hash = os.getenv(
        "ADMIN_PASSWORD_HASH",
        "",
    )

    secret_key = os.getenv(
        "SECRET_KEY",
        "",
    )

    print(
        "ADMIN_USERNAME configurado:",
        bool(usuario),
    )
    print(
        "ADMIN_PASSWORD_HASH configurado:",
        bool(senha_hash),
    )
    print(
        "SECRET_KEY configurada:",
        bool(secret_key),
    )

    if senha_hash:
        metodo = senha_hash.split(
            "$",
            1,
        )[0]

        print(
            "Método detectado no hash:",
            metodo,
        )

    if (
        not usuario
        or not senha_hash
        or not secret_key
    ):
        print()
        print(
            "ERRO: o .env está incompleto."
        )
        return

    senha = getpass(
        "\nDigite a senha para testar: "
    )

    try:
        valida = check_password_hash(
            senha_hash,
            senha,
        )
    except Exception as erro:
        print()
        print(
            "ERRO ao interpretar o hash:"
        )
        print(
            f"{type(erro).__name__}: {erro}"
        )
        print()
        print(
            (
                "Regere o .env usando o mesmo "
                "Python do servidor."
            )
        )
        return

    print()
    print(
        "Senha válida:",
        "SIM" if valida else "NÃO",
    )


if __name__ == "__main__":
    main()
