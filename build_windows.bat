@echo off
echo === Mixers - Build para Windows ===
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name Mixers --collect-all customtkinter main.py
echo.
echo Build concluido! Seu executavel esta em: dist\Mixers.exe
pause
