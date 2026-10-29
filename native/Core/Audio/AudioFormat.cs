using System;

namespace AnimaNative.Audio;

/// <summary>Task 59: signatures, independent of URL extensions (TTS can use opaque URLs).</summary>
public enum AudioFormat { Unknown, Mp3, Ogg, Wav }

/// <summary>Task 59: identify only supported containers before calling a Godot decoder.</summary>
public static class AudioFormats
{
    public static AudioFormat Detect(ReadOnlySpan<byte> bytes)
    {
        if (bytes.StartsWith("ID3"u8) || bytes.Length >= 2 && bytes[0] == 0xff && (bytes[1] & 0xe0) == 0xe0) return AudioFormat.Mp3;
        if (bytes.StartsWith("OggS"u8)) return AudioFormat.Ogg;
        if (bytes.Length >= 12 && bytes.StartsWith("RIFF"u8) && bytes.Slice(8, 4).SequenceEqual("WAVE"u8)) return AudioFormat.Wav;
        return AudioFormat.Unknown;
    }
}
