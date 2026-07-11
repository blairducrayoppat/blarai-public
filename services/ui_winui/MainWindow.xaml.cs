using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using BlarAI.Desktop.Ipc;
using BlarAI.Desktop.Dtos;
using BlarAI.Desktop.Services;
using BlarAI.Desktop.ViewModels;
using Windows.ApplicationModel.DataTransfer;
using Windows.Graphics;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace BlarAI.Desktop;

/// <summary>
/// Main window. A thin Gemini-shaped chat surface over the Python UI backend
/// (named pipe, ADR-014): sidebar of sessions, a centered transcript, and a
/// composer pill. All chat orchestration lives in the backend; this renders.
/// </summary>
public sealed partial class MainWindow : Window
{
    public ObservableCollection<ChatSession> Sessions { get; } = new();
    public ObservableCollection<MessageItem> Messages { get; } = new();
    public ObservableCollection<AttachmentChip> PendingAttachments { get; } = new();
    // Generated-image gallery tiles (UC-010 Phase 2, #668). Repopulated on each
    // gallery open; thumbnails fill asynchronously after the metadata loads.
    public ObservableCollection<GalleryImageItem> GalleryImages { get; } = new();

    // Single-user personal app: userdata/ is at a fixed path. Used to resolve
    // image thumbnails for attachment chips.
    private const string UserdataDir = @"C:\Users\mrbla\BlarAI\userdata";

    // Slash commands available as a power-user backdoor (not surfaced in the
    // greeting). The soft autocomplete offers these when the input starts "/".
    private static readonly (string Cmd, string Hint)[] SlashCommands =
    {
        ("/ls", "list files in userdata/ that can be loaded"),
        ("/load ", "load a file from userdata/ by name"),
        ("/unload", "clear loaded documents from this chat"),
        ("/rename ", "rename this chat"),
        ("/trust", "allow tools while documents are loaded (this chat)"),
        ("/ingest ", "capture pasted text or a file into the knowledge bank"),
        ("/approve", "approve the pending ingest into the knowledge bank"),
        ("/reject", "reject the pending ingest"),
        ("/imagine ", "generate a photorealistic image from a text prompt (UC-010)"),
        ("/illustrate ", "generate a flat-vector illustration from a prompt (UC-010)"),
        ("/cartoon ", "generate a soft cartoon illustration from a prompt (UC-010)"),
        ("/edit ", "edit a local or stored image with a prompt (img2img)"),
        ("/save ", "save a generated/displayed image to a local path"),
        ("/images", "list, delete, or check saved-status of your generated images"),
        ("/dispatch ", "send a coding goal to the agentic-setup fleet to build (brief §9)"),
    };

    // Commands that are NOT host-side: they must travel to the backend as
    // prompt text, where the GATEWAY parses them (/external -> the
    // UNTRUSTED_EXTERNAL channel, ADR-023 §3.1; /ingest, /approve, /reject ->
    // the knowledge-bank ingest coordinator, #655). Deliberate passthrough
    // list — any other unknown slash command still errors client-side.
    private static readonly string[] BackendPassthroughCommands =
    {
        "/external", "/ingest", "/approve", "/reject",
        // UC-010 image generation + management (ADR-033, #666/#667/#703) — parsed
        // by the GATEWAY (transport.py parse_imagine_command -> ImagineCoordinator),
        // not host-side. /illustrate + /cartoon are the #703 flat-illustration
        // styles; "/images" = list / delete / saved-status (Phase 1).
        "/imagine", "/illustrate", "/cartoon", "/edit", "/save", "/images",
        // Headless-coding dispatch to the agentic-setup fleet (brief §9) — parsed
        // by the GATEWAY (transport.py parse_dispatch_command -> DispatchCoordinator).
        "/dispatch",
        // Operator-preference memory (#770 M1) — parsed by the GATEWAY
        // (transport.py parse_preference_command -> PreferencesCoordinator).
        // /remember saves the operator's verbatim words; /preferences lists/edits/deletes.
        "/remember", "/preferences",
        // Operator-preference PROPOSAL confirm/dismiss (#770 M2 W1) — resolve a
        // card the 14B proposed via propose_preference; the proposal card's
        // Save/Dismiss buttons emit these with the card's staging token. They
        // ride the SAME PREFERENCE_WRITE door (P8) — the model never re-supplies
        // the body, only the 16-hex token crosses.
        "/remember-confirm", "/remember-dismiss",
    };

    private static bool IsBackendCommand(string text)
    {
        string lower = text.ToLowerInvariant();
        foreach (var cmd in BackendPassthroughCommands)
        {
            if (lower == cmd) return true;
            // Verb followed by whitespace (space OR newline — multi-line
            // paste after "/ingest" is a first-class shape).
            if (lower.StartsWith(cmd) && lower.Length > cmd.Length
                && char.IsWhiteSpace(lower[cmd.Length])) return true;
        }
        return false;
    }

    private readonly BackendClient _backend = new();
    private readonly DispatcherQueue _ui = DispatcherQueue.GetForCurrentThread();
    private readonly UserPrefs _prefs = UserPrefs.Load();
    private readonly VoicePlayback _playback = new();
    private VoiceCapture? _capture;
    private VoiceStatus _voiceStatus = VoiceStatus.Off;
    private bool _recording;
    private string? _activeSessionId;
    private bool _busy;

    public MainWindow()
    {
        this.InitializeComponent();

        // Modern shell: Mica backdrop + content-into-title-bar.
        this.SystemBackdrop = new MicaBackdrop();
        this.ExtendsContentIntoTitleBar = true;
        this.SetTitleBar(AppTitleBar);
        EnableDragDropAcrossElevation();
        ApplySavedTheme();

        try
        {
            var appWindow = this.AppWindow;
            appWindow?.Resize(new SizeInt32(1100, 760));
            // Live taskbar button + titlebar use the BlAIr gold brand mark.
            // The .ico ships next to the build (Content/PreserveNewest, csproj).
            appWindow?.SetIcon(
                Path.Combine(AppContext.BaseDirectory, "Assets", "blair.ico"));
        }
        catch { /* AppWindow may be unavailable in some hosts; non-fatal. */ }

        Messages.CollectionChanged += (_, _) => UpdateGreetingVisibility();
        UpdateGreetingVisibility();

        // Inline image rendering (UC-010 #666/#665 Pass B): the markdown renderer
        // resolves a blarai-img://<id> ref to locally-decrypted PNG bytes through
        // the backend's IMAGE_RESOLVE corridor. Wire that one delegate here (the
        // single backend pipe per process), so a generated-image reply renders the
        // pixels inline. The delegate carries bytes only — display-only, no Uri /
        // network / launch path (see MarkdownBlock.ImageBytesResolver).
        Controls.MarkdownBlock.ImageBytesResolver = _backend.ResolveImageAsync;

        // Preference proposal card (#770 M2 W1): the card's Save/Dismiss buttons
        // send /remember-confirm <token> / /remember-dismiss <token> as a PROMPT —
        // the gateway intercepts it before the model (P8), exactly as if the
        // operator typed the command. The token is the only thing that crosses;
        // the AO commits the store-side staged verbatim bytes (confirm-hop
        // integrity).
        Controls.MarkdownBlock.ProposalCommandSender =
            command => SubmitPromptAsync(command, speak: false);

        this.Activated += OnFirstActivated;
    }

    private bool _connectedOnce;

    private async void OnFirstActivated(object sender, Microsoft.UI.Xaml.WindowActivatedEventArgs e)
    {
        if (_connectedOnce) return;
        _connectedOnce = true;
        await ConnectAndLoadAsync();
    }

    // ── Connection + session list ───────────────────────────────────────

    private async Task ConnectAndLoadAsync()
    {
        try
        {
            await _backend.ConnectAsync();
            await ReloadSessionsAsync();
            await LoadVoiceStatusAsync();
            HideStatus();
        }
        catch (Exception ex)
        {
            ShowStatus(
                InfoBarSeverity.Warning,
                "BlarAI backend not running",
                "Start it, then reopen this window. (" + ex.Message + ")");
        }
    }

    private async Task ReloadSessionsAsync()
    {
        var sessions = await _backend.ListSessionsAsync();
        Sessions.Clear();
        foreach (var s in sessions) Sessions.Add(s);
    }

    private async void OnSessionSelected(object sender, SelectionChangedEventArgs e)
    {
        if (SessionsList.SelectedItem is not ChatSession session) return;
        if (session.Id == _activeSessionId) return;
        _activeSessionId = session.Id;
        ChatTitleText.Text = session.DisplayTitle;

        Messages.Clear();
        try
        {
            await _backend.SetActiveSessionAsync(session.Id);
            var turns = await _backend.GetTurnsAsync(session.Id);
            foreach (var t in turns)
            {
                var item = new MessageItem(t.Role, t.Content);
                if (t.IsDenied)
                {
                    item.IsDenied = true;
                    item.ReasonText = string.Join(", ", t.PgovReasons);
                }
                Messages.Add(item);
            }
            ScrollToEnd();
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Could not load chat", ex.Message);
        }
    }

    private async void OnNewChat(object sender, RoutedEventArgs e)
    {
        _activeSessionId = null;
        SessionsList.SelectedItem = null;
        ChatTitleText.Text = "";
        Messages.Clear();
        await Task.CompletedTask;
    }

    // ── New project (#712): create a git repo + start the build, no git for the
    //    operator. Asks what to build + a name, then sends /dispatch new in a
    //    fresh chat; the gateway does git init/commit then plans for approval. ──
    private async void OnNewProject(object sender, RoutedEventArgs e)
    {
        var goalBox = new TextBox
        {
            Header = "What do you want to build?",
            PlaceholderText = "e.g. a calculator a kid can use",
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            MinHeight = 64,
        };
        var nameBox = new TextBox
        {
            Header = "Project name",
            PlaceholderText = "short name — letters, numbers, dashes",
            AcceptsReturn = false,
            Margin = new Thickness(0, 10, 0, 0),
        };
        var panel = new StackPanel { Spacing = 4 };
        panel.Children.Add(goalBox);
        panel.Children.Add(nameBox);
        var dialog = new ContentDialog
        {
            Title = "New project",
            Content = panel,
            PrimaryButtonText = "Create & build",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = this.Content.XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;

        string goal = goalBox.Text.Trim();
        string name = nameBox.Text.Trim();
        if (string.IsNullOrEmpty(goal) || string.IsNullOrEmpty(name))
        {
            ShowStatus(InfoBarSeverity.Warning, "New project",
                "Please enter both what to build and a short name.");
            return;
        }
        // A new project starts its own chat so the plan/build conversation is clean.
        _activeSessionId = null;
        SessionsList.SelectedItem = null;
        ChatTitleText.Text = "";
        Messages.Clear();
        await SubmitPromptAsync($"/dispatch new {name} | {goal}", speak: false);
    }

    // ── Reply follow-up action buttons (#712) ────────────────────────────

    /// <summary>Edit a generated image: pre-fill the composer with /edit &lt;ref&gt;
    /// so the operator just types the change (does the work AND teaches the command).</summary>
    private void OnImageEdit(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: MessageItem item }) return;
        if (string.IsNullOrEmpty(item.ActionId)) return;
        PromptBox.Text = $"/edit blarai-img://{item.ActionId} ";
        PromptBox.SelectionStart = PromptBox.Text.Length;
        PromptBox.Focus(FocusState.Programmatic);
    }

    /// <summary>Save a generated image to a file the operator chooses.</summary>
    private async void OnImageSave(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: MessageItem item }) return;
        if (string.IsNullOrEmpty(item.ActionId)) return;
        await SaveImageToFileAsync(item.ActionId);
    }

    /// <summary>Approve a pending dispatch plan (sends /dispatch approve); retires
    /// the buttons on this message so they aren't clicked twice.</summary>
    private async void OnDispatchApprove(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: MessageItem item }) item.ActionKind = "";
        await SubmitPromptAsync("/dispatch approve", speak: false);
    }

    /// <summary>Reject a pending dispatch plan (sends /dispatch reject).</summary>
    private async void OnDispatchReject(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: MessageItem item }) item.ActionKind = "";
        await SubmitPromptAsync("/dispatch reject", speak: false);
    }

    /// <summary>Picker → resolve full-res decrypted bytes → write to disk. The
    /// sanctioned operator export (ADR-033 §D), shared with the gallery Save.</summary>
    private async Task SaveImageToFileAsync(string imageId)
    {
        try
        {
            var picker = new FileSavePicker
            {
                SuggestedStartLocation = PickerLocationId.PicturesLibrary,
                SuggestedFileName = $"blarai_{imageId[..Math.Min(8, imageId.Length)]}",
            };
            picker.FileTypeChoices.Add("PNG image", new List<string> { ".png" });
            WinRT.Interop.InitializeWithWindow.Initialize(picker, Hwnd);

            StorageFile? file = await picker.PickSaveFileAsync();
            if (file is null) return;   // operator cancelled

            if (!_backend.IsConnected)
            {
                await ConnectAndLoadAsync();
                if (!_backend.IsConnected) return;
            }
            byte[]? bytes = await _backend.ResolveImageAsync(imageId);
            if (bytes is null || bytes.Length == 0)
            {
                ShowStatus(InfoBarSeverity.Error, "Could not save image",
                    "The image could not be resolved (it may have been deleted).");
                return;
            }
            await File.WriteAllBytesAsync(file.Path, bytes);
            await _backend.MarkImageSavedAsync(imageId);   // fail-soft badge update
            ShowStatus(InfoBarSeverity.Success, "Image saved", file.Path);
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Could not save image", ex.Message);
        }
    }

    // ── Per-session controls: delete + rename (#660) ─────────────────────

    // The per-session delete button is DIM-VISIBLE by default (Opacity 0.55 in
    // XAML), not hidden — the prior Opacity=0 / restore-to-0 made it hover-only,
    // and the operator could not find it (#668 WS4). Hover brightens it to full;
    // leaving the row restores the dim-default (NOT 0), so it stays discoverable.

    /// <summary>Brighten the row's trash button while the pointer is over the row.</summary>
    private void OnSessionRowPointerEntered(object sender, PointerRoutedEventArgs e)
        => SetRowTrashOpacity(sender, 1.0);

    /// <summary>Restore the dim-but-visible default when the pointer leaves the row.</summary>
    private void OnSessionRowPointerExited(object sender, PointerRoutedEventArgs e)
        => SetRowTrashOpacity(sender, 0.55);

    private static void SetRowTrashOpacity(object rowSender, double opacity)
    {
        // The trash Button is the second child (Grid.Column=1) of the row Grid.
        if (rowSender is Grid row)
            foreach (var child in row.Children)
                if (child is Button { Tag: string } b && Grid.GetColumn(b) == 1)
                    b.Opacity = opacity;
    }

    // The trash button sits inside a ListViewItem; a plain Click would also
    // select the row first. Tapped is handled (e.Handled) so the row click does
    // not race the delete, but Click is the reliable invoke — both route here.
    private void OnDeleteSessionButtonTapped(object sender, TappedRoutedEventArgs e)
        => e.Handled = true;

    private async void OnDeleteSessionButton(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: string sessionId })
            await ConfirmAndDeleteSessionAsync(sessionId);
    }

    private async void OnDeleteSessionMenu(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: string sessionId })
            await ConfirmAndDeleteSessionAsync(sessionId);
    }

    /// <summary>
    /// Confirm (modal, can't-be-undone) then delete the chat bound to
    /// <paramref name="sessionId"/> — never the wrong one (the id rides every
    /// affordance via Tag, and the backend delete is bound to session_id with a
    /// cascade that removes the turns). On success the row leaves the sidebar and,
    /// if it was the open chat, the transcript clears.
    /// </summary>
    private async Task ConfirmAndDeleteSessionAsync(string sessionId)
    {
        var target = Sessions.FirstOrDefault(s => s.Id == sessionId);
        string name = target?.DisplayTitle ?? "this chat";

        var dialog = new ContentDialog
        {
            Title = "Delete this chat?",
            Content = $"“{name}” and all its messages will be permanently deleted. This can’t be undone.",
            PrimaryButtonText = "Delete",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = this.Content.XamlRoot,
        };
        var result = await dialog.ShowAsync();
        if (result != ContentDialogResult.Primary) return;

        if (!_backend.IsConnected)
        {
            await ConnectAndLoadAsync();
            if (!_backend.IsConnected) return;
        }
        try
        {
            await _backend.DeleteSessionAsync(sessionId);
            if (target is not null) Sessions.Remove(target);
            if (_activeSessionId == sessionId)
            {
                _activeSessionId = null;
                ChatTitleText.Text = "";
                Messages.Clear();
            }
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Could not delete chat", ex.Message);
        }
    }

    private async void OnRenameSessionMenu(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: string sessionId })
            await PromptAndRenameSessionAsync(sessionId);
    }

    /// <summary>Modal text prompt then rename the chat (backend RenameSessionAsync).</summary>
    private async Task PromptAndRenameSessionAsync(string sessionId)
    {
        var target = Sessions.FirstOrDefault(s => s.Id == sessionId);
        var input = new TextBox
        {
            Text = target?.DisplayTitle ?? "",
            PlaceholderText = "Chat name",
            SelectionStart = 0,
            SelectionLength = (target?.DisplayTitle ?? "").Length,
            AcceptsReturn = false,
        };
        var dialog = new ContentDialog
        {
            Title = "Rename chat",
            Content = input,
            PrimaryButtonText = "Rename",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = this.Content.XamlRoot,
        };
        var result = await dialog.ShowAsync();
        if (result != ContentDialogResult.Primary) return;
        string title = input.Text.Trim();
        if (string.IsNullOrEmpty(title)) return;

        if (!_backend.IsConnected)
        {
            await ConnectAndLoadAsync();
            if (!_backend.IsConnected) return;
        }
        try
        {
            await _backend.RenameSessionAsync(sessionId, title);
            await ReloadSessionsAsync();
            SelectSessionInList(_activeSessionId);
            if (_activeSessionId == sessionId) ChatTitleText.Text = title;
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Could not rename chat", ex.Message);
        }
    }

    // ── Generated-image gallery (UC-010 Phase 2, #668) ───────────────────
    //
    // An overlay pane over the chat column: list the born-encrypted generated
    // images (metadata-only), show display-only thumbnails resolved through the
    // SAME decrypt corridor the inline render uses, and offer Save (export a copy
    // to disk) + Delete (secure-wipe from the store). The chat stays intact
    // underneath; closing the overlay returns to it. The gallery introduces NO
    // new decrypt path and NO new egress — it reuses ResolveImageAsync for pixels
    // and the operator's explicit Save is the sanctioned export (ADR-033).

    private async void OnOpenGallery(object sender, RoutedEventArgs e)
    {
        if (!_backend.IsConnected)
        {
            await ConnectAndLoadAsync();
            if (!_backend.IsConnected) return;
        }

        // Refresh on each open: clear stale tiles, reload metadata, then fill
        // thumbnails asynchronously so the grid appears immediately.
        GalleryImages.Clear();
        GalleryOverlay.Visibility = Visibility.Visible;
        try
        {
            var metas = await _backend.ListGeneratedImagesAsync();
            foreach (var meta in metas)
                GalleryImages.Add(new GalleryImageItem(meta));
            GalleryEmptyState.Visibility =
                GalleryImages.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
            // Fire-and-forget the per-tile thumbnail fills (each marshals its own
            // UI-thread update); a slow/failed resolve never blocks the others.
            _ = FillGalleryThumbnailsAsync();
        }
        catch (Exception ex)
        {
            // Fail-closed: an empty gallery + a status line, never a crash.
            GalleryEmptyState.Visibility = Visibility.Visible;
            ShowStatus(InfoBarSeverity.Error, "Could not load images", ex.Message);
        }
    }

    private void OnCloseGallery(object sender, RoutedEventArgs e)
        => GalleryOverlay.Visibility = Visibility.Collapsed;   // chat untouched underneath

    /// <summary>
    /// Resolve + decode each tile's thumbnail through the display corridor
    /// (BackendClient.ResolveImageAsync → ImageResolver.ResolveAsync, the exact
    /// decode the inline markdown render uses). Display-only, in-memory bitmap;
    /// the decode runs on the UI thread (SetSourceAsync must). A null/failed
    /// resolve leaves the placeholder and disables Save for that tile (nothing to
    /// write), but Delete stays available. Iterates over a snapshot so a tile
    /// removed mid-fill (a Delete) does not disturb enumeration.
    /// </summary>
    private async Task FillGalleryThumbnailsAsync()
    {
        foreach (var item in GalleryImages.ToList())
        {
            byte[]? bytes;
            try
            {
                bytes = await _backend.ResolveImageAsync(item.ImageId);
            }
            catch
            {
                bytes = null;  // fail-closed: keep the placeholder, Save stays off
            }
            if (bytes is null || bytes.Length == 0) continue;

            // Decode on the UI thread; ResolveAsync builds an in-memory BitmapImage
            // (never a Uri / network source) and returns null on corrupt bytes.
            _ui.TryEnqueue(async void () =>
            {
                try
                {
                    var source = await ImageResolver.ResolveAsync(bytes);
                    if (source is not null)
                    {
                        item.Thumbnail = source;
                        item.Resolved = true;
                    }
                }
                catch
                {
                    // Corrupt/unrenderable bytes: leave the placeholder (fail-closed).
                }
            });
        }
    }

    private async void OnGallerySaveImage(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: string imageId }) return;
        var item = GalleryImages.FirstOrDefault(i => i.ImageId == imageId);

        try
        {
            // FileSavePicker — WinUI desktop REQUIRES initializing it with the
            // window handle (no CoreWindow). Suggested name = a short id prefix.
            var picker = new FileSavePicker
            {
                SuggestedStartLocation = PickerLocationId.PicturesLibrary,
                SuggestedFileName = $"blarai_{(item?.ShortId ?? imageId[..Math.Min(8, imageId.Length)])}",
            };
            picker.FileTypeChoices.Add("PNG image", new List<string> { ".png" });
            WinRT.Interop.InitializeWithWindow.Initialize(picker, Hwnd);

            StorageFile? file = await picker.PickSaveFileAsync();
            if (file is null) return;   // operator cancelled

            // Resolve the FULL-RES decrypted bytes through the same corridor, then
            // write them to the chosen path. This is the sanctioned operator export
            // (ADR-033 §D /save-equivalent): the ONLY way decrypted pixels leave
            // the app to disk, and only on this explicit action.
            if (!_backend.IsConnected)
            {
                await ConnectAndLoadAsync();
                if (!_backend.IsConnected) return;
            }
            byte[]? bytes = await _backend.ResolveImageAsync(imageId);
            if (bytes is null || bytes.Length == 0)
            {
                ShowStatus(InfoBarSeverity.Error, "Could not save image",
                    "The image could not be resolved (it may have been deleted).");
                return;
            }
            await File.WriteAllBytesAsync(file.Path, bytes);

            // Flip the saved badge (fail-soft: a failed mark does not undo the
            // successful disk write — the file is saved regardless).
            bool marked = await _backend.MarkImageSavedAsync(imageId);
            if (item is not null && marked) item.Saved = true;
            ShowStatus(InfoBarSeverity.Success, "Image saved", file.Path);
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Could not save image", ex.Message);
        }
    }

    private async void OnGalleryDeleteImage(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: string imageId }) return;

        // Modal confirm (can't-be-undone), mirroring the session delete pattern.
        var dialog = new ContentDialog
        {
            Title = "Delete this image?",
            Content = "This generated image will be permanently deleted from BlarAI. "
                      + "Copies you have already saved to disk are not affected. This can’t be undone.",
            PrimaryButtonText = "Delete",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = this.Content.XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;

        if (!_backend.IsConnected)
        {
            await ConnectAndLoadAsync();
            if (!_backend.IsConnected) return;
        }
        try
        {
            bool deleted = await _backend.DeleteImageAsync(imageId);
            if (deleted)
            {
                var item = GalleryImages.FirstOrDefault(i => i.ImageId == imageId);
                if (item is not null) GalleryImages.Remove(item);
                GalleryEmptyState.Visibility =
                    GalleryImages.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
            }
            else
            {
                ShowStatus(InfoBarSeverity.Warning, "Could not delete image",
                    "The image was not found, or the backend refused the request.");
            }
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Could not delete image", ex.Message);
        }
    }

    // ── Sending ─────────────────────────────────────────────────────────

    private void OnPromptKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != Windows.System.VirtualKey.Enter) return;
        bool shift = InputKeyboardSourceShiftDown();
        if (shift) return;            // Shift+Enter → newline (default behavior)
        e.Handled = true;
        _ = SendAsync();
    }

    private static bool InputKeyboardSourceShiftDown()
    {
        var state = Microsoft.UI.Input.InputKeyboardSource
            .GetKeyStateForCurrentThread(Windows.System.VirtualKey.Shift);
        return (state & Windows.UI.Core.CoreVirtualKeyStates.Down)
            == Windows.UI.Core.CoreVirtualKeyStates.Down;
    }

    private async void OnSend(object sender, RoutedEventArgs e) => await SendAsync();

    private async Task SendAsync()
    {
        if (_busy) return;
        string text = PromptBox.Text.Trim();
        if (string.IsNullOrEmpty(text) && PendingAttachments.Count == 0) return;

        if (!_backend.IsConnected)
        {
            await ConnectAndLoadAsync();
            if (!_backend.IsConnected) return;
        }

        HideSuggestions();

        // Slash commands are a power-user backdoor handled host-side, never
        // sent to the model (mirrors the TUI). Never surfaced in the greeting.
        // EXCEPTION: the BackendPassthroughCommands (/external, /ingest,
        // /approve, /reject) are NOT host commands — they must reach the
        // gateway AS A PROMPT, where it parses them (/external -> the
        // UNTRUSTED_EXTERNAL channel, ADR-023 §3.1; the ingest trio -> the
        // knowledge-bank coordinator, #655). They fall through to the prompt
        // path below instead of the host-side command switch.
        if (text.StartsWith("/") && !IsBackendCommand(text))
        {
            SetBusy(true);
            PromptBox.Text = "";
            try { await HandleSlashCommandAsync(text); }
            catch (Exception ex) { ShowStatus(InfoBarSeverity.Error, "Command failed", ex.Message); }
            finally { SetBusy(false); PromptBox.Focus(FocusState.Programmatic); }
            return;
        }

        // A pure-attachment send still needs a question for the model.
        if (string.IsNullOrEmpty(text)) return;

        PromptBox.Text = "";
        // Typed sends speak the reply only if the user turned voice output on.
        await SubmitPromptAsync(text, speak: _prefs.VoiceOutput);
    }

    /// <summary>
    /// Submit <paramref name="text"/> as a turn: add the user bubble, stream the
    /// reply, and — when <paramref name="speak"/> and TTS are available — speak it
    /// sentence-by-sentence as it streams (ADR-017). Shared by typed send and the
    /// voice path, so a spoken utterance becomes a prompt with no extra step.
    /// </summary>
    private async Task SubmitPromptAsync(string text, bool speak)
    {
        if (_busy) return;
        SetBusy(true);
        bool willSpeak = speak && _voiceStatus.Tts;
        try
        {
            if (_activeSessionId is null)
            {
                _activeSessionId = await _backend.CreateSessionAsync();
                await ReloadSessionsAsync();
                SelectSessionInList(_activeSessionId);
            }

            var userMsg = new MessageItem("user", text);
            foreach (var chip in PendingAttachments) userMsg.Attachments.Add(chip);
            PendingAttachments.Clear();
            Messages.Add(userMsg);
            var reply = new MessageItem("assistant", "");
            Messages.Add(reply);
            ScrollToEnd();

            if (willSpeak) await _playback.ResetAsync();  // clear any prior playback

            var verdict = await _backend.PromptAsync(
                _activeSessionId!, text,
                onToken: fragment => _ui.TryEnqueue(() => { reply.Append(fragment); ScrollToEnd(); }),
                speak: willSpeak, voice: CurrentVoice(),
                onAudio: willSpeak ? (chunk => _playback.EnqueueAsync(chunk.Pcm16, chunk.SampleRate)) : null,
                onAudioCancel: willSpeak ? () => _ = _playback.ResetAsync() : null,
                // Editable ingest preview (#663): a new preview turn carries the
                // cleaned article body so the operator can edit-before-approve.
                onIngestPreview: meta => _ui.TryEnqueue(() =>
                {
                    reply.DocUuid = meta.DocUuid;
                    reply.SourceType = meta.SourceType;
                    reply.EditableBody = meta.EditableBody;
                    reply.IsIngestPreview = true;
                    ScrollToEnd();
                }),
                // Follow-up action buttons (#712): "image" → Edit/Save (ActionId
                // is the generated-image id); "dispatch_plan" → Approve/Reject.
                onUiActions: meta => _ui.TryEnqueue(() =>
                {
                    reply.ActionId = meta.Id;
                    reply.ActionKind = meta.Kind;
                    ScrollToEnd();
                }));

            _ui.TryEnqueue(() =>
            {
                if (!verdict.Approved)
                {
                    reply.Text = verdict.SanitizedText;
                    reply.IsDenied = true;
                    reply.ReasonText = string.Join(", ", verdict.ReasonCodes);
                }
                ScrollToEnd();
            });

            await ReloadSessionsAsync();
            SelectSessionInList(_activeSessionId);
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Message failed", ex.Message);
        }
        finally
        {
            SetBusy(false);
            PromptBox.Focus(FocusState.Programmatic);
        }
    }

    // ── Ingest editable preview: edit-before-approve (#663 Workstream A) ──

    /// <summary>Toggle the editable markdown-source box on a preview turn.</summary>
    private void OnIngestEditToggle(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: MessageItem item })
            item.IsEditing = !item.IsEditing;
    }

    /// <summary>Approve the pending ingest with the (possibly edited) preview body.</summary>
    private async void OnIngestApprove(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: MessageItem preview })
            await DecidePreviewAsync(preview, "approve", preview.EditableBody);
    }

    /// <summary>Reject (discard) the pending ingest. No body crosses anywhere.</summary>
    private async void OnIngestReject(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: MessageItem preview })
            await DecidePreviewAsync(preview, "reject", "");
    }

    /// <summary>
    /// Shared approve/reject path for the preview buttons (#663). Both decisions
    /// ride the structured ingest_decide channel — never the prompt path — so
    /// neither posts a synthetic command bubble, touches staged attachments, nor
    /// (for approve) lets the edited body reach sessions.db. The preview's action
    /// buttons are retired ONLY when the backend reports the decision took effect
    /// (slot cleared); a transient failure leaves them in place so the operator
    /// can retry rather than be stranded with a still-pending document and no
    /// controls. The busy lock is taken BEFORE the reconnect await so a click
    /// during reconnect cannot start a second round-trip.
    /// </summary>
    private async Task DecidePreviewAsync(MessageItem preview, string decision, string editedBody)
    {
        if (_busy || _activeSessionId is null) return;
        SetBusy(true);  // lock before ANY await — closes the reconnect double-click window
        try
        {
            if (!_backend.IsConnected)
            {
                await ConnectAndLoadAsync();
                if (!_backend.IsConnected) return;  // finally restores busy
            }

            preview.IsEditing = false;  // close the editor; buttons stay until the outcome is known
            var reply = new MessageItem("assistant", "");
            Messages.Add(reply);
            ScrollToEnd();

            bool decided = await _backend.IngestDecideAsync(
                _activeSessionId!, decision, editedBody,
                onToken: fragment => _ui.TryEnqueue(() => { reply.Append(fragment); ScrollToEnd(); }));

            // Decided (stored / rejected / superseded / deterministically refused
            // → slot cleared) retires the actions; still-pending (a transient
            // failure, surfaced in the reply text) keeps them for a retry.
            if (decided) preview.IsIngestPreview = false;

            await ReloadSessionsAsync();
            SelectSessionInList(_activeSessionId);
        }
        catch (Exception ex)
        {
            // Pipe-level failure: the gateway pending slot survives — keep the
            // buttons so the operator can retry or reject.
            ShowStatus(InfoBarSeverity.Error,
                decision == "approve" ? "Approve failed" : "Reject failed", ex.Message);
        }
        finally
        {
            SetBusy(false);
            PromptBox.Focus(FocusState.Programmatic);
        }
    }

    // ── Theme ───────────────────────────────────────────────────────────

    private void OnToggleTheme(object sender, RoutedEventArgs e)
    {
        if (this.Content is FrameworkElement root)
        {
            bool toDark = root.ActualTheme != ElementTheme.Dark;
            root.RequestedTheme = toDark ? ElementTheme.Dark : ElementTheme.Light;
            _prefs.Theme = toDark ? "Dark" : "Light";
            _prefs.Save();
            ThemeIcon.Glyph = toDark ? "" : ""; // moon (dark) / brightness (light)
        }
    }

    // ── Helpers ─────────────────────────────────────────────────────────

    private void ApplySavedTheme()
    {
        ElementTheme theme = _prefs.Theme switch
        {
            "Dark" => ElementTheme.Dark,
            "Light" => ElementTheme.Light,
            _ => ElementTheme.Default,
        };
        if (this.Content is FrameworkElement root)
            root.RequestedTheme = theme;
        ThemeIcon.Glyph = theme == ElementTheme.Dark ? "" : "";
    }

    private void SelectSessionInList(string? sessionId)
    {
        if (sessionId is null) return;
        foreach (var s in Sessions)
        {
            if (s.Id == sessionId) { SessionsList.SelectedItem = s; return; }
        }
    }

    private void SetBusy(bool busy)
    {
        _busy = busy;
        SendButton.IsEnabled = !busy;
        PromptBox.IsEnabled = !busy;
    }

    private void ScrollToEnd()
    {
        if (Messages.Count == 0) return;
        MessagesList.ScrollIntoView(Messages[^1]);
    }

    private void UpdateGreetingVisibility()
    {
        GreetingPanel.Visibility = Messages.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        MessagesList.Visibility = Messages.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
    }

    private void ShowStatus(InfoBarSeverity severity, string title, string message)
    {
        StatusBar.Severity = severity;
        StatusBar.Title = title;
        StatusBar.Message = message;
        StatusBar.IsOpen = true;
    }

    private void HideStatus() => StatusBar.IsOpen = false;

    // ── Phase 4: attachments + slash backdoor ────────────────────────────

    private nint Hwnd => WinRT.Interop.WindowNative.GetWindowHandle(this);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool ChangeWindowMessageFilterEx(
        IntPtr hwnd, uint msg, uint action, IntPtr changeInfo);

    private void EnableDragDropAcrossElevation()
    {
        // The UI normally runs de-elevated (Medium integrity; ADR-019), where
        // Explorer -> UI drag-drop is a same-integrity drop and needs no help.
        // This remains a safety net for the rare path where de-elevation was
        // unavailable and the launcher fell back to spawning the UI elevated:
        // Windows' UIPI then blocks the drop unless the cross-privilege drop
        // messages are allowed through the window message filter.
        const uint MSGFLT_ALLOW = 1;
        uint[] messages = { 0x0233 /*WM_DROPFILES*/, 0x004A /*WM_COPYDATA*/, 0x0049 /*WM_COPYGLOBALDATA*/ };
        try
        {
            foreach (var msg in messages)
                ChangeWindowMessageFilterEx(Hwnd, msg, MSGFLT_ALLOW, IntPtr.Zero);
        }
        catch { /* best-effort; a non-elevated run does not need this */ }
    }

    private async void OnAttach(object sender, RoutedEventArgs e)
    {
        try
        {
            // Win32 common dialog (not the WinRT picker); the de-elevated UI
            // reaches OneDrive cloud-only files through it (ADR-019).
            string? path = FileDialog.PickFile(Hwnd);
            if (!string.IsNullOrEmpty(path))
                await StageAttachmentAsync(path);
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Attach failed", ex.Message);
        }
    }

    private async void OnScreenshot(object sender, RoutedEventArgs e)
    {
        try
        {
            // Briefly hide BlarAI so the capture shows the desktop behind it.
            this.AppWindow?.Hide();
            await Task.Delay(250);
            string token = DateTime.Now.ToString("yyyyMMdd-HHmmss");
            string tmp = ScreenCapture.CapturePrimaryScreenToTemp(token);
            this.AppWindow?.Show();
            await StageAttachmentAsync(tmp);
        }
        catch (Exception ex)
        {
            this.AppWindow?.Show();
            ShowStatus(InfoBarSeverity.Error, "Screenshot failed", ex.Message);
        }
    }

    private void OnChatDragOver(object sender, DragEventArgs e)
    {
        if (e.DataView.Contains(StandardDataFormats.StorageItems))
        {
            e.AcceptedOperation = DataPackageOperation.Copy;
            e.DragUIOverride.Caption = "Attach to BlarAI";
            e.DragUIOverride.IsCaptionVisible = true;
        }
    }

    private async void OnChatDrop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var deferral = e.GetDeferral();
        try
        {
            var items = await e.DataView.GetStorageItemsAsync();
            foreach (var item in items)
                if (item is StorageFile file)
                    await StageAttachmentAsync(file.Path);
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Attach failed", ex.Message);
        }
        finally
        {
            deferral.Complete();
        }
    }

    private async Task StageAttachmentAsync(string srcPath)
    {
        if (!_backend.IsConnected)
        {
            await ConnectAndLoadAsync();
            if (!_backend.IsConnected) return;
        }
        try
        {
            if (_activeSessionId is null)
            {
                _activeSessionId = await _backend.CreateSessionAsync();
                await ReloadSessionsAsync();
                SelectSessionInList(_activeSessionId);
            }
            var info = await _backend.StoreAttachmentAsync(srcPath, _activeSessionId!);
            string userdataPath = Path.Combine(UserdataDir, info.Filename);
            PendingAttachments.Add(new AttachmentChip(info.Filename, info.MediaType, userdataPath));
            if (info.IsMedia)
                ShowStatus(InfoBarSeverity.Informational, "Attached", info.Message);
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Attach failed", ex.Message);
        }
    }

    private async void OnRemovePending(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement fe || fe.Tag is not string filename) return;
        var chip = PendingAttachments.FirstOrDefault(c => c.Filename == filename);
        if (chip is null) return;
        PendingAttachments.Remove(chip);
        // No per-document unstage exists on the backend; re-sync the staged
        // set to the remaining chips so a removed chip is truly not sent.
        if (_activeSessionId is not null)
        {
            await _backend.UnloadDocumentsAsync(_activeSessionId);
            foreach (var c in PendingAttachments.ToList())
                await _backend.LoadDocumentAsync(_activeSessionId, c.Filename);
        }
    }

    // ── Slash commands (power-user backdoor) ─────────────────────────────

    private async Task HandleSlashCommandAsync(string text)
    {
        _activeSessionId ??= await _backend.CreateSessionAsync();
        var parts = text.Split(new[] { ' ' }, 2);
        string cmd = parts[0].ToLowerInvariant();
        string arg = parts.Length > 1 ? parts[1].Trim() : "";

        switch (cmd)
        {
            case "/ls":
                var files = await _backend.ListUserdataFilesAsync();
                AddSystemMessage(files.Count == 0
                    ? "No loadable files in `userdata/`."
                    : "**Files in userdata/**\n" +
                      string.Join("\n", files.Select(f => $"- {f.Filename}  ({f.MediaType})")));
                break;
            case "/load":
                if (arg.Length == 0) { AddSystemMessage("Usage: `/load <filename>`"); break; }
                var loaded = await _backend.LoadDocumentAsync(_activeSessionId!, arg);
                PendingAttachments.Add(new AttachmentChip(
                    loaded.Filename, loaded.MediaType, Path.Combine(UserdataDir, loaded.Filename)));
                AddSystemMessage($"Loaded **{loaded.Filename}** — ask me about it."
                    + (loaded.IsMedia ? " " + loaded.Message : ""));
                break;
            case "/unload":
                await _backend.UnloadDocumentsAsync(_activeSessionId!);
                PendingAttachments.Clear();
                AddSystemMessage("Cleared loaded documents from this chat.");
                break;
            case "/rename":
                if (arg.Length == 0) { AddSystemMessage("Usage: `/rename <new title>`"); break; }
                await _backend.RenameSessionAsync(_activeSessionId!, arg);
                await ReloadSessionsAsync();
                SelectSessionInList(_activeSessionId);
                AddSystemMessage($"Renamed this chat to **{arg}**.");
                break;
            case "/trust":
                await _backend.TrustDocumentsAsync(_activeSessionId!);
                AddSystemMessage("Tools are now allowed in this chat even with documents loaded.");
                break;
            default:
                AddSystemMessage($"Unknown command `{cmd}`. Try /ls, /load, /unload, /rename, /trust, /ingest, /approve, /reject, /imagine, /illustrate, /cartoon, /edit, /save, /images.");
                break;
        }
    }

    private void AddSystemMessage(string markdown)
    {
        Messages.Add(new MessageItem("assistant", markdown));
        ScrollToEnd();
    }

    // ── Slash soft-autocomplete ──────────────────────────────────────────

    private const string SuggestSep = "  —  ";

    private void OnPromptTextChanged(object sender, TextChangedEventArgs e)
    {
        string t = PromptBox.Text;
        if (t.StartsWith("/") && !t.Contains(' '))
        {
            var matches = SlashCommands
                .Where(c => c.Cmd.TrimEnd().StartsWith(t, StringComparison.OrdinalIgnoreCase))
                .Select(c => $"{c.Cmd.Trim()}{SuggestSep}{c.Hint}")
                .ToList();
            if (matches.Count > 0)
            {
                SuggestList.ItemsSource = matches;
                SuggestBox.Visibility = Visibility.Visible;
                return;
            }
        }
        HideSuggestions();
    }

    private void HideSuggestions() => SuggestBox.Visibility = Visibility.Collapsed;

    private void OnSuggestionClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is not string s) return;
        string cmd = s.Split(SuggestSep)[0];
        // Commands that take an argument keep a trailing space ready to type.
        bool takesArg = cmd is "/load" or "/rename" or "/ingest" or "/dispatch";
        PromptBox.Text = cmd + (takesArg ? " " : "");
        PromptBox.SelectionStart = PromptBox.Text.Length;
        HideSuggestions();
        PromptBox.Focus(FocusState.Programmatic);
    }

    // ── Voice (ADR-017) ──────────────────────────────────────────────────

    /// <summary>Query the backend's voice availability and reflect it in the UI.</summary>
    private async Task LoadVoiceStatusAsync()
    {
        _voiceStatus = await _backend.GetVoiceStatusAsync();
        _ui.TryEnqueue(ApplyVoiceStatus);
    }

    // Re-entrancy guard: when we set ToggleSwitch.IsOn programmatically (e.g.
    // reverting a failed load, or reflecting status), the Toggled event fires —
    // this flag makes those handlers no-op so they don't loop back into a load.
    private bool _suppressVoiceToggle;

    private void ApplyVoiceStatus()
    {
        // Always-off-at-boot (#660 decision #3): the backend reports both halves
        // off at launch. The toggles stay ENABLED so the operator can turn a
        // feature on (which loads its model on demand); the mic composer button
        // and the voice picker reflect the ACTUAL loaded state.
        MicButton.IsEnabled = _voiceStatus.Stt;
        VoiceCombo.IsEnabled = _voiceStatus.Tts;

        _suppressVoiceToggle = true;
        VoiceOutputToggle.IsOn = _voiceStatus.Tts;
        MicToggle.IsOn = _voiceStatus.Stt;
        _suppressVoiceToggle = false;

        RefreshVoiceCombo();
    }

    private void RefreshVoiceCombo()
    {
        VoiceCombo.Items.Clear();
        foreach (var v in _voiceStatus.Voices) VoiceCombo.Items.Add(v);
        string current = CurrentVoice();
        if (VoiceCombo.Items.Contains(current)) VoiceCombo.SelectedItem = current;
        else if (VoiceCombo.Items.Count > 0) VoiceCombo.SelectedIndex = 0;
    }

    /// <summary>The voice id to synthesize with: saved choice, else backend default.</summary>
    private string CurrentVoice()
        => !string.IsNullOrEmpty(_prefs.Voice) ? _prefs.Voice : _voiceStatus.DefaultVoice;

    private async void OnMicButton(object sender, RoutedEventArgs e)
    {
        if (!_voiceStatus.Stt) return;
        if (!_recording)
        {
            _capture = new VoiceCapture();
            bool ok = await _capture.StartAsync();
            if (!ok)
            {
                string detail = _capture.LastError;
                _capture = null;
                ShowStatus(InfoBarSeverity.Warning, "Microphone unavailable",
                    string.IsNullOrEmpty(detail)
                        ? "Could not open the microphone."
                        : "Could not open the microphone — " + detail);
                return;
            }
            _recording = true;
            SetMicRecording(true);
            ShowStatus(InfoBarSeverity.Informational, "Listening…",
                "Speak, then tap the microphone again to stop and transcribe.");
            return;
        }

        // Second tap: stop, transcribe, drop the text into the composer. The WHOLE
        // flow (including StopAsync) is guarded so no failure can vanish silently
        // in this async-void handler; each step is logged for bring-up diagnosis.
        _recording = false;
        SetMicRecording(false);
        try
        {
            VoiceLog("stop tap — finalizing capture");
            var cap = _capture is not null
                ? await _capture.StopAsync()
                : new VoiceCapture.Result(Array.Empty<byte>(), 16000, 1, 0f);
            byte[] pcm = cap.Pcm;
            int sampleRate = cap.SampleRate;
            int channels = cap.Channels;
            string device = _capture?.DeviceName ?? "";
            string capErr = _capture?.LastError ?? "";
            if (_capture is not null) { await _capture.DisposeAsync(); _capture = null; }

            double seconds = channels > 0 ? pcm.Length / 2.0 / sampleRate / channels : 0;
            string diag = $"device: {device} · {seconds:0.0}s · {sampleRate}Hz · {channels}ch · peak {cap.Peak * 100:0}%";
            VoiceLog($"captured {pcm.Length} bytes — {diag} err='{capErr}'");

            if (pcm.Length == 0)
            {
                ShowStatus(InfoBarSeverity.Warning, "Didn't catch anything",
                    string.IsNullOrEmpty(capErr) ? diag : capErr);
                return;
            }

            MicButton.IsEnabled = false;
            ShowStatus(InfoBarSeverity.Informational, "Transcribing…", "");
            VoiceLog($"calling backend transcribe ({pcm.Length} bytes @ {sampleRate}Hz/{channels}ch)…");
            string text = await _backend.TranscribeAsync(pcm, sampleRate, channels);
            VoiceLog($"transcribe returned: '{text}'");
            if (!string.IsNullOrWhiteSpace(text))
            {
                // The end of the recording IS the prompt submission: the spoken
                // words go straight into the conversation and the assistant
                // responds. Whether the reply is SPOKEN back is governed by the
                // "Speak replies aloud" toggle (ADR-017) — voice input does not
                // force voice output; the user controls the audio of the response.
                HideStatus();
                MicButton.IsEnabled = _voiceStatus.Stt;
                await SubmitPromptAsync(text, speak: _prefs.VoiceOutput);
            }
            else
            {
                ShowStatus(InfoBarSeverity.Warning, "Didn't catch that", diag);
            }
        }
        catch (Exception ex)
        {
            VoiceLog($"EXCEPTION {ex.GetType().Name}: {ex.Message}");
            ShowStatus(InfoBarSeverity.Error, "Voice error", $"{ex.GetType().Name}: {ex.Message}");
            if (_capture is not null) { try { await _capture.DisposeAsync(); } catch { } _capture = null; }
        }
        finally
        {
            MicButton.IsEnabled = _voiceStatus.Stt;
            PromptBox.Focus(FocusState.Programmatic);
        }
    }

    private void SetMicRecording(bool recording)
    {
        // Swap to a filled stop glyph + red while recording so the state is
        // unmistakable; back to the mic glyph when idle.
        MicIcon.Glyph = recording ? "" : "";  // Stop / Microphone
        MicIcon.Foreground = recording
            ? new SolidColorBrush(Microsoft.UI.Colors.OrangeRed)
            : (Brush)Application.Current.Resources["TextFillColorPrimaryBrush"];
        ToolTipService.SetToolTip(MicButton,
            recording ? "Recording — tap to stop" : "Tap to talk; tap again to stop");
    }

    private async void OnPlayMessage(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: MessageItem item })
            await SpeakAsync(item.Text);
    }

    /// <summary>Synthesize and play <paramref name="text"/> incrementally.</summary>
    private async Task SpeakAsync(string text)
    {
        if (!_voiceStatus.Tts || string.IsNullOrWhiteSpace(text)) return;
        try
        {
            await _playback.ResetAsync();
            await foreach (var chunk in _backend.SynthesizeAsync(text, CurrentVoice()))
                await _playback.EnqueueAsync(chunk.Pcm16, chunk.SampleRate);
        }
        catch (Exception ex)
        {
            ShowStatus(InfoBarSeverity.Error, "Could not speak", ex.Message);
        }
    }

    /// <summary>
    /// "Voice replies (BlarAI speaks)" toggle (#660): ON loads the Kokoro TTS
    /// model on demand; OFF unloads it to reclaim RAM. The backend returns the
    /// refreshed status, which we apply (gating the voice picker + per-message
    /// play). A failed load (model not installed) reverts the toggle and shows
    /// the unavailable note rather than leaving a lying "On".
    /// </summary>
    private async void OnVoiceOutputToggled(object sender, RoutedEventArgs e)
    {
        if (_suppressVoiceToggle) return;
        bool wantOn = VoiceOutputToggle.IsOn;
        _prefs.VoiceOutput = wantOn;
        _prefs.Save();  // display-state only; never auto-loads at next boot (#660)
        await ApplyVoiceHalfAsync(
            wantOn, isStt: false, toggle: VoiceOutputToggle, ring: TtsLoadingRing);
    }

    /// <summary>
    /// "Microphone (BlarAI listens)" toggle (#660): ON loads the Whisper STT
    /// model on demand (the composer mic button lights up); OFF unloads it.
    /// </summary>
    private async void OnMicToggled(object sender, RoutedEventArgs e)
    {
        if (_suppressVoiceToggle) return;
        bool wantOn = MicToggle.IsOn;
        _prefs.MicEnabled = wantOn;
        _prefs.Save();  // display-state only; never auto-loads at next boot (#660)
        await ApplyVoiceHalfAsync(
            wantOn, isStt: true, toggle: MicToggle, ring: SttLoadingRing);
    }

    /// <summary>
    /// Shared load/unload path for a voice half. Shows a loading ring + disables
    /// the toggle for the (few-second) model load, calls the backend
    /// (<c>voice_set_stt</c> / <c>voice_set_tts</c>), applies the refreshed
    /// status, and — when an ON failed to load the half — reverts the toggle and
    /// surfaces the "models not installed" note. Guards re-entrancy so the revert
    /// does not re-trigger.
    /// </summary>
    private async Task ApplyVoiceHalfAsync(
        bool wantOn, bool isStt, ToggleSwitch toggle, ProgressRing ring)
    {
        if (!_backend.IsConnected)
        {
            await ConnectAndLoadAsync();
            if (!_backend.IsConnected)
            {
                _suppressVoiceToggle = true; toggle.IsOn = false; _suppressVoiceToggle = false;
                return;
            }
        }
        toggle.IsEnabled = false;
        if (wantOn) { ring.IsActive = true; ring.Visibility = Visibility.Visible; }
        try
        {
            _voiceStatus = isStt
                ? await _backend.SetSttAsync(wantOn)
                : await _backend.SetTtsAsync(wantOn);

            bool loaded = isStt ? _voiceStatus.Stt : _voiceStatus.Tts;
            MicButton.IsEnabled = _voiceStatus.Stt;
            VoiceCombo.IsEnabled = _voiceStatus.Tts;
            RefreshVoiceCombo();

            if (wantOn && !loaded)
            {
                // Asked to turn on but the model did not load (not installed /
                // load failure): revert the switch and tell the user.
                _suppressVoiceToggle = true; toggle.IsOn = false; _suppressVoiceToggle = false;
                VoiceUnavailableNote.Visibility = Visibility.Visible;
            }
            else
            {
                VoiceUnavailableNote.Visibility = Visibility.Collapsed;
            }
        }
        catch (Exception ex)
        {
            _suppressVoiceToggle = true; toggle.IsOn = false; _suppressVoiceToggle = false;
            ShowStatus(InfoBarSeverity.Error,
                isStt ? "Could not load microphone" : "Could not load voice", ex.Message);
        }
        finally
        {
            ring.IsActive = false; ring.Visibility = Visibility.Collapsed;
            toggle.IsEnabled = true;
        }
    }

    private void OnVoiceSelected(object sender, SelectionChangedEventArgs e)
    {
        if (VoiceCombo.SelectedItem is string voice && voice != _prefs.Voice)
        {
            _prefs.Voice = voice;
            _prefs.Save();
        }
    }

    /// <summary>Bring-up diagnostics: append a UI-side voice event to a log file.</summary>
    private static void VoiceLog(string msg)
    {
        try
        {
            string path = Path.Combine(UserdataDir, "_voice_ui.log");
            File.AppendAllText(path, $"{DateTime.Now:HH:mm:ss} {msg}{Environment.NewLine}");
        }
        catch { /* diagnostics only */ }
    }
}
