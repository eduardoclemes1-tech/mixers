# Changelog

Todas as mudanças relevantes deste projeto são documentadas neste arquivo.
O formato segue o padrão [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento segue [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [2.2.1] - 2026-11-27

### Corrigido
- Botão de Play/Pause no mini controle de mídia agora alterna dinamicamente o ícone (`▶` / `⏸`) e o tooltip de acordo com o estado real de reprodução do Windows (SMTC), com resposta imediata ao clique e ressincronização ao trocar de faixa.

## [2.2.0] - 2026-11-27

### Adicionado
- Descoberta em tempo real de **todos os aplicativos abertos** (`OpenAppsService` + `WindowEventWatcher`), incluindo janelas UWP e apps minimizados na bandeja (Discord, WhatsApp, Spotify, Steam, Riot Client, navegadores etc.).
- Atribuição automática de processo-pai para sessões hospedadas (`msedgewebview2.exe` → **WhatsApp**, `steamwebhelper.exe` → **Steam**).
- Pré-volume e pré-mute síncronos diretamente no evento WASAPI `OnSessionCreated` (aplica volume/mute no 1º milissegundo antes de qualquer pico de som).
- Leitura de ícones oficiais de apps da Microsoft Store/UWP via `AppxManifest.xml`.
- Opção **"Mostrar todos os apps abertos"** em Ajustes.

## [2.1.1] - 2026-11-27

### Corrigido
- Chamada explícita de `AudioSessionManager.RefreshSessions()` para detectar novos aplicativos e novas sessões de áudio imediatamente.
- Eventos nativos WASAPI (`OnSessionCreated` e `IMMNotificationClient`) para reagir em tempo real a novos apps e trocas externas de dispositivo de áudio.
- Monitoramento de todas as saídas de áudio ativas (incluindo dispositivos `Communications`).
- Fallback via `GetSessionIdentifier` para aplicativos elevados (Administrador) e jogos com anti-cheat.
- Barra de rolagem slim automática e altura expandida para visualizar mais aplicativos simultaneamente.

## [2.1.0] - 2026-11-27

### Adicionado
- OSD flutuante discreto ao alterar volume, microfone ou dispositivo de saída.
- Atalho global dedicado para alternar dispositivo de saída de áudio.
- Exibição do título da música atual via Windows SMTC.
- Menu de contexto (botão direito) por aplicativo: fixar no topo, restaurar 100% e ocultar.
- Controle de volume Master pela roda do mouse sobre o ícone na bandeja.
- Filtro **"Mostrar só apps tocando agora"** e opção **"Mostrar na barra de tarefas"**.

## [2.0.2] - 2026-11-27

### Alterado
- Remoção da seção "Ações rápidas" dos Ajustes e do menu da bandeja para simplificar a interface.

## [2.0.1] - 2026-11-27

### Adicionado
- Opção em Ajustes para ligar/desligar o fundo transparente Acrylic.

## [2.0.0] - 2026-11-27

### Adicionado
- Troca de dispositivo de saída com 1 clique direto no cabeçalho.
- Atalho global de mute para microfones + ícone dinâmico na bandeja.
- Modo Call automático (abaixa música/navegador durante chamadas).
- Mini controle de mídia (`⏮ ⏯ ⏭`) e recurso "Lembrar volume por aplicativo".

## [1.0.0] - 2026-11-27

### Adicionado
- Reescrita completa nativa para Windows em **C# + WPF (.NET 8)** com aceleração por GPU, vidro fosco Acrylic real e integração WASAPI via `NAudio.Wasapi`.
