using System;
using System.IO;
using AnimaNative.Ui;
using Xunit;

namespace AnimaNative.Tests;

public class RememberedSessionTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "anima-session-" + Guid.NewGuid().ToString("N"));
    private SessionStore Store => new(Path.Combine(_dir, "session.json"));
    public RememberedSessionTests() => Directory.CreateDirectory(_dir);
    public void Dispose() => Directory.Delete(_dir, true);

    [Fact]
    public void RoundTripMatchesOnlyTheNormalizedServerAndNeverStoresAPassword()
    {
        Assert.Null(Store.LoadFor("example.org:8000"));
        Assert.True(Store.Save(new RememberedSession("http://example.org:8000", "Ada", "private-token", "admin")));
        var saved = Store.LoadFor(" example.org:8000/ ");
        Assert.NotNull(saved);
        Assert.Equal("Ada", saved.User);
        Assert.Equal("private-token", saved.Token);
        Assert.Equal("admin", saved.Role);
        Assert.Null(Store.LoadFor("https://example.org:8000"));
        Assert.Null(Store.LoadFor("example.org:9000"));
        Assert.DoesNotContain("password", File.ReadAllText(Store.Path));
        Assert.DoesNotContain("private-token", saved.ToString());
        Assert.Single(Directory.GetFiles(_dir));
        Assert.True(Store.Delete());
        Assert.Null(Store.LoadFor("example.org:8000"));
    }

    [Fact]
    public void ReplacementIsPrivateOnLinux()
    {
        if (!OperatingSystem.IsLinux()) return;
        File.WriteAllText(Store.Path, "old entry");
        File.SetUnixFileMode(Store.Path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.OtherRead);
        Assert.True(Store.Save(new RememberedSession("http://host", "Ada", "secret", "user")));
        Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite, File.GetUnixFileMode(Store.Path));
    }

    [Theory]
    [InlineData("{")]
    [InlineData("null")]
    [InlineData("[]")]
    [InlineData("{\"server\":\"http://host\",\"user\":\"Ada\",\"token\":42,\"role\":\"user\"}")]
    [InlineData("{\"server\":\"http://host\",\"user\":\"Ada\",\"token\":\"\",\"role\":\"user\"}")]
    public void BrokenEntriesAreAbsent(string text)
    {
        File.WriteAllText(Store.Path, text);
        Assert.Null(Store.LoadFor("http://host"));
    }
}
