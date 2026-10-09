using System;
using System.Collections.Generic;
using System.Linq;
using BlarAI.Desktop.Services;
using Xunit;

namespace BlarAI.Desktop.Tests;

/// <summary>
/// Headless coverage for pipe-table recognition (#1583).
///
/// Two failure directions, and the second is the one that would be noticed
/// last. Failing to recognise a table mangles the auditability disclosure into
/// wrapped prose, which is visible immediately. Recognising a table where there
/// is none silently eats ordinary assistant replies containing a bar, and
/// nobody would connect that to this change.
///
/// So the recognition boundary is tested from both sides.
/// </summary>
public class MarkdownTableGateTests
{
    private static List<string> L(params string[] lines) => lines.ToList();

    // ── It recognises a real table ───────────────────────────────────────────

    [Fact]
    public void A_header_and_separator_start_a_table()
    {
        var parsed = MarkdownTable.TryParse(
            L("| Surface | Records? |", "|---|---|", "| tool loop | No |", "| ingest | Yes |"), 0);

        Assert.NotNull(parsed);
        Assert.Equal(new[] { "Surface", "Records?" }, parsed!.Header);
        Assert.Equal(2, parsed.Rows.Count);
        Assert.Equal(new[] { "ingest", "Yes" }, parsed.Rows[1]);
        Assert.Equal(4, parsed.LinesConsumed);
    }

    [Fact]
    public void It_stops_at_the_first_line_that_is_not_a_row()
    {
        var parsed = MarkdownTable.TryParse(
            L("| a | b |", "|---|---|", "| 1 | 2 |", "", "prose after"), 0);

        Assert.NotNull(parsed);
        Assert.Single(parsed!.Rows);
        Assert.Equal(3, parsed.LinesConsumed);
    }

    [Theory]
    [InlineData("|---|---|")]
    [InlineData("| --- | --- |")]
    [InlineData("|:---|---:|")]
    [InlineData("|:-:|:-:|")]
    public void Alignment_markers_are_still_separators(string separator)
        => Assert.True(MarkdownTable.IsSeparator(separator));

    // ── It does NOT eat prose ────────────────────────────────────────────────

    [Fact]
    public void A_sentence_containing_a_bar_is_not_a_table()
        => Assert.Null(MarkdownTable.TryParse(L("use grep | sort", "to sort output"), 0));

    [Fact]
    public void A_pipe_row_with_no_separator_under_it_is_not_a_table()
        => Assert.Null(MarkdownTable.TryParse(L("| not | really |", "| still | not |"), 0));

    [Theory]
    [InlineData("| just text |")]
    [InlineData("| -- x -- |")]
    [InlineData("|   |")]
    [InlineData("")]
    [InlineData(null)]
    public void These_are_not_separators(string? line)
        => Assert.False(MarkdownTable.IsSeparator(line));

    [Fact]
    public void A_table_at_the_very_end_of_the_input_does_not_run_off()
    {
        Assert.Null(MarkdownTable.TryParse(L("| a | b |"), 0));
        var parsed = MarkdownTable.TryParse(L("| a | b |", "|---|---|"), 0);
        Assert.NotNull(parsed);
        Assert.Empty(parsed!.Rows);
    }

    // ── Cell splitting, on the shapes this project's own tables use ──────────

    [Fact]
    public void A_pipe_inside_inline_code_does_not_split_a_cell()
    {
        // The governance tables contain things like `a | b` in code spans.
        var cells = MarkdownTable.SplitRow("| `grep | sort` | second |");

        Assert.Equal(2, cells.Count);
        Assert.Equal("`grep | sort`", cells[0]);
        Assert.Equal("second", cells[1]);
    }

    [Fact]
    public void An_escaped_pipe_does_not_split_a_cell()
    {
        var cells = MarkdownTable.SplitRow(@"| a \| b | c |");

        Assert.Equal(2, cells.Count);
        Assert.Equal("a | b", cells[0]);
    }

    [Fact]
    public void A_short_row_is_padded_rather_than_dropped()
    {
        // A malformed row in a DISCLOSURE must still be shown. Dropping it is
        // the silent less-than-the-truth this screen exists to avoid.
        var parsed = MarkdownTable.TryParse(
            L("| a | b | c |", "|---|---|---|", "| only-one |"), 0);

        Assert.NotNull(parsed);
        Assert.Single(parsed!.Rows);
        Assert.Equal(3, parsed.Rows[0].Count);
        Assert.Equal("only-one", parsed.Rows[0][0]);
        Assert.Equal("", parsed.Rows[0][2]);
    }

    [Fact]
    public void Rows_without_outer_pipes_still_parse()
    {
        var parsed = MarkdownTable.TryParse(L("a | b", "---|---", "1 | 2"), 0);

        Assert.NotNull(parsed);
        Assert.Equal(new[] { "a", "b" }, parsed!.Header);
        Assert.Equal(new[] { "1", "2" }, parsed.Rows[0]);
    }

    // -- The real disclosure parses. THE REAL ONE. ---------------------------

    [Fact]
    public void Every_table_in_the_REAL_auditability_card_parses()
    {
        // Loaded through the SHIPPED loader from the SHIPPED copy. An earlier
        // version of this test hand-copied three rows out of the card, and the
        // copy had already drifted -- it abridged "Inline - and the **only**
        // surface that writes receipts today" to "Inline", dropping exactly the
        // qualification that makes the row honest. The method still called
        // itself "the real disclosure parses".
        var card = AuditabilityCard.Load(AppContext.BaseDirectory);
        Assert.True(card.Available, "the card is not shipped into the test output: " + card.Reason);

        var lines = card.Body.Replace("\r\n", "\n").Split('\n');

        int tables = 0, rows = 0;
        for (int i = 0; i < lines.Length; i++)
        {
            var parsed = MarkdownTable.TryParse(lines, i);
            if (parsed is null) continue;
            tables++;
            rows += parsed.Rows.Count;
            foreach (var row in parsed.Rows)
                Assert.True(row.Count >= parsed.Header.Count,
                    $"a row in the card has fewer cells ({row.Count}) than its header ({parsed.Header.Count})");
            i += parsed.LinesConsumed - 1;
        }

        Assert.True(tables >= 1, "no table in the real card was recognised at all");
        Assert.True(rows >= 5, $"only {rows} rows parsed out of the real card");
    }

    [Fact]
    public void No_line_of_the_REAL_card_is_lost_between_parser_and_prose()
    {
        // Every line is either consumed by a table or left as prose. A line that
        // is neither would vanish from the screen.
        var card = AuditabilityCard.Load(AppContext.BaseDirectory);
        Assert.True(card.Available, card.Reason);
        var lines = card.Body.Replace("\r\n", "\n").Split('\n');

        var accounted = new bool[lines.Length];
        for (int i = 0; i < lines.Length; i++)
        {
            if (accounted[i]) continue;
            var parsed = MarkdownTable.TryParse(lines, i);
            if (parsed is null) { accounted[i] = true; continue; }
            for (int k = i; k < i + parsed.LinesConsumed && k < lines.Length; k++)
                accounted[k] = true;
            i += parsed.LinesConsumed - 1;
        }

        Assert.DoesNotContain(false, accounted);
    }

    [Fact]
    public void A_row_with_MORE_cells_than_its_header_keeps_them_all()
    {
        // The parser's contract, and what the renderer must honour: review found
        // the renderer sized itself to the header and silently dropped the
        // overflow, which in a real repo file was the failure reason itself.
        var parsed = MarkdownTable.TryParse(
            L("| a | b |", "|---|---|", "| 1 | 2 | THIRD-CELL |"), 0);

        Assert.NotNull(parsed);
        Assert.Equal(3, parsed!.Rows[0].Count);
        Assert.Equal("THIRD-CELL", parsed.Rows[0][2]);
    }

    // -- Ordinary prose is not a table --------------------------------------

    [Theory]
    [InlineData("Pick Option A | Option B for now.", "---")]
    [InlineData("Run `cat log | grep ERROR` to filter.", "---")]
    [InlineData("- pipe stdout with `a | b`", "---")]
    [InlineData("Throughput | latency", "---")]
    [InlineData("value is a|b", "----------")]
    public void A_horizontal_rule_under_prose_does_not_make_a_table(string prose, string rule)
    {
        // All five reproduced as tables before the separator was required to be
        // a PIPE row. The parser then went on eating following prose lines as
        // body rows, and the rule itself vanished.
        Assert.Null(MarkdownTable.TryParse(L(prose, rule, "more prose"), 0));
    }

    [Fact]
    public void A_pipe_inside_inline_code_does_not_make_a_row()
    {
        // LooksLikeRow's docstring claimed this and did not implement it.
        Assert.False(MarkdownTable.LooksLikeRow("Run `ls | wc` and see."));
        Assert.True(MarkdownTable.LooksLikeRow("| a | b |"));
    }
}
