using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/view_shift.json against the C# port <see cref="ViewShift.For"/>
/// (hand derivations: client3d/scripts/smoke_view_shift.mjs; TS source: client3d/src/scene/viewShift.ts).
///
/// <code>
///   TS fn          C#               shape translation
///   viewShiftFor   ViewShift.For    ScreenBox {x,y,w,h} | null → HudRect? ; ViewShift → {dx, dy}
/// </code>
///
/// The TS <c>ScreenBox</c> is the HUD's <c>HudRect</c> (both: CSS pixels from the top left), so the
/// port takes the <see cref="HudRect"/> the bridge already hands over (<c>setChatBox</c>).
/// </summary>
public class ViewShiftVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("view_shift"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["viewShiftFor"] = a =>
        {
            var s = ViewShift.For(VectorCompare.Num(Arity(a, 3, 3)[0]), VectorCompare.Num(a[1]), BoxOrNull(a[2]));
            return new JsonObject { ["dx"] = s.Dx, ["dy"] = s.Dy };
        },
    };

    private static HudRect? BoxOrNull(JsonNode? node)
    {
        if (node is null) return null;
        if (node is not JsonObject o || o.Count != 4)
            throw new ArgumentException($"expected a screen box {{x, y, w, h}}, got {VectorCompare.Show(node)}");
        return new HudRect(VectorCompare.Num(o["x"]), VectorCompare.Num(o["y"]), VectorCompare.Num(o["w"]), VectorCompare.Num(o["h"]));
    }

    public static TheoryData<string> Cases => VectorFile.Labels("view_shift");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched()
        => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void CapIsTheTsConstant() => Assert.Equal(0.35, ViewShift.MaxShiftFraction);
}
