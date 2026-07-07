using Microsoft.UI.Xaml;

namespace BlarAI.Desktop;

/// <summary>
/// Application entry point. Opens the main window. The app is a thin client of
/// the Python UI backend (named pipe, ADR-014) and holds no business logic.
/// </summary>
public partial class App : Application
{
    private Window? _window;

    public App()
    {
        this.InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window = new MainWindow();
        _window.Activate();
    }
}
