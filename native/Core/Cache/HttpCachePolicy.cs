using System;
using System.Net.Http;
using System.Linq;

namespace AnimaNative.Cache;

/// <summary>Task 62 / E10-T1, inventory §2.3 / R-2: only RESPONSE directives grant immutability.
/// No-cache overrides freshness; no-store overrides everything; Age/Date reduce the remaining max-age.</summary>
public sealed record HttpCachePolicy(bool Store, bool Immutable, DateTimeOffset FreshUntil, string CacheControl)
{
    public static HttpCachePolicy From(HttpResponseMessage response, DateTimeOffset now, string? previous = null)
    {
        var text = response.Headers.CacheControl?.ToString() ?? previous ?? "";
        System.Net.Http.Headers.CacheControlHeaderValue.TryParse(text, out var cc);
        bool immutable = cc?.Extensions.Any(e => e.Name.Equals("immutable", StringComparison.OrdinalIgnoreCase)) ?? false;
        double age = Math.Max(response.Headers.Age?.TotalSeconds ?? 0,
            response.Headers.Date is { } date ? Math.Max(0, (now - date).TotalSeconds) : 0);
        double seconds = Math.Max(0, (cc?.MaxAge?.TotalSeconds ?? 0) - age);
        return new(cc?.NoStore != true, immutable && cc?.NoCache != true && cc?.NoStore != true,
            now.AddSeconds(cc?.NoCache == true ? 0 : seconds), text);
    }
}
