using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Scene;
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
///   nightFactorAt    Ambience.NightFactorAt   (cross-reference with ambience.json)
/// </code>
/// </summary>
public class SkyLightVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("sky_light"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = WithValues(new()
    {
        ["nightFactorAt"] = a => Ambience.NightFactorAt(Num(Arity(a, 1, 1)[0])),
    });

    public static TheoryData<string> Cases => DispatchedLabels("sky_light", Dispatch);

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>The fns native has not ported yet — the next commit ports them; nothing is skipped silently.</summary>
    [Fact]
    public void PendingFunctions() => AssertPending(File.Value, Dispatch,
        "shadowTexelM", "lightBasisValue", "gameHourLights", "fogFactor", "lightBasis", "snapShadowCentre");
}
