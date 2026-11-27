@echo off
echo === Mixers - Gerando Mixers.exe e Mixers-Windows.zip ===
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name Mixers --collect-all customtkinter --hidden-import pystray._win32 main.py
python scripts\make_zip.py
echo.
echo Pronto! Seu pacote ZIP esta em: dist\Mixers-Windows.zip
pause
