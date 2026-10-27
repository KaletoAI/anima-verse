using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.World;

namespace AnimaNative.Api;

/// <summary>Protocol barrier before manual position ownership; all actual participant runs must release before waking.</summary>
public static class OwnedPropControl
{
    public static async Task ReleaseAsync(JsonElement state, Func<string, Task<JsonDocument>> cancel,
                                         Func<Task<JsonDocument>> wake)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (string group in new[] { "current", "outgoing", "incoming" })
        {
            if (!state.TryGetProperty(group, out var runs) || runs.ValueKind != JsonValueKind.Array) continue;
            foreach (var run in runs.EnumerateArray())
            {
                string id = Json.Str(run, "execution_id");
                if (id.Length == 0 || !seen.Add(id)) continue;
                using var cancelled = await cancel(id);
                if (Json.Str(cancelled.RootElement, "status") == "refused")
                    throw new InvalidOperationException(Json.Str(cancelled.RootElement, "reason", "Cancellation refused"));
            }
        }
        using var awake = await wake();
        if (!awake.RootElement.TryGetProperty("ok", out var ok) || ok.ValueKind != JsonValueKind.True)
            throw new InvalidOperationException("Waking failed; manual position ownership was not acquired");
    }
}
