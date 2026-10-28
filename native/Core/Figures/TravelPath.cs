using System;
using System.Collections.Generic;
using System.Buffers;
using System.Linq;
using System.Text.Json;
using AnimaNative.World;

namespace AnimaNative.Figures;

/// <summary>Task 42 / A11: map clock age at the server's unrounded travel instant, in milliseconds.</summary>
public readonly record struct TravelSync(double ClockAgeMs, double BuildMs)
{
    public static TravelSync Parse(JsonElement root)
        => root.TryGetProperty("sync", out var s) && s.ValueKind == JsonValueKind.Object
            ? new(Json.Num(s, "clock_age_ms"), Json.Num(s, "build_ms")) : default;
}

/// <summary>Task 42: monotonic request, headers and completed-parse timestamps, all in milliseconds.</summary>
public readonly record struct MapReceipt(double PolledAt, double HeadersAt, double ParsedAt)
{
    private const string Field = "_nativeReceipt";
    /// <summary>
    /// Task 42: client-only metadata travels with the JSON root because bootstrap and poll dispatch clone it before
    /// FigureManager sees it. An object-identity table would lose the stamps there. No server fields are changed;
    /// this private field is never sent to the server. The original receipt measures the HTTP parse, before copying.
    /// </summary>
    public JsonDocument Attach(JsonElement root)
    {
        var buffer = new ArrayBufferWriter<byte>();
        using (var w = new Utf8JsonWriter(buffer))
        {
            w.WriteStartObject();
            foreach (var p in root.EnumerateObject()) if (p.Name != Field) p.WriteTo(w);
            w.WriteStartObject(Field);
            w.WriteNumber("polledAt", PolledAt); w.WriteNumber("headersAt", HeadersAt); w.WriteNumber("parsedAt", ParsedAt);
            w.WriteEndObject(); w.WriteEndObject();
        }
        return JsonDocument.Parse(buffer.WrittenMemory);
    }
    public static MapReceipt? FromMap(JsonElement root)
        => root.TryGetProperty(Field, out var m) && m.ValueKind == JsonValueKind.Object
            ? new MapReceipt(Json.Num(m, "polledAt"), Json.Num(m, "headersAt"), Json.Num(m, "parsedAt")) : null;
}

/// <summary>
/// Task 42 / E6-T2: import-free travelPath.ts arithmetic, in world metres on XZ pairs. Heights belong to the reached
/// ground, never this polyline. Null paces hold progress; null entries cross timeless legs. travel.json is the oracle.
/// </summary>
public static class TravelPath
{
    public const double TrimBucketM = 5, LineSpacingM = 4, TravelTauS = 1;
    public const int LineMaxPoints = 400;
    private static bool Positive(double v) => double.IsFinite(v) && v > 0;
    private static double SegLength((double X, double Z) a, (double X, double Z) b)
    {
        double x = b.X - a.X, z = b.Z - a.Z, l = Math.Sqrt(x * x + z * z);
        return double.IsFinite(l) ? l : 0;
    }
    public static double PolylineLength(IReadOnlyList<(double X, double Z)>? points)
    {
        double total = 0;
        if (points is not null) for (int i = 0; i + 1 < points.Count; i++) total += SegLength(points[i], points[i + 1]);
        return total;
    }
    public static double ClampProgress(double value, double totalM)
    {
        double total = Positive(totalM) ? totalM : 0;
        return double.IsNaN(value) ? 0 : value < 0 ? 0 : value > total ? total : value;
    }
    public static (double X, double Z)? PointAtDistance(IReadOnlyList<(double X, double Z)>? points, double d)
    {
        if (points is null || points.Count == 0) return null;
        double rest = ClampProgress(d, PolylineLength(points));
        for (int i = 0; i + 1 < points.Count; i++)
        {
            var a = points[i]; var b = points[i + 1]; double l = SegLength(a, b);
            if (l <= 0) continue;
            if (rest <= l) return (a.X + (b.X - a.X) * (rest / l), a.Z + (b.Z - a.Z) * (rest / l));
            rest -= l;
        }
        return points[^1];
    }
    public static double TrimBucket(double progressM) => Positive(progressM) ? Math.Floor(progressM / TrimBucketM) : 0;
    public static List<(double X, double Z)> RemainingPoints(IReadOnlyList<(double X, double Z)>? points, double progressM)
    {
        if (points is null || points.Count == 0) return new();
        double rest = ClampProgress(progressM, PolylineLength(points));
        for (int i = 0; i + 1 < points.Count; i++)
        {
            var a = points[i]; var b = points[i + 1]; double l = SegLength(a, b);
            if (l <= 0) continue;
            if (rest <= l)
            {
                var result = new List<(double, double)> { (a.X + (b.X - a.X) * (rest / l), a.Z + (b.Z - a.Z) * (rest / l)) };
                result.AddRange(points.Skip(rest >= l ? i + 2 : i + 1));
                return result;
            }
            rest -= l;
        }
        return new() { points[^1] };
    }
    public static List<(double X, double Z)> DensifyPolyline(IReadOnlyList<(double X, double Z)>? points,
        double spacingM = LineSpacingM, double maxPoints = LineMaxPoints)
    {
        double total = PolylineLength(points);
        if (points is null) return new();
        if (points.Count < 2 || !Positive(spacingM) || total <= 0) return points.ToList();
        double cap = double.IsFinite(maxPoints) && maxPoints > points.Count ? maxPoints : points.Count;
        double spacing = Math.Max(spacingM, total / (cap - 1));
        var result = new List<(double, double)> { points[0] };
        for (int i = 0; i + 1 < points.Count; i++)
        {
            var a = points[i]; var b = points[i + 1]; double l = SegLength(a, b);
            double pieces = l > spacing ? Math.Ceiling(l / spacing) : 1;
            for (int k = 1; k < pieces; k++) result.Add((a.X + (b.X - a.X) * (k / pieces), a.Z + (b.Z - a.Z) * (k / pieces)));
            result.Add(b);
        }
        return result;
    }
    public static double CatchUpStep(double distanceM, double? rateMS, double dt, double walkSpeedMS)
        => !Positive(distanceM) || !Positive(dt) ? 0 : Math.Min(distanceM, Math.Max(Positive(walkSpeedMS) ? walkSpeedMS : 0,
            rateMS is { } rate && Positive(rate) ? rate : 0) * dt);
    public static double? DeadReckonRate((double X, double Z)? prev, double prevAtS, (double X, double Z)? cur, double atS)
    {
        if (prev is not { } p || cur is not { } c || !new[] { p.X, p.Z, c.X, c.Z, prevAtS, atS }.All(double.IsFinite) || atS - prevAtS <= 0) return null;
        double rate = SegLength(p, c) / (atS - prevAtS);
        return double.IsFinite(rate) ? rate : null;
    }
    public static double DeadReckonStep(double? rateMS, double? pace, double dt, double remainingM)
        => rateMS is not { } rate || !Positive(rate) || !Positive(dt) || !Positive(remainingM) ? 0
            : Math.Min(remainingM, rate * (pace is { } p && Positive(p) ? p : 1) * dt);
    public static double AdvanceAlongPaces(IReadOnlyList<(double X, double Z)>? points, IReadOnlyList<double?>? paces, double fromM, double dtS)
    {
        double total = PolylineLength(points), m = ClampProgress(fromM, total);
        if (paces is null || points is null) return m;
        double left = Positive(dtS) ? dtS : 0, acc = 0;
        for (int i = 0; i + 1 < points.Count; i++)
        {
            double l = SegLength(points[i], points[i + 1]), end = acc + l; acc = end;
            if (m >= end && l > 0) continue;
            double? pace = i < paces.Count ? paces[i] : null;
            if (l <= 0 || pace is null) { m = Math.Max(m, end); continue; }
            if (!Positive(pace.Value) || left <= 0) break;
            double need = (end - m) / pace.Value;
            if (need <= left) { left -= need; m = end; continue; }
            m += pace.Value * left; break;
        }
        return ClampProgress(m, total);
    }
    public static double AgeAtReceiptS(TravelSync sync, MapReceipt meta)
        => (sync.ClockAgeMs + Math.Max(0, meta.HeadersAt - meta.PolledAt - sync.BuildMs) / 2 + meta.ParsedAt - meta.HeadersAt) / 1000;
    public static double StepShown(IReadOnlyList<(double X, double Z)>? points, IReadOnlyList<double?>? paces,
        double shownM, double targetM, double dt, double tau = TravelTauS)
    {
        double target2 = AdvanceAlongPaces(points, paces, targetM, dt), pred = AdvanceAlongPaces(points, paces, shownM, dt);
        double k = dt > 0 ? 1 - Math.Exp(-dt / tau) : 0;
        return ClampProgress(shownM + Math.Max(0, pred - shownM + (target2 - pred) * k), PolylineLength(points));
    }
    public static double? RateAt(IReadOnlyList<(double X, double Z)>? points, IReadOnlyList<double?>? paces, double m)
    {
        if (paces is null || paces.Count == 0) return null;
        double acc = 0;
        if (points is not null) for (int i = 0; i + 1 < points.Count; i++)
        {
            acc += SegLength(points[i], points[i + 1]);
            if (m < acc) return i < paces.Count ? paces[i] : null;
        }
        return paces[^1];
    }
    public static double HardSnapM(double? rate) => Math.Max(6, rate is { } r && Positive(r) ? 2 * r : 0);
    public static (double ShownM, string Snap) AdoptTarget(double shownM, double targetM, double? rate)
        => Math.Abs(targetM - shownM) <= HardSnapM(rate) ? (shownM, "none") : (targetM, targetM < shownM ? "back" : "fwd");

    /// <summary>Task 42: browser monotonic deque; expiry is inclusive at 30,000 ms, on push AND read.</summary>
    public sealed class ErrWindow
    {
        private readonly LinkedList<(double T, double E)> _samples = new();
        private void Prune(double nowMs) { while (_samples.First is { } f && f.Value.T <= nowMs - 30000) _samples.RemoveFirst(); }
        public void Push(double nowMs, double errM)
        {
            while (_samples.Last is { } l && l.Value.E <= errM) _samples.RemoveLast();
            _samples.AddLast((nowMs, errM)); Prune(nowMs);
        }
        public double Max(double nowMs) { Prune(nowMs); return _samples.First?.Value.E ?? 0; }
    }
}
