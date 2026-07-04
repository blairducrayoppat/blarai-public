using System.Buffers.Binary;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace BlarAI.Desktop.Ipc;

/// <summary>
/// Async client for the BlarAI UI backend named pipe (ADR-014). Speaks the same
/// length-prefixed JSON framing as services/ui_backend/src/protocol.py: a 4-byte
/// big-endian unsigned length prefix followed by UTF-8 JSON.
///
/// This is the ONLY channel the WinUI app uses to reach the Python services.
/// It holds no business logic — every call maps to a backend RPC method.
/// </summary>
public sealed class PipeClient : IAsyncDisposable
{
    private const string DefaultPipeName = "BlarAI";
    private const int MaxFrameBytes = 4 * 1024 * 1024;

    private readonly string _pipeName;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private NamedPipeClientStream? _pipe;
    private int _nextId;

    public PipeClient(string pipeName = DefaultPipeName)
    {
        _pipeName = pipeName;
    }

    public bool IsConnected => _pipe?.IsConnected ?? false;

    public async Task ConnectAsync(int timeoutMs = 5000, CancellationToken ct = default)
    {
        _pipe = new NamedPipeClientStream(
            ".", _pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await _pipe.ConnectAsync(timeoutMs, ct).ConfigureAwait(false);
        _pipe.ReadMode = PipeTransmissionMode.Byte;
    }

    /// <summary>Call a non-streaming method; returns the "result" element.</summary>
    public async Task<JsonElement> CallAsync(
        string method, object? parameters = null, CancellationToken ct = default)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            int id = Interlocked.Increment(ref _nextId);
            await WriteFrameAsync(BuildRequest(id, method, parameters), ct).ConfigureAwait(false);
            JsonElement frame = await ReadFrameAsync(ct).ConfigureAwait(false);
            return UnwrapResult(frame);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>
    /// Call the streaming <c>prompt</c> method, yielding each stream frame
    /// (kinds: "token", "pgov", "end") until the terminal "end" frame.
    /// </summary>
    public async IAsyncEnumerable<StreamFrame> PromptAsync(
        string sessionId, string prompt, bool speak = false, string? voice = null,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            int id = Interlocked.Increment(ref _nextId);
            var payload = new { session_id = sessionId, prompt, speak, voice };
            await WriteFrameAsync(BuildRequest(id, "prompt", payload), ct).ConfigureAwait(false);

            while (true)
            {
                JsonElement frame = await ReadFrameAsync(ct).ConfigureAwait(false);
                if (frame.TryGetProperty("ok", out var ok) && !ok.GetBoolean())
                {
                    throw BackendError(frame);
                }
                string kind = frame.GetProperty("stream").GetString() ?? "";
                JsonElement value = frame.TryGetProperty("value", out var v) ? v : default;
                yield return new StreamFrame(kind, value);
                if (kind == "end")
                {
                    yield break;
                }
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>
    /// Call a streaming method, yielding each stream frame (kinds: method-defined,
    /// e.g. "audio", terminated by "end"). Mirrors <see cref="PromptAsync"/> but
    /// generic over the method + params, for the voice <c>synthesize</c> path.
    /// </summary>
    public async IAsyncEnumerable<StreamFrame> CallStreamAsync(
        string method, object? parameters,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            int id = Interlocked.Increment(ref _nextId);
            await WriteFrameAsync(BuildRequest(id, method, parameters), ct).ConfigureAwait(false);

            while (true)
            {
                JsonElement frame = await ReadFrameAsync(ct).ConfigureAwait(false);
                if (frame.TryGetProperty("ok", out var ok) && !ok.GetBoolean())
                {
                    throw BackendError(frame);
                }
                string kind = frame.GetProperty("stream").GetString() ?? "";
                JsonElement value = frame.TryGetProperty("value", out var v) ? v : default;
                yield return new StreamFrame(kind, value);
                if (kind == "end")
                {
                    yield break;
                }
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    // ── Framing ────────────────────────────────────────────────────────

    private static byte[] BuildRequest(int id, string method, object? parameters)
    {
        var envelope = new Dictionary<string, object?>
        {
            ["id"] = id,
            ["method"] = method,
            ["params"] = parameters ?? new { },
        };
        return JsonSerializer.SerializeToUtf8Bytes(envelope);
    }

    private async Task WriteFrameAsync(byte[] body, CancellationToken ct)
    {
        if (_pipe is null) throw new InvalidOperationException("Not connected.");
        if (body.Length > MaxFrameBytes) throw new InvalidOperationException("Frame too large.");
        var header = new byte[4];
        BinaryPrimitives.WriteUInt32BigEndian(header, (uint)body.Length);
        await _pipe.WriteAsync(header, ct).ConfigureAwait(false);
        await _pipe.WriteAsync(body, ct).ConfigureAwait(false);
        await _pipe.FlushAsync(ct).ConfigureAwait(false);
    }

    private async Task<JsonElement> ReadFrameAsync(CancellationToken ct)
    {
        if (_pipe is null) throw new InvalidOperationException("Not connected.");
        byte[] header = await ReadExactAsync(4, ct).ConfigureAwait(false);
        uint len = BinaryPrimitives.ReadUInt32BigEndian(header);
        if (len == 0 || len > MaxFrameBytes) throw new InvalidOperationException($"Bad frame length {len}.");
        byte[] body = await ReadExactAsync((int)len, ct).ConfigureAwait(false);
        using var doc = JsonDocument.Parse(body);
        return doc.RootElement.Clone();
    }

    private async Task<byte[]> ReadExactAsync(int n, CancellationToken ct)
    {
        if (_pipe is null) throw new InvalidOperationException("Not connected.");
        var buf = new byte[n];
        int off = 0;
        while (off < n)
        {
            int read = await _pipe.ReadAsync(buf.AsMemory(off, n - off), ct).ConfigureAwait(false);
            if (read == 0) throw new EndOfStreamException("Pipe closed mid-frame.");
            off += read;
        }
        return buf;
    }

    private static JsonElement UnwrapResult(JsonElement frame)
    {
        if (frame.TryGetProperty("ok", out var ok) && ok.GetBoolean())
        {
            return frame.TryGetProperty("result", out var result) ? result : default;
        }
        throw BackendError(frame);
    }

    private static PipeBackendException BackendError(JsonElement frame)
    {
        string code = "error", message = "backend error";
        if (frame.TryGetProperty("error", out var err))
        {
            if (err.TryGetProperty("code", out var c)) code = c.GetString() ?? code;
            if (err.TryGetProperty("message", out var m)) message = m.GetString() ?? message;
        }
        return new PipeBackendException(code, message);
    }

    public async ValueTask DisposeAsync()
    {
        if (_pipe is not null)
        {
            await _pipe.DisposeAsync().ConfigureAwait(false);
            _pipe = null;
        }
        _gate.Dispose();
    }
}

/// <summary>A single streaming frame from the backend's <c>prompt</c> method.</summary>
public readonly record struct StreamFrame(string Kind, JsonElement Value);

/// <summary>Raised when the backend returns an error frame.</summary>
public sealed class PipeBackendException(string code, string message)
    : Exception($"{code}: {message}")
{
    public string Code { get; } = code;
}
