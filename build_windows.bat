@echo off
setlocal
echo === Mixers - Build Nativo C# WPF (.NET 8) ===
dotnet publish MixersWpf\Mixers.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o dist
if errorlevel 1 (
    echo.
    echo Erro ao compilar o Mixers. Verifique se o .NET 8 SDK esta instalado.
    exit /b 1
)
echo.
echo Pronto! Seu executavel nativo esta em: dist\Mixers.exe
pause
