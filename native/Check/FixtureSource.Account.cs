using System.Collections.Generic;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;

namespace AnimaNative.Check;

public sealed partial class FixtureSource
{
    public Queue<JsonElement> AvatarMaps { get; } = new();
    public List<JsonElement> CharacterSwitchRequests { get; } = new();
    public int AvatarMapRequests { get; private set; }
    public string? AccountAvatar { get; set; }
    public int CharacterSwitchStatus { get; set; } = 200;
    public string CharacterSwitchDetail { get; set; } = "";
    public TaskCompletionSource? CharacterSwitchGate { get; set; }

    public Task<JsonDocument> GetAccountCharactersAsync() => Task.FromResult(JsonDocument.Parse(
        JsonSerializer.Serialize(new { active_character = AccountAvatar ?? "", characters = new string[0], default_character = "" })));

    public async Task<JsonDocument> SwitchCharacterAsync(string name, CancellationToken ct = default)
    {
        CharacterSwitchRequests.Add(JsonSerializer.SerializeToElement(new { character_name = name }));
        if (CharacterSwitchGate is { } gate) await gate.Task.WaitAsync(ct);
        ct.ThrowIfCancellationRequested();
        if (CharacterSwitchStatus is < 200 or >= 300)
            throw new ApiException(CharacterSwitchStatus, "/account/switch-character", CharacterSwitchDetail);
        return JsonDocument.Parse(JsonSerializer.Serialize(new { status = "success", active_character = name, previous_character = "" }));
    }

    private Task<JsonDocument> AvatarMap()
    {
        AvatarMapRequests++;
        return Task.FromResult(JsonDocument.Parse(AvatarMaps.Dequeue().GetRawText()));
    }
}
