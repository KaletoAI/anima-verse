using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AnimaNative.Api;

public partial interface IWorldSource
{
    Task<JsonDocument> GetAccountCharactersAsync()
        => Task.FromException<JsonDocument>(new ApiException(404, "/account/characters"));
    Task<JsonDocument> SwitchCharacterAsync(string name, CancellationToken ct = default)
        => Task.FromException<JsonDocument>(new ApiException(404, "/account/switch-character"));
}

public sealed partial class AnimaApi
{
    public Task<JsonDocument> GetAccountCharactersAsync() => GetJson("/account/characters");

    /// <summary>Same cookie, body and refusal semantics as api.ts switchCharacter; bounded headers and body.</summary>
    public Task<JsonDocument> SwitchCharacterAsync(string name, CancellationToken ct = default)
        => PostPropAction("/account/switch-character", JsonSerializer.SerializeToElement(new { character_name = name }), ct);
}
