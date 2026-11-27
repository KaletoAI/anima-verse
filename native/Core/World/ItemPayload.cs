using System;
using System.Collections.Generic;
using System.Text.Json;

namespace AnimaNative.World;

/// <summary>One action offered on a world-placeable room item (<c>GET /play/locations/{id}/items</c>).</summary>
public sealed record WorldItemAction(string Id, string Label, string Source);

/// <summary>One visible, anchored, world-placeable room item in location-local metres.</summary>
public sealed record WorldItem(
    string ItemId,
    string RoomId,
    string Name,
    int Quantity,
    double X,
    double Z,
    double Y,
    double Yaw,
    double SizeM,
    string? ModelUrl,
    string? ImageUrl,
    IReadOnlyList<WorldItemAction> Actions);

/// <summary>Godot-free parser for <c>GET /play/locations/{location_id}/items</c>.</summary>
public static class ItemPayload
{
    public static IReadOnlyList<WorldItem> Parse(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object
            || !root.TryGetProperty("items", out var itemsEl)
            || itemsEl.ValueKind != JsonValueKind.Array)
            return Array.Empty<WorldItem>();

        var list = new List<WorldItem>();
        foreach (var e in itemsEl.EnumerateArray())
        {
            if (e.ValueKind != JsonValueKind.Object) continue;
            if (!e.TryGetProperty("item_id", out var idEl) || idEl.ValueKind != JsonValueKind.String) continue;
            string itemId = idEl.GetString() ?? "";
            if (itemId.Length == 0) continue;

            if (!e.TryGetProperty("room_id", out var roomEl) || roomEl.ValueKind != JsonValueKind.String) continue;
            string roomId = roomEl.GetString() ?? "";

            if (!e.TryGetProperty("at", out var atEl) || atEl.ValueKind != JsonValueKind.Array || atEl.GetArrayLength() < 2)
                continue;
            if (Json.NumOrNull(atEl[0]) is not double x || Json.NumOrNull(atEl[1]) is not double z)
                continue;

            if (!e.TryGetProperty("y", out var yEl) || Json.NumOrNull(yEl) is not double y)
                continue;

            double yaw = 0;
            if (e.TryGetProperty("yaw", out var yawEl) && yawEl.ValueKind != JsonValueKind.Null)
            {
                if (Json.NumOrNull(yawEl) is not double yd) continue;
                yaw = yd;
            }

            double sizeM = 0.25;
            if (e.TryGetProperty("size_m", out var sizeEl) && sizeEl.ValueKind != JsonValueKind.Null)
            {
                if (Json.NumOrNull(sizeEl) is not double sm || sm <= 0) continue;
                sizeM = sm;
            }

            int quantity = 1;
            if (e.TryGetProperty("quantity", out var qtyEl) && qtyEl.ValueKind != JsonValueKind.Null)
            {
                if (qtyEl.ValueKind != JsonValueKind.Number || !qtyEl.TryGetInt32(out int q) || q < 1) continue;
                quantity = q;
            }

            string name = Json.Str(e, "name");
            if (name.Length == 0) name = itemId;

            string? modelUrl = OptionalUrl(e, "model_url");
            string? imageUrl = OptionalUrl(e, "image_url");

            var actions = ParseActions(e);
            list.Add(new WorldItem(itemId, roomId, name, quantity, x, z, y, yaw, sizeM, modelUrl, imageUrl, actions));
        }

        return list;
    }

    private static string? OptionalUrl(JsonElement e, string key)
        => e.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String && v.GetString() is { Length: > 0 } s
            ? s
            : null;

    private static IReadOnlyList<WorldItemAction> ParseActions(JsonElement e)
    {
        if (!e.TryGetProperty("actions", out var actEl) || actEl.ValueKind != JsonValueKind.Array)
            return Array.Empty<WorldItemAction>();

        var actions = new List<WorldItemAction>();
        foreach (var a in actEl.EnumerateArray())
        {
            if (a.ValueKind == JsonValueKind.Object)
            {
                string id = Json.Str(a, "id");
                if (id.Length == 0) continue;
                string label = Json.Str(a, "label");
                if (label.Length == 0) label = id;
                string source = Json.Str(a, "source");
                actions.Add(new WorldItemAction(id, label, source));
            }
            else if (a.ValueKind == JsonValueKind.String && a.GetString() is { Length: > 0 } bareId)
            {
                actions.Add(new WorldItemAction(bareId, bareId, ""));
            }
        }

        return actions;
    }
}
