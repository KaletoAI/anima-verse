using System.Linq;
using System.Text.Json;
using AnimaNative.Ui;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The launcher's remembered settings (<c>user://launcher.json</c>): server and user name
/// survive a restart, a broken file costs nothing but the pre-fill, and the password
/// never reaches the file.
/// </summary>
public class LauncherSettingsTests
{
    [Theory]
    [InlineData("{")]
    [InlineData("")]
    [InlineData(null)]
    [InlineData("[]")]
    [InlineData("\"server\"")]
    [InlineData("{\"server\": 5, \"user\": [1], \"fullscreen\": \"yes\"}")]
    public void CorruptFileYieldsDefaults(string? text)
    {
        var s = LauncherSettings.Parse(text);
        Assert.Equal("", s.Server);
        Assert.Equal("", s.User);
        Assert.False(s.Fullscreen);
    }

    [Fact]
    public void ParsesAStoredFile()
    {
        var s = LauncherSettings.Parse("{\"server\": \"http://192.168.8.244:8000\", \"user\": \"demo\", \"fullscreen\": true}");
        Assert.Equal("http://192.168.8.244:8000", s.Server);
        Assert.Equal("demo", s.User);
        Assert.True(s.Fullscreen);
    }

    [Fact]
    public void AStoredServerIsNormalisedOnRead()
    {
        // A hand-edited file in user form still pre-fills a usable address; an unusable one is dropped.
        Assert.Equal("http://192.168.8.244:8000", LauncherSettings.Parse("{\"server\": \"192.168.8.244:8000/\"}").Server);
        Assert.Equal("", LauncherSettings.Parse("{\"server\": \"ftp://x\", \"user\": \"demo\"}").Server);
        Assert.Equal("demo", LauncherSettings.Parse("{\"server\": \"ftp://x\", \"user\": \"demo\"}").User);
    }

    [Theory]
    [InlineData("192.168.8.244:8000", "http://192.168.8.244:8000")]
    [InlineData(" http://192.168.8.244:8000/ ", "http://192.168.8.244:8000")]
    [InlineData("https://x.y/", "https://x.y")]
    [InlineData("localhost:8000", "http://localhost:8000")]
    [InlineData("HTTP://Host:8000//", "HTTP://Host:8000")]
    [InlineData("  ", null)]
    [InlineData("", null)]
    [InlineData("ftp://x.y", null)]
    [InlineData("http://", null)]
    [InlineData("http://a b", null)]
    public void NormalizesServerUrl(string input, string? expected)
    {
        Assert.Equal(expected, LauncherSettings.NormalizeServer(input));
    }

    [Fact]
    public void CliOverridesStored()
    {
        var stored = new LauncherSettings { Server = "http://stored:8000", User = "stored", Fullscreen = true };

        var both = LauncherSettings.Merge(stored, "http://cli:8000", "cli");
        Assert.Equal("http://cli:8000", both.Server);
        Assert.Equal("cli", both.User);
        Assert.True(both.Fullscreen);   // not a CLI flag: always the stored value

        var none = LauncherSettings.Merge(stored, null, null);
        Assert.Equal(stored, none);

        var blank = LauncherSettings.Merge(stored, "  ", " ");
        Assert.Equal(stored, blank);

        var userOnly = LauncherSettings.Merge(stored, null, " cli ");
        Assert.Equal("http://stored:8000", userOnly.Server);
        Assert.Equal("cli", userOnly.User);

        // Nothing stored, nothing given: the empty fields of a first start.
        var first = LauncherSettings.Merge(LauncherSettings.Parse(null), null, null);
        Assert.Equal(("", "", false), (first.Server, first.User, first.Fullscreen));

        // The CLI value is normalised like a typed one.
        Assert.Equal("http://192.168.8.244:8000", LauncherSettings.Merge(stored, "192.168.8.244:8000/", null).Server);
    }

    [Fact]
    public void NeverSerializesPassword()
    {
        // Even a file someone wrote a password into loses it on the next save.
        var s = LauncherSettings.Parse("{\"server\": \"http://h:8000\", \"user\": \"demo\", \"password\": \"secret\", \"fullscreen\": true}");
        var text = s.Serialize();
        using var doc = JsonDocument.Parse(text);
        var keys = doc.RootElement.EnumerateObject().Select(p => p.Name).OrderBy(k => k).ToArray();
        Assert.Equal(new[] { "fullscreen", "server", "user" }, keys);
        Assert.DoesNotContain("secret", text);
        Assert.DoesNotContain("password", text);
    }

    [Fact]
    public void RoundTrips()
    {
        var s = new LauncherSettings { Server = "https://x.y", User = "Name With Spaces", Fullscreen = true };
        Assert.Equal(s, LauncherSettings.Parse(s.Serialize()));
        var d = LauncherSettings.Parse(null);
        Assert.Equal(d, LauncherSettings.Parse(d.Serialize()));
    }
}
