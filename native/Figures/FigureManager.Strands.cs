using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// The per-strand hair's share of the manager (figures.ts <c>FigureLibrary.strandRecord</c> / <c>makeFigure</c>,
/// npcs.ts <c>tickStrandHair</c>): one record cache per manager, the source of a full-tier template, the per-frame
/// budget.
/// </summary>
public partial class FigureManager
{
    private StrandRecordCache? _strandRecords;
    private static readonly Stopwatch StrandClock = Stopwatch.StartNew();

    /// <summary>The strand records by sha256 (shared by every figure of a model, a tier swap back included).</summary>
    public StrandRecordCache StrandRecords
        => _strandRecords ??= new StrandRecordCache(url => _source.GetHairStrandRecordAsync(url), () => StrandClock.Elapsed.TotalMilliseconds, _log);

    /// <summary>api.ts: <c>m.hair_strands?.url &amp;&amp; m.hair_strands?.sha256 ? {url, sha256} : null</c>.</summary>
    private static (string Url, string Sha256)? StrandRefOf(JsonElement model)
    {
        if (model.ValueKind != JsonValueKind.Object || !model.TryGetProperty("hair_strands", out var h) || h.ValueKind != JsonValueKind.Object) return null;
        string Str(string k) => h.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString()! : "";
        string url = Str("url"), sha = Str("sha256");
        return url.Length > 0 && sha.Length > 0 ? (url, sha) : null;
    }

    /// <summary>The source of a body: full tier, <c>hair_strands</c> named, and a GLB primitive with strand attributes
    /// (a template without one cannot bind — its record is not even fetched).</summary>
    private StrandHairSource? StrandSourceFor(ModelTemplate t, ModelInfo info, FigureTier tier)
    {
        if (tier != FigureTier.Full || info.HairStrands is not { } hs || t.Strands.Count == 0) return null;
        return new StrandHairSource(t.Strands, () => StrandRecords.Get(hs.Url, hs.Sha256));
    }

    /// <summary>
    /// npcs.ts <c>tickStrandHair(cameraPos)</c>: a visible figure that is not the first-person body, within the leave
    /// distance and with a ready handle is a candidate (<see cref="StrandBudget.Candidates"/>: full tier); the budget
    /// (<see cref="StrandBudget.Pick"/>: 2 figures, 8 m in / 9 m out, 8 ms) picks; every other figure runs its chains.
    /// No camera: nobody runs strands. Returns the picked names.
    /// </summary>
    public HashSet<string> TickStrandHair(Vector3? camera) => TickStrandHair(_figures.Values, camera);

    /// <summary><see cref="TickStrandHair(Vector3?)"/> over any figures (the check drives it directly).</summary>
    public static HashSet<string> TickStrandHair(IEnumerable<Figure> figures, Vector3? camera)
    {
        var list = figures.Where(IsInstanceValid).ToList();
        if (camera is not { } cam)
        {
            foreach (var f in list) f.SetStrandHair(false);
            return new HashSet<string>();
        }
        var views = new List<(string Name, V3 Position, bool Full, bool HasRecord, bool FirstPerson, double CostMs, bool Running)>();
        foreach (var f in list)
        {
            var p = f.IsInsideTree() ? f.GlobalPosition : f.Position;
            bool near = p.DistanceTo(cam) <= StrandBudget.Limits.LeaveM;
            bool hasRecord = f.IsVisibleInTree() && !f.IsFirstPerson && near && f.PrepareStrandHair();
            views.Add((f.CharacterName, new V3(p.X, p.Y, p.Z), f.LoadedTier == FigureTier.Full, hasRecord, f.IsFirstPerson,
                       f.StrandCostMs, f.StrandRunning));
        }
        var picked = StrandBudget.Pick(StrandBudget.Candidates(views, new V3(cam.X, cam.Y, cam.Z)));
        foreach (var f in list) f.SetStrandHair(picked.Contains(f.CharacterName));
        return picked;
    }
}
