using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Scene;
using AnimaNative.Sky;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.E3VectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/sky_light.json against the native light math (hand derivations:
/// client3d/scripts/smoke_shadow_snap.mjs; TS sources client3d/src/scene/skyLight.ts, fogConstants.ts, shadowSnap.ts,
/// ambience.ts).
///
/// <code>
///   TS fn            C#                       shape translation
///   gameHourLights   SkyLight.GameHourLights  colours stay LINEAR in C#; the adapter packs them as sRGB ints (three getHex)
///   nightFactorAt    Ambience.NightFactorAt   (cross-reference with ambience.json)
///   fogFactor        Fog.Factor
///   shadowTexelM     ShadowSnap.TexelM
///   lightBasis       ShadowSnap.Basis         [x, y, z] ↔ (X, Y, Z)
///   snapShadowCentre ShadowSnap.SnapCentre    {target, offset, halfM?, mapPx?}
/// </code>
/// </summary>
public class SkyLightVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("sky_light"));

    private static (double X, double Y, double Z) V(JsonNode? n)
    {
        var v = VectorCompare.NumList(n);
        return v.Count == 3 ? (v[0], v[1], v[2]) : throw new ArgumentException($"expected [x, y, z], got {VectorCompare.Show(n)}");
    }

    private static JsonArray Arr((double X, double Y, double Z) v) => new(v.X, v.Y, v.Z);

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = WithValues(new()
    {
        ["nightFactorAt"] = a => Ambience.NightFactorAt(Num(Arity(a, 1, 1)[0])),
        ["gameHourLights"] = a =>
        {
            var l = SkyLight.GameHourLights(Num(Arity(a, 1, 1)[0]));
            return new JsonObject
            {
                ["sunAngle"] = l.SunAngle, ["sun"] = l.Sun.ToSrgbHex(), ["sky"] = l.Sky.ToSrgbHex(),
                ["sunIntensity"] = l.SunIntensity, ["hemiIntensity"] = l.HemiIntensity, ["fillIntensity"] = l.FillIntensity,
            };
        },
        ["fogFactor"] = a => Fog.Factor(Num(Arity(a, 1, 1)[0])),
        ["shadowTexelM"] = a =>
        {
            Arity(a, 0, 2);
            return ShadowSnap.TexelM(Arg(a, 0) is { } h ? Num(h) : ShadowSnap.HalfM, Arg(a, 1) is { } m ? Num(m) : ShadowSnap.MapPx);
        },
        ["lightBasis"] = a =>
        {
            var b = ShadowSnap.Basis(V(Arity(a, 1, 1)[0]));
            return new JsonObject { ["x"] = Arr(b.X), ["y"] = Arr(b.Y), ["z"] = Arr(b.Z) };
        },
        ["snapShadowCentre"] = a =>
        {
            var o = Arity(a, 1, 1)[0];
            var c = ShadowSnap.SnapCentre(V(Key(o, "target")), V(Key(o, "offset")),
                                          Key(o, "halfM") is { } h ? Num(h) : ShadowSnap.HalfM,
                                          Key(o, "mapPx") is { } m ? Num(m) : ShadowSnap.MapPx);
            return Arr(c);
        },
    });

    public static TheoryData<string> Cases => VectorFile.Labels("sky_light");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>Every fn of the file has a C# port in the table.</summary>
    [Fact]
    public void EveryFunctionDispatched() => AssertAllDispatched(File.Value, Dispatch);
}
