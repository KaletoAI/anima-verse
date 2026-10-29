using System.Text;
using AnimaNative.Audio;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 59: do not trust a .mp3 suffix or accept a non-WAVE RIFF container.</summary>
public class AudioFormatTests
{
    [Theory]
    [InlineData("ID3stuff", AudioFormat.Mp3)]
    [InlineData("OggSdata", AudioFormat.Ogg)]
    [InlineData("RIFF1234WAVEdata", AudioFormat.Wav)]
    [InlineData("RIFF1234AVI data", AudioFormat.Unknown)]
    [InlineData("broken.mp3", AudioFormat.Unknown)]
    [InlineData("", AudioFormat.Unknown)]
    [InlineData("I", AudioFormat.Unknown)]
    [InlineData("Og", AudioFormat.Unknown)]
    public void ContainerSignature(string bytes, AudioFormat expected)
        => Assert.Equal(expected, AudioFormats.Detect(Encoding.ASCII.GetBytes(bytes)));
    [Fact]
    public void Mp3WithoutId3UsesFrameSync() => Assert.Equal(AudioFormat.Mp3, AudioFormats.Detect(new byte[] { 0xff, 0xe3, 0x18, 0xc4 }));
}
