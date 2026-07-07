using System.IO;
using Windows.Media.Audio;
using Windows.Media.Capture;
using Windows.Media.MediaProperties;
using Windows.Media.Render;
using Windows.Storage;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Push-to-talk microphone capture (ADR-017). The microphone is routed through
/// an <see cref="AudioGraph"/> into an <see cref="AudioFileOutputNode"/> that
/// encodes straight to a 16 kHz mono 16-bit WAV file — the graph does the format
/// conversion in software, so the mic's native rate is irrelevant and there is
/// no per-quantum frame handling or unsafe buffer reading to go wrong.
///
/// On stop we finalize the file and parse out the raw PCM + format, which the
/// backend transcribes. Capture is in-process (not the cross-integrity-level
/// path UIPI blocks for drag-drop), so it works in the elevated window.
/// </summary>
public sealed class VoiceCapture : IAsyncDisposable
{
    private const string CaptureFileName = "_voice_capture.wav";

    private AudioGraph? _graph;
    private AudioDeviceInputNode? _input;
    private AudioFileOutputNode? _fileOutput;
    private StorageFile? _file;

    /// <summary>Name of the capture device actually opened (diagnostics).</summary>
    public string DeviceName { get; private set; } = "";

    /// <summary>Human-readable reason the last <see cref="StartAsync"/> failed.</summary>
    public string LastError { get; private set; } = "";

    /// <summary>One captured utterance: 16-bit PCM plus its format + peak level.</summary>
    public sealed record Result(byte[] Pcm, int SampleRate, int Channels, float Peak);

    public async Task<bool> StartAsync()
    {
        LastError = "";
        var settings = new AudioGraphSettings(AudioRenderCategory.Speech);
        var graphResult = await AudioGraph.CreateAsync(settings);
        if (graphResult.Status != AudioGraphCreationStatus.Success)
        {
            LastError = $"AudioGraph create failed: {graphResult.Status}{Hr(graphResult.ExtendedError)}";
            return false;
        }
        _graph = graphResult.Graph;

        var inResult = await _graph.CreateDeviceInputNodeAsync(MediaCategory.Speech);
        if (inResult.Status != AudioDeviceNodeCreationStatus.Success)
        {
            LastError = $"Microphone open failed: {inResult.Status}{Hr(inResult.ExtendedError)}";
            _graph.Dispose();
            _graph = null;
            return false;
        }
        _input = inResult.DeviceInputNode;
        try { DeviceName = _input.Device?.Name ?? "(default)"; } catch { DeviceName = "(default)"; }

        // Encode to 16 kHz mono 16-bit PCM in the file-output node. Forcing this
        // format on the *encoder* (not the mic driver) is safe — the encoder is
        // software and converts from whatever the mic provides.
        string userdata = @"C:\Users\mrbla\BlarAI\userdata";
        Directory.CreateDirectory(userdata);
        var folder = await StorageFolder.GetFolderFromPathAsync(userdata);
        _file = await folder.CreateFileAsync(CaptureFileName, CreationCollisionOption.ReplaceExisting);

        var profile = MediaEncodingProfile.CreateWav(AudioEncodingQuality.High);
        profile.Audio = AudioEncodingProperties.CreatePcm(16000, 1, 16);

        var outResult = await _graph.CreateFileOutputNodeAsync(_file, profile);
        if (outResult.Status != AudioFileNodeCreationStatus.Success)
        {
            LastError = $"WAV encoder failed: {outResult.Status}{Hr(outResult.ExtendedError)}";
            _graph.Dispose();
            _graph = null;
            return false;
        }
        _fileOutput = outResult.FileOutputNode;
        _input.AddOutgoingConnection(_fileOutput);
        _graph.Start();
        return true;
    }

    /// <summary>Stop capturing, finalize the WAV, and return its PCM + format.</summary>
    public async Task<Result> StopAsync()
    {
        if (_graph is not null) { try { _graph.Stop(); } catch { } }
        if (_fileOutput is not null)
        {
            try { await _fileOutput.FinalizeAsync(); }
            catch (Exception ex) { LastError = $"Finalize failed: {ex.Message}"; }
        }
        // Release the graph handles before reading. FinalizeAsync already closes
        // the file-output node, so disposing it again throws ObjectDisposedException
        // — every teardown call is therefore defensive.
        SafeDispose(_fileOutput); _fileOutput = null;
        SafeDispose(_input); _input = null;
        SafeDispose(_graph); _graph = null;
        if (_file is null) return new Result(Array.Empty<byte>(), 16000, 1, 0f);

        byte[] wav = await ReadAllBytesAsync(_file.Path);
        return ParseWav(wav);
    }

    private static async Task<byte[]> ReadAllBytesAsync(string path)
    {
        // FileShare.ReadWrite tolerates any lingering encoder handle; a couple of
        // quick retries cover the brief window after finalize on a slow disk.
        for (int attempt = 0; ; attempt++)
        {
            try
            {
                using var fs = new FileStream(
                    path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                using var ms = new MemoryStream();
                await fs.CopyToAsync(ms);
                return ms.ToArray();
            }
            catch (IOException) when (attempt < 5)
            {
                await Task.Delay(50);
            }
        }
    }

    /// <summary>Extract PCM + sample rate + channels + peak from a PCM WAV.</summary>
    private static Result ParseWav(byte[] wav)
    {
        if (wav.Length < 12) return new Result(Array.Empty<byte>(), 16000, 1, 0f);

        // Walk chunks: read fmt fields from the ACTUAL fmt chunk and find data.
        // CreateWav emits a JUNK padding chunk before fmt, so fixed offsets are
        // wrong — the fmt chunk is not at offset 12.
        int channels = 1, sampleRate = 16000;
        int i = 12, dataOffset = -1, dataLen = 0;
        while (i + 8 <= wav.Length)
        {
            string id = System.Text.Encoding.ASCII.GetString(wav, i, 4);
            int size = BitConverter.ToInt32(wav, i + 4);
            int body = i + 8;
            if (id == "fmt " && body + 16 <= wav.Length)
            {
                channels = BitConverter.ToInt16(wav, body + 2);
                sampleRate = BitConverter.ToInt32(wav, body + 4);
            }
            else if (id == "data")
            {
                dataOffset = body;
                dataLen = size;
                break;  // fmt precedes data in a WAV, so it is already read
            }
            i = body + size + (size & 1);
        }
        if (channels < 1) channels = 1;
        if (sampleRate < 1) sampleRate = 16000;
        if (dataOffset < 0 || dataOffset + dataLen > wav.Length)
            return new Result(Array.Empty<byte>(), sampleRate, channels, 0f);

        var pcm = new byte[dataLen];
        Array.Copy(wav, dataOffset, pcm, 0, dataLen);

        float peak = 0f;
        for (int s = 0; s + 1 < dataLen; s += 2)
        {
            short v = (short)(pcm[s] | (pcm[s + 1] << 8));
            float a = Math.Abs(v) / 32768f;
            if (a > peak) peak = a;
        }
        return new Result(pcm, sampleRate, channels, peak);
    }

    private static string Hr(Exception? ex) => ex is null ? "" : $" (0x{ex.HResult:X8}: {ex.Message})";

    private static void SafeDispose(IDisposable? d)
    {
        try { d?.Dispose(); } catch { /* already closed (e.g. by FinalizeAsync) */ }
    }

    public ValueTask DisposeAsync()
    {
        SafeDispose(_fileOutput); _fileOutput = null;
        SafeDispose(_input); _input = null;
        SafeDispose(_graph); _graph = null;
        return ValueTask.CompletedTask;
    }
}
