# Contribuindo com o Mixers

Contribuições são muito bem-vindas! Se você encontrou um bug ou tem uma ideia de melhoria, siga este guia rápido.

## Pré-requisitos

- **Windows 10 (19041+)** ou **Windows 11**
- **[.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)**

## Como rodar localmente

```powershell
git clone https://github.com/eduardoclemes1-tech/mixers.git
cd mixers
dotnet build
dotnet run --project MixersWpf/Mixers.csproj
```

Para gerar o executável único (`dist\Mixers.exe`):

```powershell
.\build_windows.bat
```

## Padrões de contribuição

1. Crie uma branch a partir de `main` (ex.: `feat/minha-melhoria` ou `fix/correcao-audio`).
2. Mantenha o código limpo, sem avisos de compilação (`dotnet build -c Release` com **0 avisos e 0 erros**).
3. Use mensagens de commit no padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `perf:`, `docs:`, `chore:`).
4. Abra um Pull Request descrevendo claramente o problema resolvido ou o recurso adicionado.
