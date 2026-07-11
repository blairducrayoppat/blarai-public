using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using BlarAI.Desktop.Services;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Windows.UI.Text;

namespace BlarAI.Desktop.Controls;

/// <summary>
/// Lightweight markdown renderer for assistant replies — Gemini-style prose:
/// headings, bold/italic, inline code, fenced code blocks (with a copy button),
/// bullet/numbered lists, and links. Hand-rolled rather than taking a heavy
/// dependency, and tolerant of the half-finished markdown that arrives mid-stream
/// (an unclosed code fence renders as an in-progress code block).
///
/// Set <see cref="Markdown"/>; the control rebuilds its content on every change,
/// so binding it to a streaming string re-renders live as tokens arrive.
/// </summary>
public sealed class MarkdownBlock : ContentControl
{
    public MarkdownBlock()
    {
        HorizontalContentAlignment = HorizontalAlignment.Stretch;
    }

    /// <summary>
    /// Resolver for a <c>blarai-img://&lt;id&gt;</c> reference → the locally-decrypted
    /// PNG bytes (or <c>null</c> when the image is unavailable / forged / capped),
    /// injected ONCE at app/MainWindow init (set to
    /// <c>BackendClient.ResolveImageAsync</c>). It is a process-wide static because
    /// every markdown render path here is static (the control rebuilds its content
    /// on each <c>Markdown</c> change) and there is exactly one backend pipe per
    /// process; the alternative (threading a BackendClient instance through every
    /// static Build/AppendInlines call) would not buy isolation in a single-window
    /// app. Left <c>null</c> in tests / before wiring, in which case
    /// <see cref="BuildImageInline"/> never starts a resolve and the inert alt-text
    /// placeholder is the terminal state (display-only, fail-closed).
    ///
    /// SECURITY: the returned bytes are fed to <see cref="ImageResolver.ResolveAsync"/>,
    /// which builds the <c>ImageSource</c> from an in-memory buffer ONLY — never a
    /// Uri / network / file / data: source. This delegate is the sole bridge from
    /// the renderer to the resolve corridor; it carries bytes, never a navigable
    /// reference.
    /// </summary>
    public static Func<string, CancellationToken, Task<byte[]?>>? ImageBytesResolver { get; set; }

    /// <summary>
    /// Sender for an operator-preference PROPOSAL card's Save/Dismiss buttons
    /// (#770 M2 W1), injected ONCE at MainWindow init. The AO streams a
    /// <c>[[PREFERENCE-PROPOSAL token=…]]…[[/PREFERENCE-PROPOSAL]]</c> block inside
    /// the assistant message; <see cref="BuildProposalCard"/> renders a card whose
    /// buttons invoke this with EXACTLY <c>/remember-confirm &lt;token&gt;</c> /
    /// <c>/remember-dismiss &lt;token&gt;</c> — the same operator-typed commands
    /// the text fallback names. P8: this sends a COMMAND (operator authority);
    /// only the opaque token crosses, never a model-supplied body. Left
    /// <c>null</c> in tests / before wiring, in which case the buttons are inert
    /// (the readable text still names the commands to type).
    /// </summary>
    public static Func<string, Task>? ProposalCommandSender { get; set; }

    public static readonly DependencyProperty MarkdownProperty =
        DependencyProperty.Register(
            nameof(Markdown), typeof(string), typeof(MarkdownBlock),
            new PropertyMetadata("", OnMarkdownChanged));

    public string Markdown
    {
        get => (string)GetValue(MarkdownProperty);
        set => SetValue(MarkdownProperty, value);
    }

    private static void OnMarkdownChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        => ((MarkdownBlock)d).Render();

    private void Render() => Content = Build(Markdown ?? "");

    // ── Block-level: split prose from fenced code, emit a stack of elements ──

    private static UIElement Build(string text)
    {
        var root = new StackPanel { Spacing = 8 };
        var prose = new StringBuilder();

        void FlushProse()
        {
            if (prose.Length == 0) return;
            root.Children.Add(BuildProse(prose.ToString().TrimEnd('\n')));
            prose.Clear();
        }

        var lines = text.Replace("\r\n", "\n").Split('\n');
        int i = 0;
        while (i < lines.Length)
        {
            string line = lines[i];
            if (line.TrimStart().StartsWith("```"))
            {
                FlushProse();
                var code = new StringBuilder();
                string lang = line.TrimStart().Substring(3).Trim();
                i++;
                while (i < lines.Length && !lines[i].TrimStart().StartsWith("```"))
                {
                    code.Append(lines[i]).Append('\n');
                    i++;
                }
                i++; // consume closing fence (or run off the end if unclosed)
                root.Children.Add(BuildCodeBlock(code.ToString().TrimEnd('\n'), lang));
            }
            else if (line.TrimStart().StartsWith(Services.PreferenceProposalCard.OpenPrefix))
            {
                // #770 M2 W1 — operator-preference PROPOSAL card. The open marker
                // line carries the 16-hex staging token; collect the readable body
                // until the close marker, then render a card with Save/Dismiss
                // buttons. A malformed token renders the body as plain prose (never
                // a card) — the forged-token gate at the render boundary.
                FlushProse();
                string token = Services.PreferenceProposalCard.TokenFromOpenMarker(line.Trim());
                var cardBody = new StringBuilder();
                i++;
                while (i < lines.Length &&
                       !lines[i].TrimStart().StartsWith(Services.PreferenceProposalCard.CloseMarker))
                {
                    cardBody.Append(lines[i]).Append('\n');
                    i++;
                }
                i++; // consume the close marker (or run off the end if unclosed)
                string body = cardBody.ToString().Trim('\n');
                if (Services.PreferenceProposalCard.IsValidToken(token))
                    root.Children.Add(BuildProposalCard(token, body));
                else
                    root.Children.Add(BuildProse(body));
            }
            else
            {
                prose.Append(line).Append('\n');
                i++;
            }
        }
        FlushProse();
        return root;
    }

    // ── Prose: headings, lists, paragraphs → a RichTextBlock ─────────────────

    private static RichTextBlock BuildProse(string proseText)
    {
        var rtb = new RichTextBlock { LineHeight = 22, IsTextSelectionEnabled = true };
        foreach (var raw in proseText.Split('\n'))
        {
            string line = raw.TrimEnd();
            if (line.Length == 0)
            {
                rtb.Blocks.Add(new Paragraph { Margin = new Thickness(0, 2, 0, 2) });
                continue;
            }

            var para = new Paragraph { Margin = new Thickness(0, 2, 0, 2) };

            // Headings
            var h = Regex.Match(line, @"^(#{1,3})\s+(.*)$");
            if (h.Success)
            {
                para.FontWeight = FontWeights.SemiBold;
                para.FontSize = h.Groups[1].Value.Length switch { 1 => 22, 2 => 18, _ => 16 };
                AppendInlines(para, h.Groups[2].Value);
                rtb.Blocks.Add(para);
                continue;
            }

            // Bullet / numbered lists
            var bullet = Regex.Match(line, @"^\s*[-*]\s+(.*)$");
            var number = Regex.Match(line, @"^\s*(\d+)[.)]\s+(.*)$");
            if (bullet.Success)
            {
                para.Margin = new Thickness(14, 1, 0, 1);
                para.Inlines.Add(new Run { Text = "•  " });
                AppendInlines(para, bullet.Groups[1].Value);
                rtb.Blocks.Add(para);
                continue;
            }
            if (number.Success)
            {
                para.Margin = new Thickness(14, 1, 0, 1);
                para.Inlines.Add(new Run { Text = number.Groups[1].Value + ".  " });
                AppendInlines(para, number.Groups[2].Value);
                rtb.Blocks.Add(para);
                continue;
            }

            AppendInlines(para, line);
            rtb.Blocks.Add(para);
        }
        return rtb;
    }

    // ── Inline: ![alt](img), **bold**, *italic*, `code`, [text](url) ─────────
    //
    // The image alternative MUST come first so that "![alt](url)" is consumed as
    // an image (it owns the leading "!") rather than the trailing "[alt](url)"
    // being mis-read as a plain link. Only the host-internal "blarai-img://"
    // scheme ever becomes a real image; AppendInlines refuses every other scheme
    // in the image slot and falls back to the alt placeholder (display-only,
    // never navigable — see UC-003 Workstream B).
    private static readonly Regex InlinePattern = new(
        @"(!\[(?<ia>.*?)\]\((?<iu>[^)]*)\))" +
        @"|(\*\*(?<b>.+?)\*\*)" +
        @"|(\*(?<i>.+?)\*)" +
        @"|(`(?<c>.+?)`)" +
        @"|(\[(?<lt>.+?)\]\((?<lu>[^)]+)\))",
        RegexOptions.Compiled);

    private static void AppendInlines(Paragraph para, string text)
    {
        int pos = 0;
        foreach (Match m in InlinePattern.Matches(text))
        {
            if (m.Index > pos)
                para.Inlines.Add(new Run { Text = text.Substring(pos, m.Index - pos) });

            if (m.Groups["ia"].Success)
                para.Inlines.Add(BuildImageInline(m.Groups["ia"].Value, m.Groups["iu"].Value));
            else if (m.Groups["b"].Success)
                para.Inlines.Add(new Run { Text = m.Groups["b"].Value, FontWeight = FontWeights.SemiBold });
            else if (m.Groups["i"].Success)
                para.Inlines.Add(new Run { Text = m.Groups["i"].Value, FontStyle = FontStyle.Italic });
            else if (m.Groups["c"].Success)
                para.Inlines.Add(new Run
                {
                    Text = m.Groups["c"].Value,
                    FontFamily = new FontFamily("Consolas, Cascadia Mono, monospace"),
                });
            else if (m.Groups["lt"].Success)
            {
                var link = new Hyperlink();
                link.Inlines.Add(new Run { Text = m.Groups["lt"].Value });
                // Defense-in-depth: ONLY http/https links are navigable. An
                // active-scheme URL (javascript:, data:, file:, vbscript:, …) is
                // rendered as inert text, never a navigable target. The cleaner's
                // escape pass already neutralizes such URLs upstream; this is the
                // belt-and-suspenders second layer at the render boundary.
                if (Uri.TryCreate(m.Groups["lu"].Value, UriKind.Absolute, out var uri)
                    && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
                    link.NavigateUri = uri;
                para.Inlines.Add(link);
            }
            pos = m.Index + m.Length;
        }
        if (pos < text.Length)
            para.Inlines.Add(new Run { Text = text.Substring(pos) });
    }

    // ── Inline image: ![alt](blarai-img://<id>) — display-only, never navigable

    /// <summary>
    /// Render an inline image reference. STRICTLY display-only, read-only: only
    /// the host-internal "blarai-img://" scheme is honoured and only as
    /// locally-decrypted pixels; we NEVER set NavigateUri / PointerPressed /
    /// Tapped or any click/launch handler, and we NEVER build an ImageSource from
    /// a URL/network/data:/javascript: source. Any non-image scheme, a forged id,
    /// the absence of decrypted bytes, or a corrupt decode falls back to a safe
    /// "[image: alt]" text placeholder. The alt is HTML-escaped at render time
    /// (defense-in-depth) so it can never smuggle markup or active content.
    ///
    /// LIVE-PIXEL FLOW (UC-010 #666/#665 Pass B): the resolve corridor is async
    /// (the decrypted PNG arrives over the IMAGE_RESOLVE pipe leg), so this returns
    /// SYNCHRONOUSLY with a placeholder and fills the pixels when they arrive:
    ///   1. Refuse any non-blarai-img:// scheme / forged id up front → inert alt
    ///      Run (no resolve attempted, no container).
    ///   2. If no resolver is wired (tests / before MainWindow init) → inert alt
    ///      Run (terminal placeholder; fail-closed).
    ///   3. Otherwise: emit an InlineUIContainer holding a constrained, hit-test-off
    ///      Image with NO source yet, and kick off the async resolve. On success
    ///      the decoded BitmapImage (built from the in-memory buffer only) becomes
    ///      the Image.Source on the UI thread; on null/error the container's child
    ///      is swapped to the alt-text placeholder. The Image never holds anything
    ///      but an in-memory BitmapImage — never a Uri / network / data: source.
    /// </summary>
    private static Inline BuildImageInline(string altRaw, string url)
    {
        string alt = ImageResolver.EscapeAlt(altRaw);
        Inline Placeholder() =>
            new Run { Text = "[image: " + alt + "]", FontStyle = FontStyle.Italic };

        // Scheme + id gate first: anything that is not a well-formed
        // "blarai-img://<32-hex>" ref (http(s), data:, javascript:, file:, a forged
        // / malformed id, …) never reaches the resolve path — it degrades to the
        // inert alt placeholder, never a network/active source.
        string? imageId = ImageResolver.ExtractImageId(url);
        if (imageId is null) return Placeholder();

        // No resolver wired (unit tests, or before MainWindow init): there is no
        // way to obtain decrypted bytes, so the placeholder is terminal.
        var resolver = ImageBytesResolver;
        if (resolver is null) return Placeholder();

        // Display-only Image: no source yet (renders as nothing until the pixels
        // arrive), strictly read-only — no NavigateUri (Image has none), no
        // pointer/tap handlers, IsHitTestVisible off.
        var image = new Image
        {
            Stretch = Stretch.Uniform,
            MaxWidth = 480,
            MaxHeight = 360,
            IsHitTestVisible = false,
        };
        ToolTipService.SetToolTip(image, altRaw);          // alt as a hover label only
        AutomationProperties.SetName(image, altRaw);       // accessible name = alt
        var container = new InlineUIContainer { Child = image };

        // BuildImageInline runs during Render() on the UI thread, so this captures
        // the UI DispatcherQueue to marshal the Source assignment / placeholder
        // swap back after the off-thread resolve completes.
        DispatcherQueue ui = DispatcherQueue.GetForCurrentThread();
        _ = FillImageAsync(resolver, imageId, image, container, alt, ui);
        return container;
    }

    /// <summary>
    /// Async fill for an inline image placeholder: resolve the id to decrypted
    /// bytes, decode to a BitmapImage off an in-memory buffer, and set the Image's
    /// Source on the UI thread. Fail-closed in every direction — a null/empty/over-
    /// cap result from the resolver, a corrupt decode, or any exception leaves the
    /// placeholder swapped to inert alt text; nothing is ever sourced from a Uri,
    /// the network, or a data: payload, and nothing throws back to the render path.
    /// </summary>
    private static async Task FillImageAsync(
        Func<string, CancellationToken, Task<byte[]?>> resolver,
        string imageId, Image image, InlineUIContainer container, string alt,
        DispatcherQueue ui)
    {
        void ShowPlaceholder()
        {
            // Replace the (sourceless, invisible) Image with the alt-text placeholder
            // so a missing/forged/corrupt image renders identically to a refused one.
            if (!ui.TryEnqueue(() =>
                    container.Child = new TextBlock
                    {
                        Text = "[image: " + alt + "]",
                        FontStyle = FontStyle.Italic,
                    }))
            {
                // UI queue gone (window closing) — nothing to render; safe no-op.
            }
        }

        try
        {
            byte[]? bytes = await resolver(imageId, CancellationToken.None).ConfigureAwait(false);
            if (bytes is null || bytes.Length == 0)
            {
                ShowPlaceholder();
                return;
            }

            // Decode on the UI thread: BitmapImage is a DependencyObject and
            // SetSourceAsync must run on the thread that will display it. The bytes
            // are already in hand (resolved off-thread); only the decode is enqueued.
            ui.TryEnqueue(async void () =>
            {
                try
                {
                    ImageSource? source = await ImageResolver.ResolveAsync(bytes);
                    if (source is null)
                        container.Child = new TextBlock
                        {
                            Text = "[image: " + alt + "]",
                            FontStyle = FontStyle.Italic,
                        };
                    else
                        image.Source = source;  // in-memory BitmapImage ONLY
                }
                catch
                {
                    // Corrupt/unrenderable bytes: fail closed to the alt placeholder.
                    container.Child = new TextBlock
                    {
                        Text = "[image: " + alt + "]",
                        FontStyle = FontStyle.Italic,
                    };
                }
            });
        }
        catch
        {
            // Resolver / pipe failure: keep the display-only contract — alt text.
            ShowPlaceholder();
        }
    }

    // ── Code block: monospace card with a copy button ───────────────────────

    private static UIElement BuildCodeBlock(string code, string lang)
    {
        var border = new Border
        {
            Background = (Brush)Application.Current.Resources["CardBackgroundFillColorSecondaryBrush"],
            BorderBrush = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"],
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(12, 10, 12, 10),
        };

        var grid = new Grid();
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var header = new Grid { Margin = new Thickness(0, 0, 0, 6) };
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        if (!string.IsNullOrWhiteSpace(lang))
        {
            var label = new TextBlock { Text = lang, FontSize = 11, Opacity = 0.6 };
            header.Children.Add(label);
        }
        var copy = new Button
        {
            Content = new FontIcon { Glyph = "", FontSize = 12 }, // Copy
            Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent),
            BorderThickness = new Thickness(0),
            Padding = new Thickness(6, 2, 6, 2),
        };
        ToolTipService.SetToolTip(copy, "Copy");
        copy.Click += (_, _) =>
        {
            var dp = new Windows.ApplicationModel.DataTransfer.DataPackage();
            dp.SetText(code);
            Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(dp);
        };
        Grid.SetColumn(copy, 1);
        header.Children.Add(copy);
        Grid.SetRow(header, 0);
        grid.Children.Add(header);

        var codeText = new TextBlock
        {
            Text = code,
            FontFamily = new FontFamily("Consolas, Cascadia Mono, monospace"),
            TextWrapping = TextWrapping.Wrap,
            IsTextSelectionEnabled = true,
        };
        Grid.SetRow(codeText, 1);
        grid.Children.Add(codeText);

        border.Child = grid;
        return border;
    }

    // ── Preference proposal card: readable text + Save/Dismiss (#770 M2 W1) ───

    /// <summary>
    /// Render an operator-preference PROPOSAL as a card: the shared backend's
    /// readable text (shown as LITERAL text — never re-parsed as markdown, so a
    /// proposed body's <c>*</c>/<c>[]</c> can't become formatting) plus Save and
    /// Dismiss buttons. The buttons emit EXACTLY
    /// <c>PreferenceProposalCard.ConfirmCommand(token)</c> /
    /// <c>DismissCommand(token)</c> via <see cref="ProposalCommandSender"/> — the
    /// same operator-typed commands the text names (P8: operator authority; only
    /// the token crosses). Both buttons disable after one click (a proposal is
    /// single-use; the AO's token pop is the authoritative one-shot).
    /// </summary>
    private static UIElement BuildProposalCard(string token, string body)
    {
        var border = new Border
        {
            Background = (Brush)Application.Current.Resources["CardBackgroundFillColorSecondaryBrush"],
            BorderBrush = (Brush)Application.Current.Resources["AccentControlElevationBorderBrush"],
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(14, 12, 14, 12),
        };

        var stack = new StackPanel { Spacing = 10 };
        stack.Children.Add(new TextBlock
        {
            Text = body,
            TextWrapping = TextWrapping.Wrap,
            IsTextSelectionEnabled = true,
        });

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        var save = new Button { Content = "Save preference" };
        var dismiss = new Button { Content = "Dismiss" };

        async void SendThenDisable(string command)
        {
            save.IsEnabled = false;
            dismiss.IsEnabled = false;
            var sender = ProposalCommandSender;
            if (sender is not null && command.Length > 0)
            {
                try { await sender(command); }
                catch { /* send failure is surfaced by the send path itself */ }
            }
        }

        save.Click += (_, _) =>
            SendThenDisable(Services.PreferenceProposalCard.ConfirmCommand(token));
        dismiss.Click += (_, _) =>
            SendThenDisable(Services.PreferenceProposalCard.DismissCommand(token));

        buttons.Children.Add(dismiss);
        buttons.Children.Add(save);
        stack.Children.Add(buttons);

        border.Child = stack;
        return border;
    }
}
