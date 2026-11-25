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

    /// <summary>
    /// Plan E3 Task 7: <c>POST /play/order/arrived</c> — the avatar reached its access on its own walk (the server never
    /// walks a player-controlled figure). Answers <c>{"ok": true}</c>; a refusal is a 409 whose detail names the reason
    /// (<c>order_unknown</c>, <c>arrive_too_far</c>, <c>room_mismatch</c> or the run's own reason).
    /// </summary>
    Task<JsonDocument> PostOrderArrivedAsync(string orderId, double x, double z, double yaw, string roomId)
        => Task.FromException<JsonDocument>(new ApiException(404, "/play/order/arrived", "not served by this source"));
}

public sealed partial class AnimaApi
{
    public Task<JsonDocument> GetOrdersAsync(long since) => GetJson($"/play/orders?since={since}");

    public Task<JsonDocument> PostOrderArrivedAsync(string orderId, double x, double z, double yaw, string roomId)
        => PostPropAction("/play/order/arrived", OrderArrived.Body(orderId, x, z, yaw, roomId), default);
}

/// <summary>
/// <c>POST /play/order/arrived</c>: its body <c>{order_id, x, z, yaw, room_id}</c> (yaw in radians, as <c>/play/pos</c>)
/// and the reading of its answer — "" for an acceptance, else the refusal's reason.
/// </summary>
public static class OrderArrived
{
    public static JsonElement Body(string orderId, double x, double z, double yaw, string roomId)
        => JsonSerializer.SerializeToElement(new { order_id = orderId, x, z, yaw, room_id = roomId });

    /// <summary>A 200 answer: "" when it says <c>ok: true</c>, else its <c>reason</c> (<c>refused</c> without one).</summary>
    public static string RefusalOf(JsonElement answer)
    {
        if (answer.ValueKind == JsonValueKind.Object && answer.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.True)
            return "";
        return ReasonIn(answer) ?? "refused";
    }

    /// <summary>A 409's detail (the server's refusal object as JSON text): its <c>reason</c>, else the text, else <c>refused</c>.</summary>
    public static string RefusalOf(ApiException e)
    {
        if (string.IsNullOrWhiteSpace(e.Detail)) return "refused";
        try
        {
            using var doc = JsonDocument.Parse(e.Detail);
            if (ReasonIn(doc.RootElement) is { } reason) return reason;
        }
        catch (JsonException)
        {
            // A plain-text detail names the reason itself.
        }
        return e.Detail;
    }

    private static string? ReasonIn(JsonElement e)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty("reason", out var r) && r.ValueKind == JsonValueKind.String
           && r.GetString() is { Length: > 0 } reason ? reason : null;
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
