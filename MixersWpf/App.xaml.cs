using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows;

namespace Mixers;

public partial class App : System.Windows.Application
{
    public const string AppVersion = "2.0.1";
    private Mutex? _singleInstanceMutex;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // Garante apenas uma instância aberta por vez
        _singleInstanceMutex = new Mutex(true, "Mixers_SingleInstance_Mutex_v1", out bool createdNew);
        if (!createdNew)
        {
            Shutdown();
            return;
        }

        DispatcherUnhandledException += (_, args) =>
        {
            LogError("DispatcherUnhandledException", args.Exception);
            args.Handled = true;
        };
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            if (args.ExceptionObject is Exception ex)
            {
                LogError("UnhandledException", ex);
            }
        };

        bool startMinimized = e.Args.Any(a =>
            a.Equals("--minimized", StringComparison.OrdinalIgnoreCase));

        var window = new MainWindow(startMinimized);
        MainWindow = window;
        if (!startMinimized)
        {
            window.ShowFlyout();
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        try
        {
            _singleInstanceMutex?.ReleaseMutex();
            _singleInstanceMutex?.Dispose();
        }
        catch
        {
        }
        base.OnExit(e);
    }

    public static void LogError(string context, Exception ex)
    {
        try
        {
            string dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "Mixers");
            Directory.CreateDirectory(dir);
            string line = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {context}: {ex}\n";
            File.AppendAllText(Path.Combine(dir, "mixers.log"), line);
        }
        catch
        {
        }
    }
}
