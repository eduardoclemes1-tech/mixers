# Mixers 🎚️

**Mixers** é um gerenciador de volume por aplicativo feito para **Windows** (Windows 10 e Windows 11).

Com ele você controla rapidamente o volume geral do PC e o som individual de cada aplicativo aberto (navegador, Spotify, Discord, jogos, etc.) em uma interface moderna em tema escuro.

## Funcionalidades

- **Volume Geral (Master):** controle deslizante e botão de mudo do sistema.
- **Volume por Aplicativo:** lista automaticamente todos os programas com áudio ativo, com slider individual e botão de mudo.
- **Busca rápida:** filtre aplicativos pelo nome.
- **Ações rápidas:**
  - **100% Tudo:** restaura todos os apps para 100% e tira o mudo.
  - **Modo Foco (30%):** baixa todos os apps para 30%.
  - **Mutar Apps:** silencia todos os aplicativos de uma vez.
- **Perfis personalizados:** salve combinações de volume (ex: *Jogo*, *Reunião*, *Estudo*) e aplique com um clique.

## Como usar no Windows

### Opção 1: Rodar direto com Python
Pré-requisito: [Python 3.10+](https://www.python.org/downloads/) instalado no Windows.

```powershell
git clone https://github.com/eduardoclemes1-tech/mixers.git
cd mixers
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Opção 2: Gerar o executável `Mixers.exe` no Windows
Basta dar dois cliques em `build_windows.bat` ou rodar no PowerShell:
```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name Mixers --collect-all customtkinter main.py
```
O executável será gerado em `dist\Mixers.exe`.

## Estrutura do Projeto

```text
mixers/
├── main.py                # Ponto de entrada do aplicativo
├── build_windows.bat      # Script de 1 clique para gerar Mixers.exe no Windows
├── requirements.txt       # Dependências do projeto
├── mixers/
│   ├── __init__.py
│   ├── audio_backend.py   # Integração com áudio do Windows (WASAPI / pycaw)
│   ├── profiles.py        # Salvar e carregar perfis de volume
│   └── ui.py              # Interface gráfica (CustomTkinter)
└── tests/
    └── test_mixers.py     # Testes automatizados
```

## Rodar os testes

```bash
python -m unittest discover -s tests -v
```
