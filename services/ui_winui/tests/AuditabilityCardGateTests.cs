using System;
using System.IO;
using BlarAI.Desktop.Services;
using Xunit;

namespace BlarAI.Desktop.Tests;

/// <summary>
/// Headless coverage for the in-app auditability disclosure loader (#1583).
///
/// The screen exists so the operator who owns the risk can read BlarAI's own
/// statement of which actions are recorded and which are NOT — including the
/// rows that say "no". Every test here is about one question: can the screen
/// ever show LESS than the disclosure without saying so?
///
/// It must not, because a coverage screen that quietly shows less converts an
/// unknown into a false assurance, which is strictly worse than showing nothing.
/// </summary>
public class AuditabilityCardGateTests
{
    private static string WriteCard(string body, string? name = null)
    {
        var dir = Path.Combine(Path.GetTempPath(), "blarai-card-" + Guid.NewGuid().ToString("N"));
        var target = Path.Combine(dir, AuditabilityCard.RelativePath.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        File.WriteAllText(target, body);
        return dir;
    }

    // ── The card loads, and loads whole ──────────────────────────────────────

    [Fact]
    public void A_present_card_loads_and_keeps_its_body()
    {
        var dir = WriteCard("---\ntitle: Auditability Card\n---\n\n# Card\n\n| a | b |\n|---|---|\n| no | yes |\n");

        var result = AuditabilityCard.Load(dir);

        Assert.True(result.Available);
        Assert.Contains("# Card", result.Body);
        Assert.Contains("| no | yes |", result.Body);
        Assert.Null(result.Reason);
    }

    [Fact]
    public void The_frontmatter_is_removed_but_nothing_below_it_is()
    {
        var dir = WriteCard("---\ntitle: t\nstatus: living\n---\n\nFIRST LINE\n\nlast line\n");

        var body = AuditabilityCard.Load(dir).Body;

        Assert.DoesNotContain("status: living", body);
        Assert.StartsWith("FIRST LINE", body);
        Assert.Contains("last line", body);
    }

    [Fact]
    public void A_card_with_no_frontmatter_is_untouched()
    {
        const string text = "# Straight into it\n\nno frontmatter here\n";
        var dir = WriteCard(text);

        Assert.Equal(text, AuditabilityCard.Load(dir).Body);
    }

    [Fact]
    public void An_unclosed_frontmatter_fence_keeps_the_whole_file()
    {
        // Treating an unclosed fence as "all frontmatter" would render a BLANK
        // disclosure from a file that is entirely present — a silent
        // less-than-the-truth, which is the one failure that matters here.
        const string text = "---\ntitle: t\n\n# The disclosure\n\nrow that must survive\n";

        var body = AuditabilityCard.StripFrontMatter(text);

        Assert.Contains("row that must survive", body);
        Assert.Contains("# The disclosure", body);
    }

    // ── It refuses rather than showing less ──────────────────────────────────

    [Fact]
    public void A_missing_card_refuses_LOUDLY_instead_of_showing_an_empty_page()
    {
        var dir = Path.Combine(Path.GetTempPath(), "blarai-card-absent-" + Guid.NewGuid().ToString("N"));

        var result = AuditabilityCard.Load(dir);

        Assert.False(result.Available);
        Assert.Contains("could not be loaded", result.Body);
        Assert.Contains("treat nothing", result.Body, StringComparison.OrdinalIgnoreCase);
        Assert.NotNull(result.Reason);
        // It must say where to read the real thing instead.
        Assert.Contains("docs/governance/auditability-card.md", result.Body);
    }

    [Fact]
    public void An_empty_card_file_refuses()
    {
        var dir = WriteCard("   \n\n  \n");

        var result = AuditabilityCard.Load(dir);

        Assert.False(result.Available);
        Assert.Contains("empty", result.Reason!);
    }

    [Fact]
    public void A_card_that_is_frontmatter_and_nothing_else_refuses()
    {
        // The nastiest shape: the file is present and well-formed, and has no
        // disclosure in it. Rendering the empty remainder would look like a
        // system with nothing to disclose.
        var dir = WriteCard("---\ntitle: t\n---\n\n\n");

        var result = AuditabilityCard.Load(dir);

        Assert.False(result.Available);
        Assert.Contains("no content", result.Reason!);
    }

    [Fact]
    public void No_base_directory_refuses_rather_than_reading_the_working_directory()
    {
        // Falling back to the current directory would read whatever the operator
        // happened to launch from.
        foreach (var bad in new[] { "", "   ", null })
        {
            var result = AuditabilityCard.Load(bad!);
            Assert.False(result.Available);
        }
    }

    // ── The refusal is not mistakable for the disclosure ─────────────────────

    [Fact]
    public void The_refusal_text_is_never_returned_as_available()
    {
        var absent = AuditabilityCard.Load(Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N")));
        var present = AuditabilityCard.Load(WriteCard("---\nt: x\n---\n\n# real\n"));

        Assert.False(absent.Available);
        Assert.True(present.Available);
        Assert.DoesNotContain(AuditabilityCard.UnavailableHeading, present.Body);
    }
}
