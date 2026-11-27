"""Ponto de entrada do aplicativo Mixers (Windows)."""

from __future__ import annotations

import argparse
import sys

from mixers.audio_backend import create_audio_backend
from mixers.ui import MixersApp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mixers",
        description="Mixers - Gerenciador de som por aplicativo para Windows.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Executa com dados simulados (útil para testes sem áudio do Windows).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.demo and sys.platform != "win32":
        print(
            "O Mixers foi feito para Windows (win32).\n"
            "Para testar a interface em modo simulado, execute: python main.py --demo",
            file=sys.stderr,
        )
        return 1

    backend = create_audio_backend(demo=args.demo)
    app = MixersApp(backend=backend, demo_mode=args.demo)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
