using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;

namespace AnimaNative.Check;

/// <summary>Plan E3 Task 5: <c>GET /play/orders?since=</c> from the fixture's <c>orders.json</c> (404 when it has none).</summary>
public sealed partial class FixtureSource
{
    /// <summary>The <c>since</c> of every orders request, in order (the check reads it).</summary>
    public List<long> OrdersSince { get; } = new();

    public Task<JsonDocument> GetOrdersAsync(long since)
    {
        OrdersSince.Add(since);
        return File.Exists(PathOf("orders.json"))
            ? Doc("orders.json")
            : Task.FromException<JsonDocument>(new ApiException(404, "/play/orders", "no orders.json in " + _dir));
    }
}
