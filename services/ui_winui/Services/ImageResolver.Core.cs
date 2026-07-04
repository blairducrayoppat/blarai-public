using System.Net;
using System.Text.RegularExpressions;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Dependency-free id-gate partial of <see cref="ImageResolver"/>. This file
/// contains only members that have no WinUI / Windows App SDK dependency so they
/// can be compiled into the headless xUnit test project via a Compile link, with
/// no ProjectReference to BlarAI.Desktop (which drags in the full Windows App SDK
/// workload). The complete public surface is the union of this partial and
/// ImageResolver.cs.
/// </summary>
public static partial class ImageResolver
{
    /// <summary>The single host-internal image scheme. Anything else is refused.</summary>
    public const string Scheme = "blarai-img://";

    /// <summary>
    /// True iff <paramref name="url"/> is the host-internal image scheme. The
    /// renderer refuses every other scheme (http(s), data:, javascript:, file:…)
    /// in the image position — those never become an ImageSource, only the alt
    /// placeholder. Case-insensitive on the scheme, defensively.
    /// </summary>
    public static bool IsImageRef(string? url) =>
        url is not null && url.StartsWith(Scheme, StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// The authoritative <c>image_id</c> shape: a <c>uuid4().hex</c> — exactly
    /// 32 lowercase hex chars, no hyphens, nothing trailing. The host mints ids
    /// as <c>uuid4().hex</c> (gateway <c>ingest_coordinator</c>) and the cleaner
    /// rewrites refs to a bare <c>blarai-img://&lt;id&gt;</c>, so this is the
    /// COMPLETE legitimate surface — anything else is a forged / malformed ref.
    /// </summary>
    /// <remarks>
    /// Anchored with <c>\A…\z</c>, NOT <c>^…$</c>: in .NET the <c>$</c> anchor
    /// matches before a trailing <c>\n</c>, so <c>^[0-9a-f]{32}$</c> would accept
    /// a 33-char <c>&lt;32hex&gt;\n</c> forged id. <c>\z</c> is the absolute
    /// end-of-string anchor and permits no trailing newline (adversarial review,
    /// 2026-06-15).
    /// </remarks>
    private static readonly Regex ImageIdShape =
        new(@"\A[0-9a-f]{32}\z", RegexOptions.Compiled);

    /// <summary>
    /// True iff <paramref name="id"/> is a well-formed <c>uuid4().hex</c> image
    /// id (exactly 32 lowercase hex). Rejects path traversal (<c>../..</c>),
    /// query / fragment smuggling (<c>id?x=1</c>, <c>id#frag</c>), nested-scheme
    /// payloads, uppercase, and wrong-length ids — the forgery surface a
    /// render-time gate must deny.
    /// </summary>
    /// <remarks>
    /// HEADLESS hardening (UC-003 Workstream B #4): this validates the id SHAPE.
    /// Validating the id against the document's authoritative <c>knowledge_images</c>
    /// set (true forgery-vs-stored rejection) requires a per-document valid-id
    /// manifest plumbed to the renderer, which does not exist on the render path
    /// today — that is a go-live-ceremony successor, landing with the decrypt wiring.
    /// </remarks>
    public static bool IsValidImageId(string? id) =>
        id is not null && ImageIdShape.IsMatch(id);

    /// <summary>
    /// Extract the opaque <c>image_id</c> from a well-formed
    /// <c>blarai-img://&lt;id&gt;</c> ref, ENFORCING the <c>uuid4().hex</c> shape
    /// (32 lowercase hex — the host contract). Returns <c>null</c> for any
    /// non-image scheme, an empty id, OR an id that is not exactly that shape —
    /// so a forged / malformed local ref never reaches the (dormant) decrypt path
    /// and renders as the inert alt placeholder instead.
    /// </summary>
    public static string? ExtractImageId(string? url)
    {
        if (!IsImageRef(url)) return null;
        string id = url!.Substring(Scheme.Length).Trim();
        return IsValidImageId(id) ? id : null;
    }

    /// <summary>
    /// Defense-in-depth escape of alt text before it is shown next to / instead
    /// of an image. The WinUI <c>Run.Text</c> sink already treats its content as
    /// literal (never markup), but we HTML-encode the alt anyway so that no alt
    /// can smuggle active content or markup if the same string is ever reused in
    /// a markup-bearing context. Pure presentation; deterministic.
    /// </summary>
    public static string EscapeAlt(string? alt) =>
        string.IsNullOrEmpty(alt) ? "" : WebUtility.HtmlEncode(alt);
}
