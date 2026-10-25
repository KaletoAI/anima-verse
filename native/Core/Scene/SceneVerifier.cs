using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>
/// One location's § B5a result — the native twin of the browser's <c>VerifyReport</c>
/// (client3d/src/scene/sceneRecipe.ts, dropped into <c>window.__sceneVerify[loc]</c>): how many numbers were
/// checked, the rows beyond <see cref="SceneVerify.Eps"/>, the model specs that did not load, and the
/// placed/total model count.
/// </summary>
public sealed record VerifyReport(string Location, int Checked, IReadOnlyList<VerifyRow> Rows, int Skipped,
                                  int Placed, int Total)
{
    public bool Clean => Rows.Count == 0;

    private string ModelInfo => $"models {Placed}/{Total}";

    /// <summary>The browser's console line (<c>Verifier.report</c>), in English.</summary>
    public string Headline() => Rows.Count > 0
        ? $"[verify] {Location}: {Rows.Count} deviation(s) in {Checked} checked numbers ({ModelInfo}, {Skipped} skipped), "
          + $"tolerance {Fmt(SceneVerify.Eps)} m"
        : $"[verify] {Location}: {Checked} numbers checked, no deviation > {Fmt(SceneVerify.Eps)} m ({ModelInfo})";

    /// <summary>The <c>console.table(rows)</c> twin: a header and one aligned line per row (none when clean).</summary>
    public IReadOnlyList<string> Table()
    {
        if (Rows.Count == 0) return Array.Empty<string>();
        var cells = new List<string[]> { new[] { "object", "field", "actual", "target", "delta" } };
        cells.AddRange(Rows.Select(r => new[] { r.Object, r.Field, Fmt(r.Actual), Fmt(r.Target), Fmt(r.Delta) }));
        var widths = Enumerable.Range(0, 5).Select(c => cells.Max(row => row[c].Length)).ToArray();
        return cells.Select(row => "  " + string.Join("  ", row.Select((v, c) => c < 2 ? v.PadRight(widths[c]) : v.PadLeft(widths[c])))
                                                 .TrimEnd()).ToList();
    }

    /// <summary>JS number printing for the table (0.123, -0.05, 12) — invariant, shortest round trip.</summary>
    public static string Fmt(double v) => v.ToString("R", CultureInfo.InvariantCulture);
}

/// <summary>
/// The accumulating side of the browser's <c>SpecVerifier</c> + <c>Verifier</c> (packages/scene-render/src/verify.ts,
/// client3d/src/scene/sceneRecipe.ts): it feeds every measurement through the vector-checked cores
/// (<see cref="SceneVerify.PrimitiveRows"/>, <see cref="SceneVerify.PlacementRows"/>) and keeps the counts. The
/// measuring itself (which box, which frame) is the renderer's; this class only diffs.
/// </summary>
public sealed class SceneVerifier
{
    private readonly List<VerifyRow> _rows = new();

    public int Checked { get; private set; }
    public int Skipped { get; private set; }
    public int Placed { get; set; }
    public int Total { get; set; }
    public IReadOnlyList<VerifyRow> Rows => _rows;

    /// <summary><c>SpecVerifier.check</c>: one number against its target.</summary>
    public void Check(string obj, string field, double actual, double target) => Add(SceneVerify.PrimitiveRows(obj, new[]
    {
        new VerifyMeasurement(field, actual, target),
    }));

    public void Add(VerifyResult result)
    {
        Checked += result.Checked;
        _rows.AddRange(result.Rows);
    }

    /// <summary>
    /// <c>SpecVerifier.primitive</c>: the measured WORLD box of a plate or wall, taken into the tile frame
    /// (<paramref name="origin"/> = the tile centre, <paramref name="frameYaw"/> = its footprint yaw) and diffed
    /// against the targets of <see cref="SceneVerify.PlateTargets"/> / <see cref="SceneVerify.WallTargets"/>.
    /// </summary>
    public void Primitive(string name, VBox world, Vec3 origin, double frameYaw, IEnumerable<PrimitiveTarget> targets)
    {
        var box = SceneVerify.InFrame(world, origin, frameYaw);
        Add(SceneVerify.PrimitiveRows(name, targets.Select(t => new VerifyMeasurement(t.Field, t.Actual(box), t.Target)).ToList()));
    }

    /// <summary><c>SpecVerifier.placement</c>: a placed model (or its placeholder) against its spec.</summary>
    public void Placement(VBox world, Vec3 position, SceneModelSpec spec, Vec3 origin, double frameYaw, double groundLift)
        => Add(SceneVerify.PlacementRows(world, position, spec, origin, frameYaw, groundLift));

    /// <summary>
    /// <c>Verifier.skip</c>: a spec that placed nothing (no mesh, no placeholder) is a MISSING object and goes into
    /// the table as a deviation — field <c>geladen</c> ("loaded"), 0 instead of 1, the browser's literal field name so
    /// the rows of both clients compare one to one.
    /// </summary>
    public void Skip(SceneModelSpec spec)
    {
        Skipped++;
        Check($"{spec.Role}:{spec.Id}", "geladen", 0, 1);
    }

    public VerifyReport Report(string location) => new(location, Checked, _rows.ToList(), Skipped, Placed, Total);

    /// <summary><c>surface_box</c>: the worst of the three size differences and the bottom edge (fix wave B).</summary>
    public static double SurfaceBoxDeviation(VBox fixBox, SceneSurface s)
        => Math.Max(Math.Max(Math.Abs(fixBox.Max.X - fixBox.Min.X - (s.BoxMax.X - s.BoxMin.X)),
                             Math.Abs(fixBox.Max.Y - fixBox.Min.Y - (s.BoxMax.Y - s.BoxMin.Y))),
                    Math.Max(Math.Abs(fixBox.Max.Z - fixBox.Min.Z - (s.BoxMax.Z - s.BoxMin.Z)),
                             Math.Abs(fixBox.Min.Y - s.BoxMin.Y)));

    /// <summary>The verify object name of a plate: <c>plate:&lt;room|level&gt;@&lt;level&gt;</c>.</summary>
    public static string PlateName(ScenePlate p) => $"plate:{(p.RoomId.Length > 0 ? p.RoomId : "level")}@{p.Level}";

    /// <summary>The verify object name of a wall: <c>wall:&lt;room|contour&gt;@&lt;level&gt;</c>.</summary>
    public static string WallName(SceneWall w) => $"wall:{(w.RoomId.Length > 0 ? w.RoomId : "contour")}@{w.Level}";
}
