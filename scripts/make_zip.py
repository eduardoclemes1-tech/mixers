"""Empacota dist/Mixers.exe em um arquivo dist/Mixers-Windows.zip pronto para uso."""

from __future__ import annotations

from pathlib import Path
import zipfile

README_TXT = """Mixers - Controle de Som por Aplicativo (Windows)
=================================================

Como usar:
1. Extraia esta pasta em qualquer lugar do seu PC.
2. Execute o arquivo Mixers.exe.
3. Ele abre no canto inferior direito e fica rodando em segundo plano
   na bandeja do sistema (perto do relogio do Windows).

Dicas:
- Clique no icone do Mixers perto do relogio para abrir ou ocultar.
- Clique em "Ajustes" para mudar a transparencia ou ativar "Iniciar com o Windows".
- Aperte ESC ou clique fora do painel para recolher para a bandeja.
"""


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    exe_path = root / "dist" / "Mixers.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"Executável não encontrado em {exe_path}")

    zip_path = root / "dist" / "Mixers-Windows.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, arcname="Mixers/Mixers.exe")
        zf.writestr("Mixers/LEIA-ME.txt", README_TXT)

    print(f"Pacote criado com sucesso: {zip_path}")


if __name__ == "__main__":
    main()
