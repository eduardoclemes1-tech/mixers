# Mixers 🎚️

**Mixers** é um gerenciador de volume por aplicativo para **Windows 10 e Windows 11**, com visual **clean, transparente e flutuante** que fica rodando em **segundo plano na bandeja do sistema** (perto do relógio).

## ⬇️ Download para Windows

Escolha a opção que preferir (sempre baixa a versão mais recente):

- 👉 **[Baixar Mixers.exe (recomendado — 1 clique, sem instalar nada)](https://github.com/eduardoclemes1-tech/mixers/releases/latest/download/Mixers.exe)**
- 📦 **[Baixar Mixers-Windows.zip](https://github.com/eduardoclemes1-tech/mixers/releases/latest/download/Mixers-Windows.zip)**
- 📋 [Ver todas as versões (Releases)](https://github.com/eduardoclemes1-tech/mixers/releases)

### Como usar
1. Baixe o **`Mixers.exe`** (ou extraia o **`Mixers-Windows.zip`**) e dê dois cliques para abrir.
   > *Nota:* na primeira execução, o Windows SmartScreen pode exibir um aviso por ser um app independente — clique em **Mais informações → Executar assim mesmo**.
2. O painel abre no canto inferior direito e fica rodando em segundo plano perto do relógio.
3. Sempre que sair uma versão nova, o próprio **Mixers** avisa e atualiza com 1 clique!

## ✨ Funcionalidades

- **Roda em segundo plano (System Tray):** clique no ícone perto do relógio ou pressione o **atalho global** (`Ctrl+Alt+M` por padrão, personalizável em **Ajustes**) para abrir/ocultar com animação suave.
- **Visual clean e transparente:** tema escuro translúcido com cantos arredondados nativos do Windows 11 e controle de **Transparência** (65% a 100%) salvo automaticamente.
- **Microfones & Sensibilidade:** lista todos os microfones ativos logo abaixo do Volume Geral, com ajuste individual de sensibilidade e botão de mudo.
- **Interativo em tempo real:** medidor visual de som (VU meter) em cada aplicativo e no volume geral, além do dispositivo de saída ativo.
- **Volume Geral + Por Aplicativo:** controle individual e botão de mudo para cada programa aberto (navegador, Spotify, Discord, jogos, etc.).
- **Ações rápidas & Perfis:** botões de `100%`, `Foco 30%`, `Mutar`, busca rápida e perfis personalizados.
- **Iniciar com o Windows & Auto-Update:** tudo configurável dentro de **Ajustes** ou pelo menu do ícone na bandeja.

<details>
<summary>🛠️ Para desenvolvedores (rodar ou compilar via Python)</summary>

```powershell
git clone https://github.com/eduardoclemes1-tech/mixers.git
cd mixers
pip install -r requirements.txt
python main.py
```

Para gerar `dist\Mixers-Windows.zip` localmente no Windows, execute `build_windows.bat`.

</details>
