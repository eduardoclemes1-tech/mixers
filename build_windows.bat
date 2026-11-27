@echo off
echo === Mixers v1.0.0 - Build Nativo C# WPF (.NET 8) ===
dotnet publish MixersWpf\Mixers.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o dist
echo.
echo Pronto! Seu executavel nativo esta em: dist\Mixers.exe
pause
