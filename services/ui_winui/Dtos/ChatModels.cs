namespace BlarAI.Desktop.Dtos;

/// <summary>
/// A conversation session as listed in the sidebar. A plain class (not a
/// record) with get-only properties: the XAML type-info generator emits a
/// setter for record init-only properties, which the compiler then rejects
/// (CS8852). Get-only auto-properties sidestep that for x:Bind display.
/// </summary>
public sealed class ChatSession
{
    public ChatSession(
        string id, string title, string createdAt, string updatedAt,
        bool isActive, int turnCount)
    {
        Id = id;
        Title = title;
        CreatedAt = createdAt;
        UpdatedAt = updatedAt;
        IsActive = isActive;
        TurnCount = turnCount;
    }

    public string Id { get; }
    public string Title { get; }
    public string CreatedAt { get; }
    public string UpdatedAt { get; }
    public bool IsActive { get; }
    public int TurnCount { get; }

    /// <summary>Title with a graceful fallback for an as-yet-unnamed session.</summary>
    public string DisplayTitle => string.IsNullOrWhiteSpace(Title) ? "New chat" : Title;
}

/// <summary>A single persisted turn (user or assistant).</summary>
public sealed record ChatTurn(
    string Id,
    string SessionId,
    string Role,
    string Content,
    string PgovStatus,
    IReadOnlyList<string> PgovReasons,
    string Timestamp)
{
    public bool IsUser => Role == "user";
    public bool IsAssistant => Role == "assistant";
    public bool IsDenied => PgovStatus == "denied";
}

/// <summary>The output-validator verdict for a generated turn (PGOV).</summary>
public sealed record PgovVerdict(
    bool Approved,
    string SanitizedText,
    IReadOnlyList<string> ReasonCodes);

/// <summary>Which voice halves the backend has loaded (ADR-017), for gating UI.</summary>
public sealed record VoiceStatus(
    bool Stt,
    bool Tts,
    IReadOnlyList<string> Voices,
    string DefaultVoice)
{
    public static readonly VoiceStatus Off = new(false, false, Array.Empty<string>(), "");
}

/// <summary>One synthesized audio chunk streamed from the backend (16-bit PCM).</summary>
public sealed record AudioChunk(byte[] Pcm16, int SampleRate, int Index);

/// <summary>
/// Editable-preview metadata attached to an ingest preview's token frame
/// (#663 Workstream A). <see cref="EditableBody"/> is the cleaned ARTICLE BODY
/// — the exact source the operator edits before approving (not the rendered
/// preview blob). The operator may trim noise/ads and approve the curated text.
/// </summary>
public sealed record IngestPreviewMeta(
    string DocUuid,
    string SourceType,
    string EditableBody);

/// <summary>
/// Follow-up UI actions attached to an assistant reply frame (#712). <see
/// cref="Kind"/> is "image" (Edit/Save buttons — <see cref="Id"/> is the 32-hex
/// generated-image id) or "dispatch_plan" (Approve/Reject buttons — Id empty).
/// Mirrors the IngestPreviewMeta one-shot attachment, carried on the token frame.
/// </summary>
public sealed record UiActionMeta(string Kind, string Id);

/// <summary>
/// Metadata for one born-encrypted generated image, as listed for the gallery
/// pane (UC-010 Phase 2, #668). METADATA ONLY — the wire carries no pixels:
/// <see cref="ByteSize"/> is the on-disk ciphertext length (a <c>length(data)</c>
/// SQL aggregate, NOT a decrypt), and the decrypted bytes are fetched separately
/// via <c>BackendClient.ResolveImageAsync</c> only when a tile is shown or saved.
/// </summary>
public sealed record GeneratedImageMeta(
    string ImageId,
    string SessionId,
    string Mime,
    long ByteSize,
    bool Saved,
    string CreatedAt);

/// <summary>A loaded/attached document descriptor (text or store-only media).</summary>
public sealed record AttachmentInfo(
    string Filename,
    string MediaType,   // "text" | "image" | "video"
    string Message)     // user-facing "vision not wired" line for media; "" for text
{
    public bool IsMedia => MediaType is "image" or "video";
}
