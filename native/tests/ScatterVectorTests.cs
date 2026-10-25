using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/scatter.json against the C# ports <see cref="ScatterMath"/> and
/// <see cref="ScatterLod"/> (hand derivations: client3d/scripts/smoke_scatter_math.mjs; TS sources:
/// packages/scene-render/src/scatter.ts and client3d/src/scene/scatterLod.ts). The shape adapters
/// and the "not given" / <c>rng</c> conventions are in <see cref="ScatterVectorAdapters"/>.
///
/// <code>
///   TS fn                  C#                                   shape translation
///   propGroundFit          ScatterMath.GroundFit                tuple → {scale, offsetY}
///   pointInRing            ScatterMath.PointInRing
///   pointInFootprint       ScatterMath.PointInFootprint         {points} → points
///   footprintDistance      ScatterMath.FootprintDistance        {points} → points
///   footprintBlocks        ScatterMath.FootprintBlocks          {points} → points
///   scatterClearM          ScatterMath.ClearM
///   propBoxFootprint       ScatterMath.PropBoxFootprint         {x,z,yaw_deg,half_w,half_d} → 5 numbers; → {points} | null
///   scatterWantedCount     ScatterMath.WantedCount
///   scatterInstances       ScatterMath.Instances                options object → SampleOptions; → [{x,z,yaw,variant?}]
///   scatterCellInstances   ScatterMath.CellInstances            options object → CellOptions; → [{x,z,yaw,variant?}]
///   scatterSeed            ScatterMath.Seed
///   scatterCellSeed        ScatterMath.CellSeed
///   reshuffleEpoch         ScatterMath.ReshuffleEpoch           double? → number | null
///   scatterSeedHash        ScatterMath.SeedHash                 uint → number
///   scatterVariantIndex    ScatterMath.VariantIndex
///   scatterYaw             ScatterMath.Yaw
///   scatterCellAt          ScatterMath.CellAt
///   scatterCellRing        ScatterMath.CellRing                 P2[] → [[x, z], …]
///   scatterCellSpan        ScatterMath.CellSpan
///   scatterTargetH         ScatterLod.TargetH
///   scatterSway            ScatterLod.Sway
///   scatterGroundOffset    ScatterLod.GroundOffset
///   instanceTier           ScatterLod.InstanceTier              {nearM,farM,cullM} → ScatterLodCfg; byte tier
///   instanceShare          ScatterLod.InstanceShare             {nearM,farM,cullM} → ScatterLodCfg
///   instanceVisible        ScatterLod.InstanceVisible           {nearM,farM,cullM} → ScatterLodCfg
///   horizontalFovRad       ScatterLod.HorizontalFovRad
///   viewCone               ScatterLod.ViewCone                  ScatterViewCone → {fwdX, fwdZ, cosHalf}
///   inViewCone             ScatterLod.InViewCone
/// </code>
///
/// Ported but without a case in the file (see the smoke's header): PinnedVariant (reached through
/// the samplers' <c>variant</c> option), SeedEpochSuffix (through the seeds' epoch), OccupyR,
/// InstanceHash (through InstanceVisible), SeededRandom, WantedCells and the Ug* undergrowth functions.
/// </summary>
public class ScatterVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("scatter"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        // ---- scatter.ts: grounding, rings, footprints ----
        ["propGroundFit"] = a => GroundFitJson(ScatterMath.GroundFit(
            VectorCompare.Num(Arity(a, 2, 3)[0]), VectorCompare.Num(a[1]), VectorCompare.NumOrNull(Arg(a, 2)))),
        ["pointInRing"] = a => JsonValue.Create(ScatterMath.PointInRing(
            VectorCompare.Num(Arity(a, 3, 3)[0]), VectorCompare.Num(a[1]), RingOrNull(a[2]))),
        ["pointInFootprint"] = a => JsonValue.Create(ScatterMath.PointInFootprint(
            Footprint(Arity(a, 3, 3)[0]), VectorCompare.Num(a[1]), VectorCompare.Num(a[2]))),
        ["footprintDistance"] = a => JsonValue.Create(ScatterMath.FootprintDistance(
            Footprint(Arity(a, 3, 3)[0]), VectorCompare.Num(a[1]), VectorCompare.Num(a[2]))),
        ["footprintBlocks"] = a => JsonValue.Create(ScatterMath.FootprintBlocks(
            Footprint(Arity(a, 3, 4)[0])!, VectorCompare.Num(a[1]), VectorCompare.Num(a[2]), VectorCompare.NumOrNull(Arg(a, 3)))),
        ["scatterClearM"] = a => JsonValue.Create(ScatterMath.ClearM(
            VectorCompare.Num(Arity(a, 1, 2)[0]), VectorCompare.NumOrNull(Arg(a, 1)))),
        ["propBoxFootprint"] = a => PropBoxFootprint(Arity(a, 1, 1)[0]),

        // ---- scatter.ts: the samplers ----
        ["scatterWantedCount"] = a => JsonValue.Create(ScatterMath.WantedCount(
            VectorCompare.Num(Arity(a, 2, 3)[0]), VectorCompare.Num(a[1]), IntOrNull(Arg(a, 2)))),
        ["scatterInstances"] = a => InstancesJson(ScatterMath.Instances(SampleOptions(Arity(a, 1, 1)[0]))),
        ["scatterCellInstances"] = a => InstancesJson(ScatterMath.CellInstances(CellOptions(Arity(a, 1, 1)[0]))),

        // ---- scatter.ts: seeds, variants, yaw ----
        ["scatterSeed"] = a => JsonValue.Create(ScatterMath.Seed(
            Str(Arity(a, 2, 3)[0]), Int(a[1]), VectorCompare.NumOrNull(Arg(a, 2)))),
        ["scatterCellSeed"] = a => JsonValue.Create(ScatterMath.CellSeed(
            Str(Arity(a, 4, 5)[0]), Int(a[1]), Int(a[2]), Int(a[3]), VectorCompare.NumOrNull(Arg(a, 4)))),
        ["reshuffleEpoch"] = a => JsonValue.Create(ScatterMath.ReshuffleEpoch(
            VectorCompare.Num(Arity(a, 1, 2)[0]), VectorCompare.NumOrNull(Arg(a, 1)))),
        ["scatterSeedHash"] = a => JsonValue.Create(ScatterMath.SeedHash(Str(Arity(a, 1, 1)[0]))),
        ["scatterVariantIndex"] = a => JsonValue.Create(ScatterMath.VariantIndex(
            Str(Arity(a, 3, 3)[0]), VectorCompare.Num(a[1]), NumOrNaN(a[2]))),
        ["scatterYaw"] = a =>
        {
            Arity(a, 1, 4);
            double r = VectorCompare.Num(a[0]);
            string? mode = StrOrNull(Arg(a, 1));
            double? deg = VectorCompare.NumOrNull(Arg(a, 2));
            // axisRad: TS default parameter 0; not given → the C# default (also 0).
            var axis = Arg(a, 3);
            return JsonValue.Create(axis is null
                ? ScatterMath.Yaw(r, mode, deg)
                : ScatterMath.Yaw(r, mode, deg, VectorCompare.Num(axis)));
        },

        // ---- scatter.ts: the cell raster ----
        ["scatterCellAt"] = a => JsonValue.Create(ScatterMath.CellAt(VectorCompare.Num(Arity(a, 1, 1)[0]))),
        ["scatterCellRing"] = a => PointsJson(ScatterMath.CellRing(Int(Arity(a, 2, 2)[0]), Int(a[1]))),
        ["scatterCellSpan"] = a => JsonValue.Create(ScatterMath.CellSpan(VectorCompare.Num(Arity(a, 1, 1)[0]))),

        // ---- scatterLod.ts ----
        ["scatterTargetH"] = a => JsonValue.Create(ScatterLod.TargetH(VectorCompare.NumOrNull(Arg(Arity(a, 0, 1), 0)))),
        ["scatterSway"] = a => JsonValue.Create(ScatterLod.Sway(
            VectorCompare.Num(Arity(a, 1, 2)[0]), VectorCompare.NumOrNull(Arg(a, 1)))),
        ["scatterGroundOffset"] = a => JsonValue.Create(ScatterLod.GroundOffset(VectorCompare.NumOrNull(Arg(Arity(a, 0, 1), 0)))),
        ["instanceTier"] = a => JsonValue.Create((int)ScatterLod.InstanceTier(
            VectorCompare.Num(Arity(a, 3, 3)[0]), Tier(a[1]), Cfg(a[2]))),
        ["instanceShare"] = a => JsonValue.Create(ScatterLod.InstanceShare(VectorCompare.Num(Arity(a, 2, 2)[0]), Cfg(a[1]))),
        ["instanceVisible"] = a => JsonValue.Create(ScatterLod.InstanceVisible(
            Int(Arity(a, 3, 3)[0]), VectorCompare.Num(a[1]), Cfg(a[2]))),
        ["horizontalFovRad"] = a => JsonValue.Create(ScatterLod.HorizontalFovRad(
            VectorCompare.Num(Arity(a, 2, 2)[0]), VectorCompare.Num(a[1]))),
        ["viewCone"] = a => ViewConeJson(ScatterLod.ViewCone(
            VectorCompare.Num(Arity(a, 3, 3)[0]), VectorCompare.Num(a[1]), VectorCompare.Num(a[2]))),
        ["inViewCone"] = a => JsonValue.Create(ScatterLod.InViewCone(
            VectorCompare.Num(Arity(a, 5, 5)[0]), VectorCompare.Num(a[1]), VectorCompare.Num(a[2]),
            VectorCompare.Num(a[3]), VectorCompare.Num(a[4]))),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("scatter");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched()
        => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    /// <summary>
    /// The <c>rng</c> convention bites: the SPACE stream one number short makes the sampler draw
    /// past the end, and that throws instead of wrapping or reseeding.
    /// </summary>
    [Fact]
    public void ShortRngStreamThrows()
    {
        var c = File.Value.Case("[S1] without a spacing all five candidates stand");
        var args = File.Value.ResolveArgs(c);
        var rng = args[0]!["rng"]!.AsArray();
        rng.RemoveAt(rng.Count - 1);
        Assert.Throws<InvalidOperationException>(() => Dispatch[c.Fn](args));
    }
}
