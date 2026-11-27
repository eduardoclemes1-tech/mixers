# Mixers 🎚️

**Mixers** é um gerenciador de volume por aplicativo **100% nativo para Windows 10 e Windows 11**, desenvolvido em **C# + WPF (.NET 8)** com aceleração por GPU (DirectX), vidro fosco **Acrylic real** e integração nativa com o áudio do Windows (**WASAPI / NAudio**).

## ⬇️ Download para Windows

Escolha a opção que preferir (sempre baixa a versão mais recente):

- 👉 **[Baixar Mixers.exe (recomendado — 1 clique, sem instalar nada)](https://github.com/eduardoclemes1-tech/mixers/releases/latest/download/Mixers.exe)**
- 📦 **[Baixar Mixers-Windows.zip](https://github.com/eduardoclemes1-tech/mixers/releases/latest/download/Mixers-Windows.zip)**
- 📋 [Ver todas as versões (Releases)](https://github.com/eduardoclemes1-tech/mixers/releases)

## ✨ Funcionalidades

- **Visual nativo Windows 11 (Acrylic + GPU 60/144Hz):** vidro fosco real que desfoca o papel de parede atrás do painel, cantos arredondados nativos e **cor automática sincronizada com o tema do seu Windows**.
- **Sliders estilo EarTrumpet:** trilha fina de `2px` renderizada em DirectX com **medidor de som branco ao vivo integrado**, pílula vertical slim e controle pela roda do mouse.
- **Ícones reais dos aplicativos:** extrai automaticamente o ícone oficial de cada `.exe` aberto.
- **Microfones & Medidor de Voz:** controle de sensibilidade, mudo, botão **`Testar`** e medidor ao vivo com classificação de nível (`Silêncio`, `Baixo`, `Ideal`, `Alto!`).
- **Roda em segundo plano (System Tray):** abre/fecha pelo ícone perto do relógio ou pelo **atalho global personalizável** (`Ctrl+Alt+M` por padrão), com opção de desligar animações para modo 100% instantâneo.
- **Iniciar com Windows, Perfis e Auto-Update:** atualiza automaticamente direto pelo GitHub Releases com 1 clique.

<details>
<summary>🛠️ Para desenvolvedores (compilar localmente com .NET 8)</summary>

```powershell
git clone https://github.com/eduardoclemes1-tech/mixers.git
cd mixers
dotnet build MixersWpf/Mixers.csproj
```

Para gerar `dist\Mixers.exe`, execute `build_windows.bat`.

</details>
