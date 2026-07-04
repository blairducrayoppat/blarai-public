using System.Text.Json;
using BlarAI.Desktop.Dtos;
using BlarAI.Desktop.Services;

namespace BlarAI.Desktop.Ipc;

/// <summary>
/// Typed convenience wrapper over <see cref="PipeClient"/>: maps backend RPC
/// methods to model objects so the UI never touches raw JSON.
/// </summary>
public sealed class BackendClient : IAsyncDisposable
{
    private readonly PipeClient _pipe;

    public BackendClient(string pipeName = "BlarAI") => _pipe = new PipeClient(pipeName);

    public bool IsConnected => _pipe.IsConnected;

    public Task ConnectAsync(int timeoutMs = 5000, CancellationToken ct = default)
        => _pipe.ConnectAsync(timeoutMs, ct);

    // ── Sessions ────────────────────────────────────────────────────────

    public async Task<IReadOnlyList<ChatSession>> ListSessionsAsync(CancellationToken ct = default)
    {
        var result = await _pipe.CallAsync("list_sessions", ct: ct).ConfigureAwait(false);
        var list = new List<ChatSession>();
        foreach (var s in result.EnumerateArray())
        {
            list.Add(new ChatSession(
                Str(s, "id"), Str(s, "title"), Str(s, "created_at"),
                Str(s, "updated_at"),
                s.TryGetProperty("is_active", out var a) && a.ValueKind == JsonValueKind.True,
                s.TryGetProperty("turn_count", out var tc) ? tc.GetInt32() : 0));
        }
        return list;
    }

    public async Task<IReadOnlyList<ChatTurn>> GetTurnsAsync(string sessionId, CancellationToken ct = default)
    {
        var result = await _pipe.CallAsync("get_turns", new { session_id = sessionId }, ct).ConfigureAwait(false);
        var list = new List<ChatTurn>();
        foreach (var t in result.EnumerateArray())
        {
            list.Add(new ChatTurn(
                Str(t, "id"), Str(t, "session_id"), Str(t, "role"), Str(t, "content"),
                Str(t, "pgov_status"), StrList(t, "pgov_reasons"), Str(t, "timestamp")));
        }
        return list;
    }

    public async Task<string> CreateSessionAsync(string title = "", CancellationToken ct = default)
    {
        var result = await _pipe.CallAsync("create_session", new { title }, ct).ConfigureAwait(false);
        return Str(result, "session_id");
    }

    public Task SetActiveSessionAsync(string sessionId, CancellationToken ct = default)
        => _pipe.CallAsync("set_active_session", new { session_id = sessionId }, ct);

    public Task DeleteSessionAsync(string sessionId, CancellationToken ct = default)
        => _pipe.CallAsync("delete_session", new { session_id = sessionId }, ct);

    public Task RenameSessionAsync(string sessionId, string title, CancellationToken ct = default)
        => _pipe.CallAsync("rename_session", new { session_id = sessionId, title }, ct);

    // ── Documents / attachments ─────────────────────────────────────────

    public async Task<AttachmentInfo> StoreAttachmentAsync(string srcPath, string sessionId, CancellationToken ct = default)
    {
        var r = await _pipe.CallAsync("store_attachment", new { src_path = srcPath, session_id = sessionId }, ct).ConfigureAwait(false);
        return new AttachmentInfo(Str(r, "filename"), Str(r, "media_type"), Str(r, "message"));
    }

    public async Task<AttachmentInfo> LoadDocumentAsync(string sessionId, string filename, CancellationToken ct = default)
    {
        var r = await _pipe.CallAsync("load_document", new { session_id = sessionId, filename }, ct).ConfigureAwait(false);
        return new AttachmentInfo(Str(r, "filename"), Str(r, "media_type"), Str(r, "message"));
    }

    public async Task<IReadOnlyList<AttachmentInfo>> ListUserdataFilesAsync(CancellationToken ct = default)
    {
        var r = await _pipe.CallAsync("list_userdata_files", ct: ct).ConfigureAwait(false);
        var list = new List<AttachmentInfo>();
        foreach (var f in r.EnumerateArray())
        {
            list.Add(new AttachmentInfo(Str(f, "filename"), Str(f, "media_type"), ""));
        }
        return list;
    }

    public Task UnloadDocumentsAsync(string sessionId, CancellationToken ct = default)
        => _pipe.CallAsync("unload_documents", new { session_id = sessionId }, ct);

    public Task TrustDocumentsAsync(string sessionId, CancellationToken ct = default)
        => _pipe.CallAsync("trust_documents_for_tools", new { session_id = sessionId }, ct);

    // ── Chat (streaming) ────────────────────────────────────────────────

    /// <summary>
    /// Stream a conversational turn. <paramref name="onToken"/> fires for each
    /// text fragment as it arrives; the returned verdict is the PGOV result.
    ///
    /// When <paramref name="speak"/> is set, the backend also synthesizes the
    /// reply sentence-by-sentence as it streams (ADR-017): <paramref name="onAudio"/>
    /// fires for each PCM chunk, and <paramref name="onAudioCancel"/> fires if PGOV
    /// denies the reply (stop playback — already-spoken words cannot be retracted).
    /// </summary>
    public async Task<PgovVerdict> PromptAsync(
        string sessionId, string text, Action<string> onToken,
        bool speak = false, string? voice = null,
        Func<AudioChunk, Task>? onAudio = null, Action? onAudioCancel = null,
        Action<IngestPreviewMeta>? onIngestPreview = null,
        Action<UiActionMeta>? onUiActions = null,
        CancellationToken ct = default)
    {
        PgovVerdict verdict = new(true, "", Array.Empty<string>());
        await foreach (var frame in _pipe.PromptAsync(sessionId, text, speak, voice, ct).ConfigureAwait(false))
        {
            switch (frame.Kind)
            {
                case "token":
                    onToken(frame.Value.GetProperty("token").GetString() ?? "");
                    // Editable-preview attachment (#663): a NEW ingest preview
                    // carries the editable article body so the UI can offer
                    // edit-before-approve.
                    if (onIngestPreview is not null
                        && frame.Value.TryGetProperty("ingest_preview", out var ip)
                        && ip.ValueKind == JsonValueKind.True)
                    {
                        onIngestPreview(new IngestPreviewMeta(
                            Str(frame.Value, "ingest_doc_uuid"),
                            Str(frame.Value, "ingest_source_type"),
                            Str(frame.Value, "ingest_editable_body")));
                    }
                    // Follow-up action buttons (#712): a successful image reply or a
                    // dispatch plan-preview carries a ui_actions discriminator.
                    if (onUiActions is not null
                        && frame.Value.TryGetProperty("ui_actions", out var ua)
                        && ua.ValueKind == JsonValueKind.String)
                    {
                        onUiActions(new UiActionMeta(
                            ua.GetString() ?? "",
                            Str(frame.Value, "ui_action_id")));
                    }
                    break;
                case "audio":
                    if (onAudio is not null)
                    {
                        string b64 = frame.Value.TryGetProperty("audio_b64", out var a) ? a.GetString() ?? "" : "";
                        if (b64.Length > 0)
                        {
                            int sr = frame.Value.TryGetProperty("sample_rate", out var s) ? s.GetInt32() : 24000;
                            int idx = frame.Value.TryGetProperty("index", out var i) ? i.GetInt32() : 0;
                            await onAudio(new AudioChunk(Convert.FromBase64String(b64), sr, idx)).ConfigureAwait(false);
                        }
                    }
                    break;
                case "audio_cancel":
                    onAudioCancel?.Invoke();
                    break;
                case "pgov":
                    verdict = new PgovVerdict(
                        frame.Value.TryGetProperty("approved", out var ap) && ap.ValueKind == JsonValueKind.True,
                        frame.Value.TryGetProperty("sanitized_text", out var st) ? st.GetString() ?? "" : "",
                        StrList(frame.Value, "reason_codes"));
                    break;
                case "end":
                    break;
            }
        }
        return verdict;
    }

    /// <summary>
    /// Approve or reject the pending ingest from the preview buttons (#663
    /// Workstream A). For approve, <paramref name="editedBody"/> (the possibly
    /// edited preview text) rides this structured RPC param — NEVER prompt text —
    /// so the curated article body never enters sessions.db. Streams the
    /// informational reply token-by-frame (no PGOV frame). Returns
    /// <c>decided</c>: true when the pending slot is now cleared (the caller
    /// retires the preview buttons), false when it survives a transient failure
    /// (the buttons stay so the operator can retry).
    /// </summary>
    public async Task<bool> IngestDecideAsync(
        string sessionId, string decision, string editedBody, Action<string> onToken,
        CancellationToken ct = default)
    {
        var payload = new { session_id = sessionId, decision, edited_body = editedBody };
        bool decided = false;
        await foreach (var frame in _pipe.CallStreamAsync("ingest_decide", payload, ct).ConfigureAwait(false))
        {
            if (frame.Kind == "token")
                onToken(frame.Value.GetProperty("token").GetString() ?? "");
            else if (frame.Kind == "end")
                decided = frame.Value.TryGetProperty("ingest_decided", out var d)
                          && d.ValueKind == JsonValueKind.True;
        }
        return decided;
    }

    // ── Voice (ADR-017) ─────────────────────────────────────────────────

    /// <summary>Query which voice halves are available, to gate mic/play UI.</summary>
    public async Task<VoiceStatus> GetVoiceStatusAsync(CancellationToken ct = default)
    {
        try
        {
            var r = await _pipe.CallAsync("voice_status", ct: ct).ConfigureAwait(false);
            return ParseVoiceStatus(r);
        }
        catch (PipeBackendException)
        {
            return VoiceStatus.Off;  // older backend without the method -> voice off
        }
    }

    /// <summary>
    /// Turn the microphone (STT) on/off on demand (#660). ON loads Whisper so the
    /// mic affordance lights up; OFF releases it to reclaim RAM. Returns the
    /// refreshed status (the backend loads/unloads then reports), so the caller
    /// re-gates in one round-trip. A first ON can take a few seconds (model load).
    /// </summary>
    public async Task<VoiceStatus> SetSttAsync(bool enabled, CancellationToken ct = default)
    {
        try
        {
            var r = await _pipe.CallAsync("voice_set_stt", new { enabled }, ct).ConfigureAwait(false);
            return ParseVoiceStatus(r);
        }
        catch (PipeBackendException)
        {
            return VoiceStatus.Off;  // older backend without the method -> voice off
        }
    }

    /// <summary>
    /// Turn voice replies (TTS) on/off on demand (#660). ON loads Kokoro + its
    /// voice bank; OFF releases them to reclaim RAM. Returns the refreshed status.
    /// </summary>
    public async Task<VoiceStatus> SetTtsAsync(bool enabled, CancellationToken ct = default)
    {
        try
        {
            var r = await _pipe.CallAsync("voice_set_tts", new { enabled }, ct).ConfigureAwait(false);
            return ParseVoiceStatus(r);
        }
        catch (PipeBackendException)
        {
            return VoiceStatus.Off;  // older backend without the method -> voice off
        }
    }

    private static VoiceStatus ParseVoiceStatus(JsonElement r)
        => new VoiceStatus(
            r.TryGetProperty("stt", out var s) && s.ValueKind == JsonValueKind.True,
            r.TryGetProperty("tts", out var t) && t.ValueKind == JsonValueKind.True,
            StrList(r, "voices"),
            Str(r, "default_voice"));

    /// <summary>
    /// Transcribe a 16-bit PCM utterance; returns the recognized text. The
    /// backend resamples to 16 kHz and downmixes to mono, so the native capture
    /// rate / channel count are passed through rather than forced client-side.
    /// </summary>
    public async Task<string> TranscribeAsync(
        byte[] pcm16, int sampleRate, int channels = 1, CancellationToken ct = default)
    {
        var payload = new
        {
            audio_b64 = Convert.ToBase64String(pcm16),
            sample_rate = sampleRate,
            format = "pcm_s16le",
            channels,
        };
        var r = await _pipe.CallAsync("transcribe", payload, ct).ConfigureAwait(false);
        return Str(r, "text");
    }

    /// <summary>
    /// Stream synthesized speech for <paramref name="text"/>; yields one PCM
    /// chunk per sentence as it generates, so playback can start immediately.
    /// </summary>
    public async IAsyncEnumerable<AudioChunk> SynthesizeAsync(
        string text, string voice,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        var payload = new { text, voice };
        await foreach (var frame in _pipe.CallStreamAsync("synthesize", payload, ct).ConfigureAwait(false))
        {
            if (frame.Kind != "audio") continue;
            string b64 = frame.Value.TryGetProperty("audio_b64", out var a) ? a.GetString() ?? "" : "";
            if (b64.Length == 0) continue;
            int sr = frame.Value.TryGetProperty("sample_rate", out var s) ? s.GetInt32() : 24000;
            int idx = frame.Value.TryGetProperty("index", out var i) ? i.GetInt32() : 0;
            yield return new AudioChunk(Convert.FromBase64String(b64), sr, idx);
        }
    }

    // ── Images (UC-003 Workstream B) ────────────────────────────────────

    /// <summary>
    /// Hard cap on a reassembled image (16 MiB). Mirrors the Python source of
    /// truth <c>shared.ipc.resolve_channel.RESOLVE_BODY_MAX_BYTES</c> — the resolve
    /// corridor delivers generated images (no 2 MiB fetch cap; a 1024² SDXL PNG
    /// exceeds it), so the cap is sized for generated images, decoupled from
    /// image_staging.MAX_IMAGE_BYTES. A stream exceeding it is refused (return
    /// null) rather than reassembled unbounded (fail-closed). (#666 go-live.)
    /// </summary>
    private const int MaxResolvedImageBytes = 16 * 1024 * 1024;

    /// <summary>
    /// Fetch the locally-decrypted PNG bytes for a knowledge-bank image by its
    /// opaque <c>image_id</c> (a <c>uuid4().hex</c> handle into the host-side
    /// <c>knowledge_images</c> rows). Returns <c>null</c> when:
    /// <list type="bullet">
    ///   <item><paramref name="imageId"/> fails the <see cref="ImageResolver.IsValidImageId"/>
    ///   shape check (client-side defense-in-depth before the round-trip);</item>
    ///   <item>the backend returns <c>found=false</c> (id not in the store);</item>
    ///   <item>the backend is older / the method is dormant (PipeBackendException).</item>
    /// </list>
    /// The Python dispatcher RPC <c>resolve_image</c> emits streaming frames:
    /// <c>kind="chunk" { data_b64: string, mime: string }</c> (one or more, with
    /// <c>mime</c> on the first chunk), then a terminal <c>kind="end" { found: bool }</c>.
    /// The consumed field names (<c>data_b64</c>, <c>found</c>) match exactly;
    /// <c>mime</c> is informational on this leg and is NOT consumed here (the
    /// decode below sniffs the format straight from the PNG header bytes).
    ///
    /// DORMANT build: the dispatcher DOES register <c>resolve_image</c>
    /// (<c>dispatcher._m_resolve_image</c>, reached via <c>getattr(self, $"_m_{method}")</c>
    /// — no allowlist), so this is dispatchable. It returns null because no
    /// decrypted image bytes exist upstream — the image fetch/store path is welded
    /// — so the dispatcher emits <c>end { found: false }</c> and ResolveImageAsync
    /// returns null via the found-check below (NOT via the PipeBackendException
    /// catch, which is only the older-backend / no-method fallback). Producing real
    /// bytes is the UC-003/UC-010 image go-live ceremony step.
    /// </summary>
    public async Task<byte[]?> ResolveImageAsync(string imageId, CancellationToken ct = default)
    {
        // Client-side defense-in-depth: refuse malformed ids before the round-trip.
        if (!ImageResolver.IsValidImageId(imageId)) return null;

        try
        {
            var buffer = new System.IO.MemoryStream();
            bool found = false;
            await foreach (var frame in _pipe.CallStreamAsync("resolve_image", new { image_id = imageId }, ct).ConfigureAwait(false))
            {
                if (frame.Kind == "chunk")
                {
                    if (frame.Value.TryGetProperty("data_b64", out var b64Prop))
                    {
                        string b64 = b64Prop.GetString() ?? "";
                        if (b64.Length > 0)
                        {
                            byte[] chunk;
                            try
                            {
                                chunk = Convert.FromBase64String(b64);
                            }
                            catch (FormatException)
                            {
                                // Malformed base64 on the wire -> fail-closed (the
                                // contract promises null-on-failure, never a throw).
                                return null;
                            }
                            // Never reassemble past MaxResolvedImageBytes (16 MiB):
                            // a stream that would exceed it is malformed/hostile ->
                            // fail-closed.
                            if (buffer.Length + chunk.Length > MaxResolvedImageBytes)
                                return null;
                            await buffer.WriteAsync(chunk, ct).ConfigureAwait(false);
                        }
                    }
                }
                else if (frame.Kind == "end")
                {
                    found = frame.Value.TryGetProperty("found", out var f)
                            && f.ValueKind == JsonValueKind.True;
                    break;
                }
            }
            if (!found || buffer.Length == 0) return null;
            return buffer.ToArray();
        }
        catch (PipeBackendException)
        {
            // Older backend that predates resolve_image (no such method registered).
            // The CURRENT dormant build DOES register resolve_image — that path returns
            // null via the found-check above (no decrypted bytes upstream), NOT here.
            return null;
        }
    }

    // ── Generated-image gallery management (UC-010 Phase 2, #668) ─────────
    //
    // The gallery pane lists and manages the born-encrypted generated images.
    // These two RPCs are METADATA-ONLY on the wire (no pixels): list returns
    // per-image metadata, manage returns an outcome. Decrypted pixels are
    // fetched ONLY via ResolveImageAsync above (for a thumbnail or the operator's
    // explicit Save). Both fail closed to an inert default on PipeBackendException
    // (older backend without the method) so the gallery degrades to empty rather
    // than throwing into the UI.

    /// <summary>
    /// List generated-image METADATA for the gallery (optionally filtered to one
    /// chat by <paramref name="sessionId"/>; null/empty → all images). Parses the
    /// non-streaming <c>list_generated_images</c> result <c>{images:[...], total,
    /// truncated}</c> into <see cref="GeneratedImageMeta"/> rows. The snake_case
    /// field names (<c>image_id, session_id, mime, byte_size, saved, created_at</c>)
    /// match the Python IMAGE_LIST contract exactly. No image bytes cross this leg.
    /// Returns an empty list on <see cref="PipeBackendException"/> (older backend).
    /// </summary>
    public async Task<IReadOnlyList<GeneratedImageMeta>> ListGeneratedImagesAsync(
        string? sessionId = null, CancellationToken ct = default)
    {
        try
        {
            object payload = string.IsNullOrEmpty(sessionId)
                ? new { }
                : new { session_id = sessionId };
            var result = await _pipe.CallAsync("list_generated_images", payload, ct).ConfigureAwait(false);
            var list = new List<GeneratedImageMeta>();
            if (result.TryGetProperty("images", out var images)
                && images.ValueKind == JsonValueKind.Array)
            {
                foreach (var img in images.EnumerateArray())
                {
                    if (img.ValueKind != JsonValueKind.Object) continue;
                    list.Add(new GeneratedImageMeta(
                        Str(img, "image_id"), Str(img, "session_id"), Str(img, "mime"),
                        Long(img, "byte_size"), Bool(img, "saved"), Str(img, "created_at")));
                }
            }
            return list;
        }
        catch (PipeBackendException)
        {
            return Array.Empty<GeneratedImageMeta>();  // older backend → empty gallery
        }
    }

    /// <summary>
    /// Mark a generated image as saved-to-disk (flips the gallery's saved badge).
    /// Client-side <see cref="ImageResolver.IsValidImageId"/> gate first (a forged
    /// id never makes the round-trip), then the non-streaming
    /// <c>manage_generated_image</c> RPC with action <c>mark_saved</c>. Returns the
    /// result's <c>ok</c> flag; false on a bad id or <see cref="PipeBackendException"/>.
    /// </summary>
    public Task<bool> MarkImageSavedAsync(string imageId, CancellationToken ct = default)
        => ManageAsync("mark_saved", imageId, ct);

    /// <summary>
    /// Delete a generated image from the born-encrypted store (a <c>secure_delete</c>
    /// wipe; the operator's separately-saved copies on disk are untouched).
    /// Client-side id gate first, then <c>manage_generated_image</c> with action
    /// <c>delete</c>. Returns true when the store reports the row was found and
    /// removed (<c>ok &amp;&amp; found</c>); false on a bad id, a not-found id, or
    /// <see cref="PipeBackendException"/>.
    /// </summary>
    public Task<bool> DeleteImageAsync(string imageId, CancellationToken ct = default)
        => ManageAsync("delete", imageId, ct);

    /// <summary>
    /// Shared driver for the two manage actions. Returns true on a successful
    /// outcome: for <c>delete</c> the row must have been <c>found</c> (deleting a
    /// vanished id is not a UI success); for <c>mark_saved</c> the <c>ok</c> flag
    /// suffices. A malformed id is refused client-side (no round-trip), matching
    /// ResolveImageAsync's defense-in-depth.
    /// </summary>
    private async Task<bool> ManageAsync(string action, string imageId, CancellationToken ct)
    {
        if (!ImageResolver.IsValidImageId(imageId)) return false;
        try
        {
            var r = await _pipe.CallAsync(
                "manage_generated_image", new { action, image_id = imageId }, ct).ConfigureAwait(false);
            bool ok = Bool(r, "ok");
            // delete requires the row to have actually been present; mark_saved does not.
            return action == "delete" ? ok && Bool(r, "found") : ok;
        }
        catch (PipeBackendException)
        {
            return false;  // older backend without the method → fail closed
        }
    }

    // ── JSON helpers ─────────────────────────────────────────────────────

    private static string Str(JsonElement e, string name)
        => e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

    private static long Long(JsonElement e, string name)
        => e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number
           && v.TryGetInt64(out var n) ? n : 0L;

    private static bool Bool(JsonElement e, string name)
        => e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.True;

    private static IReadOnlyList<string> StrList(JsonElement e, string name)
    {
        if (!e.TryGetProperty(name, out var v) || v.ValueKind != JsonValueKind.Array)
            return Array.Empty<string>();
        var list = new List<string>();
        foreach (var item in v.EnumerateArray())
            if (item.ValueKind == JsonValueKind.String) list.Add(item.GetString() ?? "");
        return list;
    }

    public ValueTask DisposeAsync() => _pipe.DisposeAsync();
}
