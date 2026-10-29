using System;
using System.Diagnostics;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;

namespace AnimaNative.Embody;

/// <summary>
/// A session remembers its avatar once. Each explicit control request may restore that avatar once,
/// then waits for authoritative placement and a ready figure. Cancellation invalidates late replies.
/// </summary>
public sealed class AvatarRecovery : IDisposable
{
    public const string MissingMessage = "Your avatar is not on the map yet.";
    private readonly IWorldSource _source;
    private readonly Func<Task> _refreshMap;
    private readonly Func<double> _now;
    private bool _identityResolved, _attempted;
    private Task? _identity;
    private int _generation;
    private double _deadline;
    private CancellationTokenSource? _attempt;
    public AvatarRecovery(IWorldSource source, Func<Task> refreshMap, Func<double>? now = null)
    {
        _source = source; _refreshMap = refreshMap;
        _now = now ?? (() => Stopwatch.GetTimestamp() * 1000.0 / Stopwatch.Frequency);
    }
    public string? OwnCharacter { get; private set; }
    public bool Waiting { get; private set; }
    public string? Failure { get; private set; }
    public Task? Request { get; private set; }
    public event Action<string>? Remembered;

    private static string? Text(JsonElement e, string key)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(v.GetString()) ? v.GetString() : null;
    private void Remember(string? name)
    {
        if (OwnCharacter is not null || name is null) return;
        OwnCharacter = name;
        Remembered?.Invoke(name);
    }
    public void RememberLogin(JsonElement login)
    {
        if (_identityResolved || login.ValueKind != JsonValueKind.Object) return;
        if (login.TryGetProperty("user", out var user) && user.ValueKind == JsonValueKind.Object
            && user.TryGetProperty("settings", out var settings)) Remember(Text(settings, "active_character"));
    }

    public Task RememberFirstMapAsync(JsonElement map) => _identity ??= ResolveIdentityAsync(map);
    private async Task ResolveIdentityAsync(JsonElement map)
    {
        _identityResolved = true;
        Remember(Text(map, "avatar"));
        if (OwnCharacter is not null) return;
        try
        {
            using var account = await _source.GetAccountCharactersAsync();
            Remember(Text(account.RootElement, "active_character"));
        }
        catch (Exception) { /* An unknown identity must never be guessed from a later map. */ }
    }

    private static JsonElement? Row(JsonElement? map, string name)
    {
        if (map is not { ValueKind: JsonValueKind.Object } m || !m.TryGetProperty("characters", out var chars)
            || chars.ValueKind != JsonValueKind.Array) return null;
        foreach (var row in chars.EnumerateArray()) if (Text(row, "name") == name) return row;
        return null;
    }
    private static bool HasPoint(JsonElement? row)
        => row is { } r && r.TryGetProperty("pos", out var pos) && pos.ValueKind == JsonValueKind.Object
            && pos.TryGetProperty("x", out var x) && x.ValueKind == JsonValueKind.Number && x.TryGetDouble(out var xx) && double.IsFinite(xx)
            && pos.TryGetProperty("z", out var z) && z.ValueKind == JsonValueKind.Number && z.TryGetDouble(out var zz) && double.IsFinite(zz);
    private bool OwnMap(JsonElement? map) => OwnCharacter is not null && map is { } m && Text(m, "avatar") == OwnCharacter;

    public bool NeedsRecovery(JsonElement? map)
    {
        if (OwnCharacter is null) return false;
        var row = Row(map, OwnCharacter);
        return !OwnMap(map) || row is null || (!HasPoint(row) && Text(row.Value, "location_id") is null);
    }

    public bool TryBegin(JsonElement? map, CancellationToken ct = default)
    {
        if (Waiting) return true;
        if (ct.IsCancellationRequested || !NeedsRecovery(map)) return false;
        if (_attempted)
        {
            // A second release during figure/place loading cannot spend another POST for the same press.
            Waiting = true;
            Tick(map, false);
            return false;
        }
        _attempted = true;
        Waiting = true;
        _deadline = _now() + 10000;
        _attempt = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _attempt.CancelAfter(10000);
        Request = RestoreAsync(OwnCharacter!, _generation, _attempt.Token);
        return true;
    }

    private async Task RestoreAsync(string name, int generation, CancellationToken ct)
    {
        try
        {
            using var answer = await _source.SwitchCharacterAsync(name, ct);
            if (generation != _generation || ct.IsCancellationRequested) return;
            await _refreshMap();
        }
        catch (Exception e)
        {
            if (generation != _generation) return;
            // Only an authoritative refusal ends the request early. Transport loss gets the full placement wait.
            if (e is ApiException api)
            {
                Failure = api.Detail ?? api.Message;
                Waiting = false;
            }
        }
    }

    public bool Tick(JsonElement? map, bool figureReady)
    {
        if (!Waiting) return false;
        if (OwnMap(map) && HasPoint(Row(map, OwnCharacter!)))
        {
            // Placement has arrived; model loading retains the existing wait, even after ten seconds.
            if (figureReady) Waiting = false;
            return figureReady;
        }
        if (_now() >= _deadline)
        {
            Failure = MissingMessage;
            Waiting = false;
            _generation++;
            _attempt?.Cancel();
        }
        return false;
    }

    public void Cancel()
    {
        _generation++;
        _attempt?.Cancel(); _attempt?.Dispose(); _attempt = null;
        Waiting = _attempted = false;
        Failure = null;
    }
    public void Dispose() => Cancel();
}
