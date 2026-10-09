using System;
using System.IO;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Loads the Auditability Card (#1544) for display in the app (#1583).
///
/// THE CARD IS NEVER RE-TYPED, and that is the entire point of this class.
/// <c>docs/governance/auditability-card.md</c> is the one copy; the csproj
/// copies it next to the build as <c>Governance/auditability-card.md</c> and
/// this loader reads THAT FILE at runtime. There is no second copy to drift,
/// so there is no drift to detect.
///
/// The alternative the ticket allowed — a hand-maintained screen plus a gate
/// asserting the two agree — is the shape that has already failed in this
/// project more than once, most visibly in the WinUI passthrough allowlist,
/// where a hand-copied C# array silently dropped a live command twice. That
/// pattern exists because C# and Python cannot share a literal. They CAN share
/// a file, so here they do.
///
/// FAIL-CLOSED, AND FAIL-LOUD. When the card cannot be read, this returns a
/// refusal rather than an empty page or a partial render. A disclosure screen
/// that silently shows less than the disclosure is the one failure mode that
/// matters: it converts an unknown into a false assurance, which is worse than
/// showing nothing (security_by_design 11).
///
/// No WinUI dependency, so the headless xUnit project compiles it via a Compile
/// link — the <see cref="ImageResolver"/> Core-partial isolation pattern.
/// </summary>
public static class AuditabilityCard
{
    /// <summary>
    /// Where the card sits relative to the running app. Set by the csproj
    /// Content copy; the gate test asserts the csproj and this constant agree,
    /// because a copy that lands anywhere else renders the refusal forever.
    /// </summary>
    public const string RelativePath = "Governance/auditability-card.md";

    /// <summary>What the screen shows when the card cannot be read.</summary>
    public const string UnavailableHeading = "# The auditability disclosure could not be loaded";

    /// <summary>
    /// The card's body, with its YAML frontmatter removed, or a refusal.
    /// </summary>
    /// <param name="baseDirectory">
    /// Where to look. The app passes <c>AppContext.BaseDirectory</c>; tests pass
    /// a temporary directory. Never defaulted, so a caller cannot accidentally
    /// read from the current working directory, which is whatever the operator
    /// happened to launch from.
    /// </param>
    public static Result Load(string baseDirectory)
    {
        if (string.IsNullOrWhiteSpace(baseDirectory))
            return Result.Unavailable("no application directory was given.");

        var path = Path.Combine(baseDirectory, RelativePath.Replace('/', Path.DirectorySeparatorChar));

        string text;
        try
        {
            // File.Exists swallows EVERY exception and returns false, so a card
            // that is present but unreadable (an ACL denial, a path the process
            // cannot traverse) used to take the "there is no card" branch --
            // a confidently wrong reason for a fail-closed refusal, with the
            // honest message sitting unreachable in the catch below.
            text = File.ReadAllText(path);
        }
        catch (FileNotFoundException)
        {
            return Result.Unavailable($"there is no card at {path}.");
        }
        catch (DirectoryNotFoundException)
        {
            return Result.Unavailable($"there is no card at {path}.");
        }
        catch (Exception ex)
        {
            // EVERY other exception, deliberately broad. The narrow filter that
            // used to sit here (IOException / UnauthorizedAccessException /
            // NotSupportedException) let SecurityException and ArgumentException
            // escape a synchronous void event handler, which takes the whole app
            // down. A crash is loud, and loud beats a false clean -- but this
            // path exists to REFUSE, and refusing is louder still because it
            // tells the operator what is missing and where to read it instead.
            return Result.Unavailable($"the card at {path} could not be read: {ex.Message}");
        }

        if (string.IsNullOrWhiteSpace(text))
            return Result.Unavailable($"the card at {path} is empty.");

        var body = StripFrontMatter(text);
        if (string.IsNullOrWhiteSpace(body))
            return Result.Unavailable($"the card at {path} has no content below its header block.");

        return new Result(true, body, null);
    }

    /// <summary>
    /// Remove a leading YAML frontmatter block (<c>---</c> … <c>---</c>).
    ///
    /// Returns the text unchanged when there is no frontmatter, and — this is
    /// the part that matters — also when the opening fence is never closed.
    /// Treating an unclosed fence as "everything is frontmatter" would render a
    /// blank disclosure from a file that is entirely present, which is exactly
    /// the silent-less-than-the-truth failure this class exists to avoid.
    /// </summary>
    public static string StripFrontMatter(string text)
    {
        if (text is null) return string.Empty;

        var normalised = text.Replace("\r\n", "\n");
        if (!normalised.StartsWith("---\n", StringComparison.Ordinal))
            return text;

        var close = normalised.IndexOf("\n---", 3, StringComparison.Ordinal);
        if (close < 0)
            return text;  // unclosed: keep everything rather than show nothing

        var after = normalised.IndexOf('\n', close + 1);
        return after < 0 ? text : normalised[(after + 1)..].TrimStart('\n');
    }

    /// <summary>The outcome of a load: the body, or why there is not one.</summary>
    public sealed record Result(bool Available, string Body, string? Reason)
    {
        public static Result Unavailable(string reason) => new(
            false,
            UnavailableHeading + "\n\n" +
            "This screen shows BlarAI's own disclosure of which of its actions are " +
            "recorded and which are not. It could not be shown, so **treat nothing " +
            "here as assurance** — this is a missing answer, not a clean one.\n\n" +
            "Reason: " + reason + "\n\n" +
            "The disclosure itself lives at `docs/governance/auditability-card.md` " +
            "in the BlarAI folder and can be read there directly.",
            reason);
    }
}
