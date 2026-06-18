import os

from waitress import serve

from app import app


if __name__ == "__main__":
    porta = int(
        os.getenv(
            "PORT",
            "8080",
        )
    )

    print("Servidor do bolão iniciado.")
    print(
        f"Endereço local: http://127.0.0.1:{porta}"
    )

    serve(
        app,
        host="127.0.0.1",
        port=porta,
        threads=8,
    )
