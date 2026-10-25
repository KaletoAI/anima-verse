using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>An axis-aligned box (three's <c>Box3</c>); empty when any max &lt; min.</summary>
public readonly record struct VBox(Vec3 Min, Vec3 Max)
{
    public bool IsEmpty => Max.X < Min.X || Max.Y < Min.Y || Max.Z < Min.Z;
}

/// <summary>One measured-against-target number of the verify run.</summary>
public sealed record VerifyRow(string Object, string Field, double Actual, double Target, double Delta);

/// <summary>A measurement to diff: field, measured value, target from the payload.</summary>
public readonly record struct VerifyMeasurement(string Field, double Actual, double Target);

/// <summary>How many numbers were checked and the rows beyond the tolerance.</summary>
public sealed record VerifyResult(int Checked, IReadOnlyList<VerifyRow> Rows);

/// <summary>One check target of a primitive: field, how to read it off the box, target.</summary>
public sealed record PrimitiveTarget(string Field, Func<VBox, double> Actual, double Target);

/// <summary>
/// The verify core of the contract (§ B5a) — arithmetic instead of screenshots — a port of
/// packages/scene-render/src/verify.ts (<c>inFrame</c>, <c>primitiveRows</c>, <c>placementRows</c>) and the
/// primitive targets of primitives.ts (<c>plateTargets</c>, <c>wallTargets</c>), checked against
/// shared/test-vectors/scene_verify.json.
/// </summary>
public static class SceneVerify
{
    /// <summary>Verify tolerance in world metres (§ B5a).</summary>
    public const double Eps = 0.01;

    private static double R3(double v) => Overview.JsSemantics.Round(v * 1000) / 1000;

    /// <summary>
    /// The measured WORLD box in the spec's frame: shifted by <paramref name="origin"/> and turned back by
    /// <paramref name="frameYaw"/>. Only the CENTRE is turned back; the half extents stay the world ones.
    /// </summary>
    public static VBox InFrame(VBox box, Vec3 origin, double frameYaw = 0)
    {
        var min = new Vec3(box.Min.X - origin.X, box.Min.Y - origin.Y, box.Min.Z - origin.Z);
        var max = new Vec3(box.Max.X - origin.X, box.Max.Y - origin.Y, box.Max.Z - origin.Z);
        if (frameYaw == 0 || double.IsNaN(frameYaw)) return new VBox(min, max);
        bool empty = max.X < min.X || max.Y < min.Y || max.Z < min.Z;
        double x = empty ? 0 : (min.X + max.X) / 2, y = empty ? 0 : (min.Y + max.Y) / 2, z = empty ? 0 : (min.Z + max.Z) / 2;
        double hx = empty ? 0 : (max.X - min.X) / 2, hy = empty ? 0 : (max.Y - min.Y) / 2, hz = empty ? 0 : (max.Z - min.Z) / 2;
        double lx = x * Math.Cos(frameYaw) - z * Math.Sin(frameYaw);
        double lz = x * Math.Sin(frameYaw) + z * Math.Cos(frameYaw);
        return new VBox(new Vec3(lx - hx, y - hy, lz - hz), new Vec3(lx + hx, y + hy, lz + hz));
    }

    /// <summary><c>primitiveRows</c>: every measurement counts; a row for each deviation beyond <see cref="Eps"/>, rounded to mm.</summary>
    public static VerifyResult PrimitiveRows(string obj, IReadOnlyList<VerifyMeasurement> measurements)
        => new(measurements.Count, measurements.Where(t => Math.Abs(t.Actual - t.Target) > Eps)
            .Select(t => new VerifyRow(obj, t.Field, R3(t.Actual), R3(t.Target), R3(t.Actual - t.Target))).ToList());

    private static bool Axis(double v)
    {
        if (double.IsNaN(v)) v = 0; // the TS default parameter (v = 0) for an absent angle
        return Math.Abs(((v % 90) + 90) % 90) <= 0.01;
    }

    /// <summary>
    /// <c>placementRows</c>: bottom, anchor (box centre for an axis-parallel non-fit placement, else the
    /// hanging point turned back), and the size ruler (<c>size_m</c> for fit, <c>max_m</c> otherwise) only where
    /// the angles keep the box axis-parallel.
    /// </summary>
    public static VerifyResult PlacementRows(VBox world, Vec3 position, SceneModelSpec spec, Vec3 origin,
                                             double frameYaw = 0, double groundLift = 0)
    {
        bool empty = world.IsEmpty;
        var size = empty ? new Vec3(0, 0, 0) : new Vec3(world.Max.X - world.Min.X, world.Max.Y - world.Min.Y, world.Max.Z - world.Min.Z);
        var box = InFrame(world, origin, frameYaw);
        var ms = new List<VerifyMeasurement>();
        void Add(string f, double a, double t) => ms.Add(new VerifyMeasurement(f, a, t));
        bool parallel = Axis(spec.YawDeg) && Axis(frameYaw * 180 / Math.PI);
        Add("bottom_y", box.Min.Y, spec.BottomY + groundLift);
        if (spec.Measure == "fit" || !parallel)
        {
            double x = position.X - origin.X, z = position.Z - origin.Z;
            Add("anchor.x", x * Math.Cos(frameYaw) - z * Math.Sin(frameYaw), spec.AnchorX);
            Add("anchor.z", x * Math.Sin(frameYaw) + z * Math.Cos(frameYaw), spec.AnchorZ);
        }
        else
        {
            bool boxEmpty = box.IsEmpty;
            Add("anchor.x", boxEmpty ? 0 : (box.Min.X + box.Max.X) / 2, spec.AnchorX);
            Add("anchor.z", boxEmpty ? 0 : (box.Min.Z + box.Max.Z) / 2, spec.AnchorZ);
        }
        if (spec.Measure == "fit")
        {
            if (spec.SizeM is { } s && parallel)
            {
                Add("size_m.w", Math.Max(size.X, size.Z), s.Length > 0 ? s[0] : double.NaN);
                Add("size_m.h", size.Y, s.Length > 1 ? s[1] : double.NaN);
            }
        }
        else if (parallel && Axis(spec.FixX) && Axis(spec.FixY) && Axis(spec.FixZ) && spec.MaxM != 0 && !double.IsNaN(spec.MaxM))
        {
            Add("max_m", spec.Measure == "xyz" ? Math.Max(size.X, Math.Max(size.Y, size.Z)) : Math.Max(size.X, size.Z), spec.MaxM);
        }
        return PrimitiveRows($"{spec.Role}:{spec.Id}", ms);
    }

    /// <summary><c>plateTargets</c>: the top edge on <c>top_y</c>, and for a body the bottom one thickness below.</summary>
    public static List<PrimitiveTarget> PlateTargets(ScenePlate plate)
    {
        var t = new List<PrimitiveTarget> { new("top_y", b => b.Max.Y, plate.TopY) };
        if (plate.Thickness > 0) t.Add(new PrimitiveTarget("bottom_y", b => b.Min.Y, plate.TopY - plate.Thickness));
        return t;
    }

    /// <summary><c>wallTargets</c>: foot and top from <c>base_y</c>/<c>height</c>, centre from the from/to midpoint.</summary>
    public static List<PrimitiveTarget> WallTargets(SceneWall wall) => new()
    {
        new("base_y", b => b.Min.Y, wall.BaseY),
        new("top_y", b => b.Max.Y, wall.BaseY + wall.Height),
        new("centre.x", b => (b.Min.X + b.Max.X) / 2, (wall.From.X + wall.To.X) / 2),
        new("centre.z", b => (b.Min.Z + b.Max.Z) / 2, (wall.From.Z + wall.To.Z) / 2),
    };
}
