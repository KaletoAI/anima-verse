using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Scatter;

namespace AnimaNative.Orders;

/// <summary>
/// Reads the wire form of an order (plan E3 decision 2, <c>motion_orders.new_order</c>). A missing or empty
/// <c>order_id</c>, an unknown <c>kind</c>, a non-finite number or a field of the wrong type yields <c>null</c>; the
/// caller drops such an order instead of playing half of it. <c>flip_motion_s</c> may be missing or null (an order
/// that awaits a reaction or a grant has none).
/// </summary>
public static class OrderParse
{
    /// <summary>The kinds E3 sends (<c>motion_orders.KINDS</c>); <c>pair</c> and <c>travel</c> come with E5/E6.</summary>
    public static readonly IReadOnlyList<string> Kinds = new[] { "prop_action", "walk", "cancel" };

    private sealed class BadOrder : Exception
    {
    }

    public static Order? From(JsonElement e)
    {
        if (e.ValueKind != JsonValueKind.Object)
            return null;
        try
        {
            string id = Str(e, "order_id");
            if (id.Length == 0)
                return null;
            string kind = Str(e, "kind");
            if (!Kinds.Contains(kind))
                return null;
            var actors = new List<OrderActor>();
            if (e.TryGetProperty("actors", out var list) && list.ValueKind != JsonValueKind.Null)
            {
                if (list.ValueKind != JsonValueKind.Array)
                    throw new BadOrder();
                foreach (var a in list.EnumerateArray())
                    actors.Add(Actor(a));
            }
            string location = "", room = "";
            int level = 0;
            OrderPoint? goal = null;
            if (e.TryGetProperty("target", out var target) && target.ValueKind == JsonValueKind.Object)
            {
                location = Str(target, "location_id");
                room = Str(target, "room_id");
                level = (int)(OptNum(target, "level") ?? 0);
                if (OptNum(target, "x") is { } gx && OptNum(target, "z") is { } gz)
                    goal = new OrderPoint(gx, OptNum(target, "y") ?? 0, gz, OptNum(target, "yaw") ?? 0);
            }
            double speed = Num(e, "speed_m_s");
            // As motion_orders.new_order: a moving order needs a positive speed, a cancel may carry 0, never below.
            if (speed < 0 || (kind != "cancel" && speed == 0))
                return null;
            return new Order(
                id, (int)Num(e, "revision"), (long)(OptNum(e, "seq") ?? 0), kind,
                Num(e, "issued_motion_s"), Num(e, "eta_motion_s"), OptNum(e, "flip_motion_s"), Num(e, "deadline_motion_s"),
                Str(e, "status"), Str(e, "awaits"), Str(e, "gait"), speed,
                actors, location, room, level, goal, Route(e), Bool(e, "snap"));
        }
        catch (BadOrder)
        {
            return null;
        }
    }

    private static OrderActor Actor(JsonElement a)
    {
        if (a.ValueKind != JsonValueKind.Object)
            throw new BadOrder();
        if (!a.TryGetProperty("start", out var start) || start.ValueKind != JsonValueKind.Object)
            throw new BadOrder();
        var steps = new List<OrderStep>();
        if (a.TryGetProperty("sequence", out var seq) && seq.ValueKind != JsonValueKind.Null)
        {
            if (seq.ValueKind != JsonValueKind.Array)
                throw new BadOrder();
            foreach (var s in seq.EnumerateArray())
            {
                if (s.ValueKind != JsonValueKind.Object)
                    throw new BadOrder();
                steps.Add(new OrderStep(Str(s, "step"), Str(s, "pose_kind"), Str(s, "pose_key"), OptNum(s, "nominal_s") ?? 0));
            }
        }
        var anchor = OptPoint(a, "anchor");
        double rootOffset = a.TryGetProperty("anchor", out var an) && an.ValueKind == JsonValueKind.Object
            ? OptNum(an, "root_offset") ?? 0
            : 0;
        return new OrderActor(
            Str(a, "name"), Str(a, "role"), Str(a, "clip_role"), OptNum(a, "height_cm"), Point(start),
            Str(start, "room_id"), (int)(OptNum(start, "level") ?? 0), OptPoint(a, "access"), anchor, rootOffset,
            Str(a, "entry_mode"), steps, Bool(a, "reports_arrival"), OptPoint(a, "stand"));
    }

    private static OrderPoint Point(JsonElement p)
    {
        if (p.ValueKind != JsonValueKind.Object)
            throw new BadOrder();
        return new OrderPoint(Num(p, "x"), Num(p, "y"), Num(p, "z"), OptNum(p, "yaw") ?? 0);
    }

    private static OrderPoint? OptPoint(JsonElement e, string name)
        => e.TryGetProperty(name, out var p) && p.ValueKind != JsonValueKind.Null ? Point(p) : null;

    /// <summary>Hint route points: <c>[x, z]</c>, <c>[x, y, z]</c> or <c>{x, z}</c>.</summary>
    private static IReadOnlyList<P2> Route(JsonElement e)
    {
        var route = new List<P2>();
        if (!e.TryGetProperty("hint_route", out var r) || r.ValueKind == JsonValueKind.Null)
            return route;
        if (r.ValueKind != JsonValueKind.Array)
            throw new BadOrder();
        foreach (var p in r.EnumerateArray())
        {
            if (p.ValueKind == JsonValueKind.Object)
            {
                route.Add(new P2(Num(p, "x"), Num(p, "z")));
                continue;
            }
            if (p.ValueKind != JsonValueKind.Array)
                throw new BadOrder();
            int n = p.GetArrayLength();
            if (n != 2 && n != 3)
                throw new BadOrder();
            route.Add(new P2(Finite(p[0]), Finite(p[n - 1])));
        }
        return route;
    }

    private static double Finite(JsonElement v)
    {
        if (v.ValueKind != JsonValueKind.Number || !v.TryGetDouble(out double d) || !double.IsFinite(d))
            throw new BadOrder();
        return d;
    }

    private static double Num(JsonElement e, string name)
        => OptNum(e, name) ?? throw new BadOrder();

    private static double? OptNum(JsonElement e, string name)
        => e.TryGetProperty(name, out var v) && v.ValueKind != JsonValueKind.Null ? Finite(v) : null;

    private static string Str(JsonElement e, string name)
    {
        if (!e.TryGetProperty(name, out var v) || v.ValueKind == JsonValueKind.Null)
            return "";
        if (v.ValueKind != JsonValueKind.String)
            throw new BadOrder();
        return v.GetString() ?? "";
    }

    private static bool Bool(JsonElement e, string name)
    {
        if (!e.TryGetProperty(name, out var v) || v.ValueKind == JsonValueKind.Null)
            return false;
        return v.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => throw new BadOrder(),
        };
    }
}
