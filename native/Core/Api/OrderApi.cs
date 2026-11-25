using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Orders;

namespace AnimaNative.Api;

/// <summary>
/// Plan E3 Task 5: <c>GET /play/orders?since=&lt;seq&gt;</c> (docs/schnittstellen-3d.md § A11b) — the visible orders with
/// <c>seq &gt; since</c>, the highest <c>seq</c> handed out and the server's <c>motion_now</c>. Optional like the other
/// play endpoints: a source that does not serve it answers 404.
/// </summary>
public partial interface IWorldSource
{
    Task<JsonDocument> GetOrdersAsync(long since)
        => Task.FromException<JsonDocument>(new ApiException(404, "/play/orders", "not served by this source"));
}

public sealed partial class AnimaApi
{
    public Task<JsonDocument> GetOrdersAsync(long since) => GetJson($"/play/orders?since={since}");
}

/// <summary>
/// One <c>/play/orders</c> answer read: the orders <see cref="OrderParse.From"/> accepts (a broken one is dropped, never
/// half played), <c>seq</c> (0 when missing) and <c>motion_now</c> (null when missing).
/// </summary>
public sealed record OrdersPayload(IReadOnlyList<Order> Orders, long Seq, double? MotionNow)
{
    public static OrdersPayload Parse(JsonElement root)
    {
        var orders = new List<Order>();
        if (root.ValueKind != JsonValueKind.Object) return new OrdersPayload(orders, 0, null);
        if (root.TryGetProperty("orders", out var list) && list.ValueKind == JsonValueKind.Array)
            foreach (var o in list.EnumerateArray())
                if (OrderParse.From(o) is { } order) orders.Add(order);
        long seq = root.TryGetProperty("seq", out var s) && s.ValueKind == JsonValueKind.Number && s.TryGetInt64(out var sv) ? sv : 0;
        double? now = root.TryGetProperty("motion_now", out var n) && n.ValueKind == JsonValueKind.Number && double.IsFinite(n.GetDouble())
            ? n.GetDouble() : null;
        return new OrdersPayload(orders, seq, now);
    }
}
