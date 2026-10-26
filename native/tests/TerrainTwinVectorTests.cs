using System;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Terrain;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.E3VectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// The vertex stage's GPU-free twin (<see cref="TerrainShaderTwin"/>, the statement-for-statement copy of
/// <see cref="TerrainLodGlsl"/>) against the <c>lodVertex</c> cases of shared/test-vectors/terrain_lod.json — the
/// browser's CPU twin of the same GLSL (hand derivations: client3d/scripts/smoke_terrain_lod.mjs). The case's pyramids
/// become the uniforms the client would upload (geometry, level rows, the near rectangle; no frame = the shader's
/// ±1e6 default; no water, no cap), so the shader's own arithmetic answers the vectors, not only the C# port.
/// </summary>
public class TerrainTwinVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("terrain_lod"));

    public static TheoryData<string> Cases
    {
        get
        {
            var data = new TheoryData<string>();
            foreach (var c in VectorFile.Load("terrain_lod").Cases.Where(c => c.Fn == "lodVertex")) data.Add(c.Label);
            return data;
        }
    }

    private static HeightPyramid? Pyramid(JsonNode? node)
    {
        if (node is null) return null;
        var p = (JsonArray)Key(node, "$pyramid")!;
        return TerrainLod.BuildPyramid(Sampler(p[0]), Num(p[1]), Num(p[2]), Num(p[3]), Num(p[4]), Num(p[5]), Int(p[6]));
    }

    private static double[] Geom(HeightPyramid? p) => p is null ? new double[] { 0, 0, 1, 0 } : new[] { p.OriginX, p.OriginZ, p.Step, p.Levels.Count };

    private static double[][] Levels(HeightPyramid? p)
        => Enumerable.Range(0, TerrainLod.MaxLodLevels)
                     .Select(i => p is not null && i < p.Levels.Count
                         ? new double[] { p.Levels[i].Cols, p.Levels[i].Rows, p.Levels[i].Step, p.Levels[i].Row0 }
                         : new double[4]).ToArray();

    private static TwinTexture? Tex(HeightPyramid? p) => p is null ? null : new TwinTexture(p.Data, p.TexW, p.TexH);

    [Theory, MemberData(nameof(Cases))]
    public void TwinAnswersTheVector(string label)
    {
        var file = File.Value;
        var c = file.Case(label);
        var a = file.ResolveArgs(c);
        var node = a[0];
        var near = Pyramid(a[3]);
        var far = Pyramid(a[5]);
        var rect = a[4] is null ? new double[] { 0, 0, -1, -1 } : VectorCompare.NumList(a[4]).ToArray();
        var extent = a[6] is null ? new double[] { -1e6, -1e6, 1e6, 1e6 } : VectorCompare.NumList(a[6]).ToArray();
        var ranges = VectorCompare.NumList(a[8]).ToArray();
        double baseStep = near?.Step ?? far?.Step ?? Num(Key(node, "size")) / Num(Key(node, "cells"));
        var state = new TerrainShaderState(Tex(near), Geom(near), Levels(near), rect, Tex(far), Geom(far), Levels(far),
                                           extent, ranges, baseStep, baseStep, null, new double[] { 0, 0, 1, 0 }, new double[4],
                                           null, null, new double[] { 0, 0, 1, 0 }, Levels(null));
        var cam = a[7];
        var v = TerrainShaderTwin.Compute(state, new[] { Num(Key(node, "x")), Num(Key(node, "z")), Num(Key(node, "size")), Num(Key(node, "level")) },
                                          Num(a[1]) / TerrainLod.PatchN, Num(a[2]) / TerrainLod.PatchN,
                                          (Num(Key(cam, "x")), Num(Key(cam, "y")), Num(Key(cam, "z"))), false);
        var e = c.Expect;
        Assert.True(Math.Abs(v.X - Num(Key(e, "x"))) <= c.Eps && Math.Abs(v.Z - Num(Key(e, "z"))) <= c.Eps
                    && Math.Abs(v.Y - Num(Key(e, "y"))) <= c.Eps,
                    $"{label}: twin ({v.X}, {v.Y}, {v.Z}) vs {VectorCompare.Show(e)}");
    }
}
