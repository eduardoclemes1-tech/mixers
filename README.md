# Mixers 🎚️

**Mixers** é um gerenciador de volume por aplicativo para **Windows 10 e Windows 11**, com visual **clean, transparente e flutuante** que fica rodando em **segundo plano na bandeja do sistema** (perto do relógio).

## Funcionalidades

- **Roda em segundo plano (System Tray):** abre um painel compacto no canto inferior direito ao clicar no ícone perto do relógio, e se recolhe automaticamente ao clicar fora ou apertar `Esc`.
- **Visual clean e transparente:** tema escuro translúcido com cantos arredondados nativos do Windows 11 e controle deslizante de **Transparência** (65% a 100%).
- **Interativo em tempo real:** barra visual de nível de som (VU meter) em cada aplicativo e no volume geral, além do nome do dispositivo de saída ativo.
- **Volume Geral + Por Aplicativo:** controle individual e mudo para cada programa aberto (navegador, Spotify, Discord, jogos, etc.).
- **Ações rápidas & Perfis:** botões de `100%`, `Foco 30%`, `Mutar`, busca rápida e perfis personalizados salvos no Windows.
- **Iniciar com o Windows:** opção integrada em **Ajustes** ou no menu do botão direito do ícone da bandeja.

## Como baixar só o ZIP pronto (sem instalar Python no Windows)

Para ativar o build automático do `Mixers-Windows.zip` no GitHub (leva 10 segundos, só faz uma vez):
1. No repositório no GitHub, clique em **Add file → Create new file**.
2. Digite o caminho: `.github/workflows/build-windows.yml`
3. Cole o conteúdo do arquivo [`github_workflow_template.yml`](github_workflow_template.yml) e clique em **Commit changes**.
4. Vá na aba **Actions**, abra a execução concluída e baixe **`Mixers-Windows-ZIP`**.
5. Extraia o `.zip` e dê dois cliques em **`Mixers.exe`**!

## Como rodar ou gerar o ZIP localmente no Windows

```powershell
git clone https://github.com/eduardoclemes1-tech/mixers.git
cd mixers
```

- **Para gerar `dist\Mixers-Windows.zip` com 1 clique:** dê dois cliques em `build_windows.bat`.
- **Para rodar direto com Python:**
  ```powershell
  pip install -r requirements.txt
  python main.py
  ```

## Estrutura do Projeto

```text
mixers/
├── main.py                        # Ponto de entrada (--minimized / --demo)
├── build_windows.bat              # Gera Mixers.exe e Mixers-Windows.zip
├── github_workflow_template.yml   # Modelo para build automático no GitHub Actions
├── requirements.txt               # Dependências do projeto
├── scripts/
│   └── make_zip.py                # Empacota Mixers.exe + LEIA-ME.txt em ZIP
├── mixers/
│   ├── __init__.py
│   ├── audio_backend.py           # Áudio do Windows (WASAPI / pycaw + VU meter)
│   ├── windows_integration.py     # Cantos arredondados, área útil e autostart
│   ├── tray.py                    # Ícone e menu em segundo plano (System Tray)
│   ├── profiles.py                # Perfis salvos em %APPDATA%\Mixers
│   └── ui.py                      # Painel clean, transparente e flutuante
└── tests/
    └── test_mixers.py             # Testes automatizados
```
