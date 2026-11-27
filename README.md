# Mixers 🎚️

**Mixers** é um gerenciador de volume por aplicativo **100% nativo para Windows 10 e Windows 11**, desenvolvido em **C# + WPF (.NET 8)** com aceleração por GPU (DirectX), vidro fosco **Acrylic real** e integração nativa com o áudio do Windows (**WASAPI / NAudio**).

## ⬇️ Download para Windows

Escolha a opção que preferir (sempre baixa a versão mais recente):

- 👉 **[Baixar Mixers.exe (recomendado — 1 clique, sem instalar nada)](https://github.com/eduardoclemes1-tech/mixers/releases/latest/download/Mixers.exe)**
- 📦 **[Baixar Mixers-Windows.zip](https://github.com/eduardoclemes1-tech/mixers/releases/latest/download/Mixers-Windows.zip)**
- 📋 [Ver todas as versões (Releases)](https://github.com/eduardoclemes1-tech/mixers/releases)

## ✨ Funcionalidades

- **Visual nativo Windows 11 (Acrylic + GPU 60/144Hz):** vidro fosco real que desfoca o papel de parede atrás do painel, cantos retos/quadrados e **cor automática sincronizada com o tema do seu Windows ao vivo**.
- **Trocar dispositivo de saída com 1 clique:** clique no nome do alto-falante no topo para alternar rapidamente entre fone, caixa de som e monitor/TV.
- **Sliders estilo EarTrumpet:** trilha fina de `2px` renderizada em DirectX com **medidor de som branco ao vivo integrado**, pílula vertical slim e controle pela roda do mouse.
- **Ícones reais dos aplicativos:** extrai automaticamente o ícone oficial de cada `.exe` e app da Microsoft Store/UWP.
- **Microfones, Medidor de Voz & Atalho de Mute:** controle de sensibilidade, mudo, botão **`Testar`**, medidor ao vivo (`Silêncio`, `Baixo`, `Ideal`, `Alto!`) e atalho global exclusivo para mutar o microfone de qualquer jogo/chamada.
- **Mini controle de mídia (`⏮ ⏯ ⏭`), Modo Call automático & Lembrar volume por app:** abaixa a música automaticamente durante chamadas, lembra o volume preferido de cada programa e muda o ícone da bandeja dinamicamente.
- **Segundo plano, Atalhos por tecla única & Auto-Update:** atualiza automaticamente direto pelo GitHub Releases com 1 clique.

<details>
<summary>🛠️ Para desenvolvedores (compilar localmente com .NET 8)</summary>

```powershell
git clone https://github.com/eduardoclemes1-tech/mixers.git
cd mixers
dotnet build MixersWpf/Mixers.csproj
```

Para gerar `dist\Mixers.exe`, execute `build_windows.bat`.

</details>
