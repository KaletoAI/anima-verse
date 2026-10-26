using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Ground;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.E3VectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/layer_ground.json against <see cref="LayerCut"/> and <see cref="NaturalGround"/> (hand
/// derivations: client3d/scripts/smoke_layer_cut.mjs; TS sources packages/scene-render/src/layerCut.ts,
/// client3d/src/scene/naturalGroundMath.ts).
///
/// <code>
///   TS fn            C#                          shape translation
///   layerWeight      LayerCut.Weight
///   decodeSd         LayerCut.DecodeSd
///   packLayerWindow  LayerCut.Pack               $map + format → LayerCut.ParseBatch (the payload parser); window ↔ object
///   layerSdBlockAt   LayerCut.SdBlockAt          $layerWindow → LayerCut.Pack
///   topLayerAt       LayerCut.TopLayerAt
///   lcPushedSd       LayerCut.PushedSd
///   ngTintFactors    NaturalGround.TintFactors   (b, s) ↔ {brightness, saturation}
///   ngAoShade        NaturalGround.AoShade
///   ngAoTaps         NaturalGround.AoTaps        [(dx, dz)] ↔ [[dx, dz]]
///   ngFieldUv        NaturalGround.FieldUv       {origin_x, origin_z, step_m, cols, rows} → HeightGrid
///   e3Constants      the C# constants under their TS names
/// </code>
/// </summary>
public class LayerGroundVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("layer_ground"));

    private static JsonNode? WindowJson(LayerMaskWindow? w) => w is null ? null : new JsonObject
    {
        ["originX"] = w.OriginX, ["originZ"] = w.OriginZ, ["idStep"] = w.IdStep, ["sdStep"] = w.SdStep,
        ["idSize"] = w.IdSize, ["sdSize"] = w.SdSize, ["id"] = Bytes(w.Id), ["sd"] = Bytes(w.Sd),
        ["sdZero"] = w.SdZero, ["sdCodesPerM"] = w.SdCodesPerM, ["sdBandM"] = w.SdBandM,
    };

    internal static readonly Dictionary<string, double> Constants = new()
    {
        ["LC_EDGE_NOISE_M"] = LayerCut.EdgeNoiseM, ["LC_EDGE_WAVE_M"] = LayerCut.EdgeWaveM,
        ["NG_DETAIL_SCALE"] = NaturalGround.DetailScale, ["NG_DETAIL_OFFSET"] = NaturalGround.DetailOffset,
        ["NG_MIX_M"] = NaturalGround.MixM, ["NG_MIX_MAX"] = NaturalGround.MixMax,
        ["NG_TINT_M"] = NaturalGround.TintM, ["NG_TINT_AMP"] = NaturalGround.TintAmp,
        ["NG_AO_RING_M"] = NaturalGround.AoRingM, ["NG_AO_SPAN_M"] = NaturalGround.AoSpanM,
        ["NG_AO_DOWN"] = NaturalGround.AoDown, ["NG_AO_UP"] = NaturalGround.AoUp,
    };

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["layerWeight"] = a => LayerCut.Weight(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["decodeSd"] = a => LayerCut.DecodeSd(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["packLayerWindow"] = a =>
        {
            var batch = LayerBatchOf(Arity(a, 2, 2)[0], a[1]);
            return WindowJson(LayerCut.Pack(batch.Tiles, batch.Format));
        },
        ["layerSdBlockAt"] = a => LayerCut.SdBlockAt(LayerWindow(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["topLayerAt"] = a => LayerCut.TopLayerAt(LayerWindow(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["lcPushedSd"] = a => LayerCut.PushedSd(Num(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), Num(a[3])),
        ["ngTintFactors"] = a =>
        {
            var (b, s) = NaturalGround.TintFactors(Num(Arity(a, 2, 2)[0]), Num(a[1]));
            return new JsonObject { ["brightness"] = b, ["saturation"] = s };
        },
        ["ngAoShade"] = a => NaturalGround.AoShade(Num(Arity(a, 2, 2)[0]), Num(a[1])),
        ["ngAoTaps"] = a =>
        {
            Arity(a, 0, 1);
            var taps = Arg(a, 0) is { } r ? NaturalGround.AoTaps(Num(r)) : NaturalGround.AoTaps();
            return new JsonArray(taps.Select(t => (JsonNode?)new JsonArray(t.Dx, t.Dz)).ToArray());
        },
        ["ngFieldUv"] = a =>
        {
            var f = Arity(a, 3, 3)[2];
            var grid = new HeightGrid(Num(Key(f, "origin_x")), Num(Key(f, "origin_z")), Num(Key(f, "step_m")),
                                      Int(Key(f, "rows")), Int(Key(f, "cols")), Array.Empty<float>());
            var (u, v, inside) = NaturalGround.FieldUv(Num(a[0]), Num(a[1]), grid);
            return new JsonObject { ["u"] = u, ["v"] = v, ["inside"] = inside };
        },
        ["e3Constants"] = a =>
        {
            Arity(a, 0, 0);
            var o = new JsonObject();
            foreach (var (k, v) in Constants) o[k] = v;
            return o;
        },
    };

    public static TheoryData<string> Cases => DispatchedLabels("layer_ground", Dispatch);

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>The fns native has not ported yet — the next commit ports them; nothing is skipped silently.</summary>
    [Fact]
    public void PendingFunctions() => AssertPending(File.Value, Dispatch, "ngDetailUv");
}
