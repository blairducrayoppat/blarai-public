using System.IO;
using System.Text;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Storage.Streams;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Streaming playback of synthesized speech (ADR-017). Each PCM chunk is wrapped
/// in an in-memory WAV and appended to a <see cref="MediaPlaybackList"/>, which
/// plays items back-to-back. This is the path verified audible on hardware; the
/// AudioGraph frame-input alternative produced silence (same WinRT frame-I/O
/// finickiness that bit capture), so it was abandoned.
///
/// For sentence-by-sentence streaming arrival, the list can run dry between
/// chunks; <see cref="EnqueueAsync"/> resumes the player when a new chunk lands,
/// so a slow-arriving reply keeps playing rather than stopping at the first gap.
/// </summary>
public sealed class VoicePlayback : IAsyncDisposable
{
    private readonly MediaPlayer _player = new();
    private MediaPlaybackList _list = new();

    public VoicePlayback()
    {
        _player.AutoPlay = true;
        _player.Source = _list;
    }

    /// <summary>Stop playback and discard anything queued (new reply / denial).</summary>
    public Task ResetAsync()
    {
        try { _player.Pause(); } catch { /* nothing playing */ }
        _list = new MediaPlaybackList();
        _player.Source = _list;
        return Task.CompletedTask;
    }

    /// <summary>Append one PCM chunk to the playback queue and keep it playing.</summary>
    public async Task EnqueueAsync(byte[] pcm16, int sampleRate)
    {
        byte[] wav = WrapWav(pcm16, sampleRate, channels: 1, bitsPerSample: 16);
        var ras = new InMemoryRandomAccessStream();
        using (var output = ras.GetOutputStreamAt(0))
        using (var writer = new DataWriter(output))
        {
            writer.WriteBytes(wav);
            await writer.StoreAsync();
            await writer.FlushAsync();
            writer.DetachStream();
        }
        ras.Seek(0);
        _list.Items.Add(new MediaPlaybackItem(MediaSource.CreateFromStream(ras, "audio/wav")));

        // Streaming arrival: if the list had run dry before this chunk arrived,
        // nudge the player to resume (AutoPlay only fires on initial Source set).
        var state = _player.PlaybackSession.PlaybackState;
        if (state is MediaPlaybackState.Paused or MediaPlaybackState.None)
            _player.Play();
    }

    /// <summary>Wrap raw PCM in a 44-byte canonical WAV header.</summary>
    private static byte[] WrapWav(byte[] pcm, int sampleRate, int channels, int bitsPerSample)
    {
        int byteRate = sampleRate * channels * bitsPerSample / 8;
        int blockAlign = channels * bitsPerSample / 8;
        using var ms = new MemoryStream();
        using var bw = new BinaryWriter(ms);
        bw.Write(Encoding.ASCII.GetBytes("RIFF"));
        bw.Write(36 + pcm.Length);
        bw.Write(Encoding.ASCII.GetBytes("WAVE"));
        bw.Write(Encoding.ASCII.GetBytes("fmt "));
        bw.Write(16);
        bw.Write((short)1);
        bw.Write((short)channels);
        bw.Write(sampleRate);
        bw.Write(byteRate);
        bw.Write((short)blockAlign);
        bw.Write((short)bitsPerSample);
        bw.Write(Encoding.ASCII.GetBytes("data"));
        bw.Write(pcm.Length);
        bw.Write(pcm);
        bw.Flush();
        return ms.ToArray();
    }

    public ValueTask DisposeAsync()
    {
        _player.Dispose();
        return ValueTask.CompletedTask;
    }
}
