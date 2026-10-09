using System;
using System.Collections.Generic;
using System.Linq;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Pipe-table parsing for <c>MarkdownBlock</c> (#1583).
///
/// WHY THIS EXISTS: the auditability disclosure (#1544) carries ONE table of 8
/// rows — measured, about 6% of its 171 lines, not "mostly tables" as an earlier
/// version of this comment claimed. The renderer had no table support, so those
/// 8 rows would have been word-wrapped as paragraphs, destroying the column
/// alignment that makes a coverage table readable at all.
///
/// The honest trade, stated because it is what licenses touching a parser that
/// runs over EVERY assistant reply: one 8-row table rendered correctly, against
/// the risk of this parser misreading ordinary chat.
///
/// DELIBERATELY CONSERVATIVE. A table is recognised ONLY on a header row
/// followed immediately by a separator row (<c>|---|---|</c>). Anything else
/// containing a pipe stays prose, exactly as before, because this parser also
/// runs over every assistant reply and a greedy one would start eating ordinary
/// sentences that happen to contain a bar.
///
/// No WinUI dependency, so the headless xUnit project compiles it via a Compile
/// link and covers the recognition boundary directly.
/// </summary>
public static class MarkdownTable
{
    /// <summary>One parsed table: a header row and its body rows.</summary>
    public sealed record Parsed(IReadOnlyList<string> Header, IReadOnlyList<IReadOnlyList<string>> Rows, int LinesConsumed);

    /// <summary>
    /// True when <paramref name="line"/> is a table separator — a pipe row whose
    /// every cell is dashes, optionally with alignment colons.
    /// </summary>
    public static bool IsSeparator(string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return false;
        // A separator must be a PIPE row. Without this, a bare markdown
        // horizontal rule or a setext underline turned the pipe-bearing prose
        // line above it into a table header -- review reproduced five ordinary
        // sentences being eaten that way, including "Pick Option A | Option B"
        // followed by "---", and the parser then went on to swallow following
        // prose lines as body rows.
        if (!line.Contains('|')) return false;
        var cells = SplitRow(line);
        if (cells.Count < 2) return false;
        foreach (var cell in cells)
        {
            var t = cell.Trim();
            if (t.Length == 0) return false;
            if (t.Any(c => c != '-' && c != ':')) return false;
            if (!t.Contains('-')) return false;
        }
        return true;
    }

    /// <summary>
    /// True when <paramref name="line"/> could be a table row: it has at least
    /// one pipe that is not inside inline code.
    /// </summary>
    public static bool LooksLikeRow(string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return false;

        // AT LEAST ONE PIPE OUTSIDE INLINE CODE. Exactly what the summary says,
        // which the first version did not implement -- it tested
        // `line.Contains('|')`, so ``Run `ls | wc` `` counted as a row. The
        // claim went untested because the code-awareness test exercised
        // SplitRow rather than this.
        //
        // NOT "splits into two or more cells". That was the second attempt and
        // it dropped ``| only-one |`` -- a legitimate single-column row, and a
        // row this parser's own contract promises to KEEP rather than reject.
        // Its regression test caught it.
        var t = line.Trim();
        bool inCode = false;
        for (int i = 0; i < t.Length; i++)
        {
            if (t[i] == '\\' && i + 1 < t.Length && t[i + 1] == '|') { i++; continue; }
            if (t[i] == '`') { inCode = !inCode; continue; }
            if (t[i] == '|' && !inCode) return true;
        }
        return false;
    }

    /// <summary>
    /// Parse a table starting at <paramref name="start"/>, or return null.
    ///
    /// Requires a header row AND a separator row immediately after it. Body rows
    /// continue until the first line that is not a pipe row; a short or long row
    /// is padded or kept rather than rejected, because a malformed row in a
    /// disclosure must still be SHOWN — dropping it would be the silent
    /// less-than-the-truth this whole screen exists to avoid.
    /// </summary>
    public static Parsed? TryParse(IReadOnlyList<string> lines, int start)
    {
        if (lines is null || start < 0 || start + 1 >= lines.Count) return null;
        if (!LooksLikeRow(lines[start])) return null;
        if (!IsSeparator(lines[start + 1])) return null;

        var header = SplitRow(lines[start]);
        if (header.Count == 0) return null;

        var rows = new List<IReadOnlyList<string>>();
        int i = start + 2;
        while (i < lines.Count && LooksLikeRow(lines[i]) && !IsSeparator(lines[i]))
        {
            var cells = SplitRow(lines[i]);
            while (cells.Count < header.Count) cells.Add(string.Empty);
            rows.Add(cells);
            i++;
        }

        return new Parsed(header, rows, i - start);
    }

    /// <summary>
    /// Split one pipe row into cells, honouring escaped pipes (<c>\|</c>) and
    /// pipes inside inline code spans, both of which appear in this project's
    /// own governance tables.
    /// </summary>
    public static List<string> SplitRow(string line)
    {
        var cells = new List<string>();
        if (line is null) return cells;

        var trimmed = line.Trim();
        if (trimmed.StartsWith("|", StringComparison.Ordinal)) trimmed = trimmed[1..];
        if (trimmed.EndsWith("|", StringComparison.Ordinal) && !trimmed.EndsWith("\\|", StringComparison.Ordinal))
            trimmed = trimmed[..^1];

        var current = new System.Text.StringBuilder();
        bool inCode = false;
        for (int i = 0; i < trimmed.Length; i++)
        {
            char c = trimmed[i];
            if (c == '\\' && i + 1 < trimmed.Length && trimmed[i + 1] == '|')
            {
                current.Append('|');
                i++;
                continue;
            }
            if (c == '`') inCode = !inCode;
            if (c == '|' && !inCode)
            {
                cells.Add(current.ToString().Trim());
                current.Clear();
                continue;
            }
            current.Append(c);
        }
        cells.Add(current.ToString().Trim());
        return cells;
    }
}
