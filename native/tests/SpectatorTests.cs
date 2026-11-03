using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Embody;
using Xunit;

namespace AnimaNative.Tests;

public class SpectatorTests
{
    [Theory]
    [InlineData("", false, true)]
    [InlineData("Kai", false, false)]
    [InlineData("Kai", true, true)]
    public void AvatarControllersSuspendUntilControlReturns(string avatar, bool changing, bool expected)
    {
        using var map = JsonDocument.Parse(JsonSerializer.Serialize(new { avatar }));
        Assert.Equal(expected, AvatarSession.Suspended(map.RootElement, changing));
    }

    [Fact]
    public void IntentionalReleaseWinsOverRememberedIdentityWhileTemporaryAbsenceCanRecover()
    {
        using var missing = JsonDocument.Parse("""{"avatar":""}""");
        using var released = JsonDocument.Parse("""{"avatar":"","avatar_released":true}""");
        Assert.False(AvatarSession.Suspended(missing.RootElement, hasRememberedAvatar: true));
        Assert.True(AvatarSession.Suspended(released.RootElement, hasRememberedAvatar: true));
    }

    [Fact]
    public async Task ReleasedLoginCannotRecoverAnOldAvatar()
    {
        using var api = new AnimaNative.Api.AnimaApi("http://fixture/");
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask);
        using var login = JsonDocument.Parse("""{"user":{"settings":{"avatar_released":true,"active_character":"Old","default_character":"Old"}}}""");
        using var map = JsonDocument.Parse("""{"avatar":"","characters":[]}""");
        recovery.RememberLogin(login.RootElement);
        await recovery.RememberFirstMapAsync(map.RootElement);
        Assert.Null(recovery.OwnCharacter);
        Assert.False(recovery.TryBegin(map.RootElement));
        Assert.Null(recovery.Request);
    }
}
