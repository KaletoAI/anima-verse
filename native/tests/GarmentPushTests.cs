using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The GPU garment push's text (<see cref="GarmentPush"/>): EXECUTED by <see cref="GlslMini"/> on every
/// <c>pushOutOfCapsules</c> case of shared/test-vectors/collision_core.json (the TypeScript's output, the same file the
/// C# twin <see cref="Collision.PushOutOfCapsules"/> replays) — the shader the GPU runs is the browser's push, number for
/// number in double precision; its constants are the C# ones; the insertion into Godot's generated StandardMaterial3D
/// code only ADDS (every original line and uniform stays, in order); the capsule choice per garment kind.
/// </summary>
public class GarmentPushTests
{
    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static double[] V(JsonNode? n) => new[] { N(n![0]), N(n[1]), N(n[2]) };

    /// <summary>The shader text a garment gets, the declarations and push block plus a wrapper of the vertex() call.</summary>
    private static GlslMini Shader(bool squeeze)
    {
        var apply = GarmentPush.Apply.Replace("\t// Anima native", "\t// ");
        return new GlslMini(GarmentPush.Block(squeeze) + "vec3 vertexStage( vec3 VERTEX, vec4 CUSTOM0 ) {\n" + apply + "\treturn VERTEX;\n}\n");
    }

    /// <summary>
    /// collision_core <c>pushOutOfCapsules(p, capsules, weight, bindP, squeeze)</c> through the shader: capsules →
    /// the uniform arrays as GarmentPushModifier writes them (bind rule on — <c>collideBindA.w</c> 0 — only where the case
    /// has a bind axis AND a bind point, the twin's rule), bindP → CUSTOM0.xyz, weight → CUSTOM0.w.
    /// </summary>
    internal static JsonNode? ShaderPush(JsonArray a)
    {
        var p = V(a[0]);
        var caps = (JsonArray)a[1]!;
        double weight = N(a[2]);
        var bindP = a[3] is null ? null : V(a[3]);
        bool squeeze = a[4]!.GetValue<bool>();
        var g = Shader(squeeze);
        int n = Math.Min(caps.Count, Collision.CollideMax);
        GlslMini.Vec Zero4() => new(0, 0, 0, 0);
        var A = Enumerable.Range(0, Collision.CollideMax).Select(_ => Zero4()).ToArray();
        var B = Enumerable.Range(0, Collision.CollideMax).Select(_ => Zero4()).ToArray();
        var BA = Enumerable.Range(0, Collision.CollideMax).Select(_ => new GlslMini.Vec(0, 0, 0, -1)).ToArray();
        var BB = Enumerable.Range(0, Collision.CollideMax).Select(_ => Zero4()).ToArray();
        for (int i = 0; i < n; i++)
        {
            var c = caps[i]!;
            var ca = V(c["a"]); var cb = V(c["b"]);
            A[i] = new GlslMini.Vec(ca[0], ca[1], ca[2], N(c["r"]));
            B[i] = new GlslMini.Vec(cb[0], cb[1], cb[2], 0);
            if (c["bind"] is { } bind && bindP is not null)
            {
                var ba = V(bind["a"]); var bb = V(bind["b"]);
                BA[i] = new GlslMini.Vec(ba[0], ba[1], ba[2], 0);
                BB[i] = new GlslMini.Vec(bb[0], bb[1], bb[2], 0);
            }
        }
        g.Uniform("collideA", A); g.Uniform("collideB", B); g.Uniform("collideBindA", BA); g.Uniform("collideBindB", BB);
        g.Uniform("collideCount", n);
        var bp = bindP ?? new double[3];
        var r = (GlslMini.Vec)g.Invoke("vertexStage", new GlslMini.Vec(p), new GlslMini.Vec(bp[0], bp[1], bp[2], weight));
        return new JsonArray(r.C[0], r.C[1], r.C[2]);
    }

    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("collision_core"));

    private static IEnumerable<VectorCase> Push => File.Value.Cases.Where(c => c.Fn == "pushOutOfCapsules");

    public static TheoryData<string> PushCases()
    {
        var data = new TheoryData<string>();
        foreach (var c in Push) data.Add(c.Label);
        return data;
    }

    /// <summary>The shader text, executed, gives the TypeScript's point for every push case of the vectors.</summary>
    [Theory]
    [MemberData(nameof(PushCases))]
    public void ShaderTextMatchesTheVectors(string label)
    {
        var dispatch = new Dictionary<string, Func<JsonArray, JsonNode?>>(HairVectorAdapters.Dispatch) { ["pushOutOfCapsules"] = ShaderPush };
        File.Value.AssertCase(label, dispatch);
    }

    [Fact]
    public void EnoughPushCasesAreCovered()
    {
        var push = Push.Select(c => File.Value.ResolveArgs(c)).ToList();
        Assert.True(push.Count >= 20, $"{push.Count} push cases");
        Assert.Contains(push, a => a[4]!.GetValue<bool>());                                   // squeeze
        Assert.Contains(push, a => !a[4]!.GetValue<bool>());                                  // plain
        Assert.Contains(push, a => a[3] is not null);                                         // bind rule
        Assert.Contains(push, a => N(a[2]) is > 0 and < 1);                                   // a weight
        Assert.Contains(push, a => ((JsonArray)a[1]!).Count > Collision.CollideMax);           // COLLIDE_MAX
    }

    /// <summary>A random sample beyond the vectors: shader text = C# twin (plain and squeeze, bind rule, weight).</summary>
    [Fact]
    public void ShaderTextMatchesTheTwinOnARandomSample()
    {
        var rng = new Random(4242);
        double R(double lo, double hi) => lo + (hi - lo) * rng.NextDouble();
        for (int trial = 0; trial < 300; trial++)
        {
            int count = rng.Next(1, 20);
            var caps = new JsonArray();
            var twin = new List<CollideCapsule>();
            for (int i = 0; i < count; i++)
            {
                var a = new V3(R(-.2, .2), R(-.2, .2), R(-.2, .2));
                var b = rng.NextDouble() < .3 ? a : new V3(R(-.2, .2), R(-.2, .2), R(-.2, .2));
                double r = R(.02, .15);
                bool bind = rng.NextDouble() < .5;
                var ba = new V3(a.X + R(-.02, .02), a.Y, a.Z); var bb = new V3(b.X, b.Y + R(-.02, .02), b.Z);
                var o = new JsonObject { ["a"] = new JsonArray(a.X, a.Y, a.Z), ["b"] = new JsonArray(b.X, b.Y, b.Z), ["r"] = r };
                if (bind) o["bind"] = new JsonObject { ["a"] = new JsonArray(ba.X, ba.Y, ba.Z), ["b"] = new JsonArray(bb.X, bb.Y, bb.Z) };
                caps.Add(o);
                twin.Add(bind ? new CollideCapsule(a, b, r, ba, bb) : new CollideCapsule(a, b, r));
            }
            var p = new V3(R(-.2, .2), R(-.2, .2), R(-.2, .2));
            V3? bindP = rng.NextDouble() < .5 ? new V3(p.X + R(-.05, .05), p.Y + R(-.05, .05), p.Z) : null;
            double w = rng.NextDouble() < .3 ? R(0, 1) : 1;
            bool squeeze = rng.NextDouble() < .5;
            var args = new JsonArray(new JsonArray(p.X, p.Y, p.Z), caps, w,
                                     bindP is { } q ? new JsonArray(q.X, q.Y, q.Z) : null, squeeze);
            var got = ShaderPush(args)!;
            var want = Collision.PushOutOfCapsules(p, twin, w, bindP, squeeze);
            Assert.True(Math.Abs(N(got[0]) - want.X) < 1e-12 && Math.Abs(N(got[1]) - want.Y) < 1e-12 && Math.Abs(N(got[2]) - want.Z) < 1e-12,
                        $"trial {trial}: shader ({N(got[0])}, {N(got[1])}, {N(got[2])}) vs twin {want}");
        }
    }

    /// <summary>Every constant in the text is a #define of the C# value; the function bodies hold no constant of their own.</summary>
    [Fact]
    public void ConstantsComeFromTheCSharpConstants()
    {
        var defines = Regex.Matches(GarmentPush.Declarations, @"#define (\w+) (\S+)").ToDictionary(m => m.Groups[1].Value, m => m.Groups[2].Value);
        double D(string k) => double.Parse(defines[k], CultureInfo.InvariantCulture);
        Assert.Equal(Collision.CollideMax, (int)D("COLLIDE_MAX"));
        Assert.Equal(Collision.CollidePasses, (int)D("COLLIDE_PASSES"));
        Assert.Equal(Collision.CollideEps, D("COLLIDE_EPS"));
        Assert.Equal(Collision.CollideMinD, D("COLLIDE_MIN_D"));
        Assert.Equal(Collision.SqueezeRounds, (int)D("SQUEEZE_ROUNDS"));
        Assert.Equal(Collision.SqueezeSteps, (int)D("SQUEEZE_STEPS"));
        Assert.Equal(Collision.SqueezeMinN, D("SQUEEZE_MIN_N"));
        Assert.Equal(16, Collision.CollideMax);
        Assert.Equal(2, Collision.CollidePasses);
        foreach (var text in new[] { GarmentPush.FunctionPlain, GarmentPush.FunctionSqueeze })
        {
            // the only literals: 0, 1, 0.0, 1.0, 0.5, 1.5, 2.0 (arithmetic of the rule, not tunables)
            var literals = Regex.Matches(text, @"(?<![\w.])\d+(\.\d+)?(e-?\d+)?(?![\w.])").Select(m => m.Value).Distinct().ToList();
            Assert.All(literals, l => Assert.Contains(l, new[] { "0", "1", "0.0", "1.0", "0.5", "1.5", "2.0" }));
            foreach (var k in defines.Keys.Where(k => k.StartsWith("COLLIDE_", StringComparison.Ordinal) && k != "COLLIDE_PASSES"))
                Assert.Contains(k, text);
        }
        Assert.Contains("SQUEEZE_ROUNDS", GarmentPush.FunctionSqueeze);
        Assert.Contains("SQUEEZE_STEPS", GarmentPush.FunctionSqueeze);
        Assert.Contains("SQUEEZE_MIN_N", GarmentPush.FunctionSqueeze);
        Assert.Contains("COLLIDE_PASSES", GarmentPush.FunctionPlain);
        Assert.Contains("COLLIDE_PASSES", GarmentPush.FunctionSqueeze);   // the fallback passes
    }

    private static StandardShaderSpec CardHair => new()
    {
        Transparency = StandardShaderSpec.TransparencyMode.AlphaScissor, Cull = StandardShaderSpec.CullKind.Disabled,
        Diffuse = StandardShaderSpec.DiffuseKind.Lambert, DontReceiveShadows = true, AlbedoFromVertexColor = true,
    };

    /// <summary>
    /// The push only ADDS to Godot's generated code: removing the inserted block and the call gives the original text
    /// back character for character (every uniform, render mode, line, in order), the call is the last statement of
    /// vertex(), and the declarations precede vertex().
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void InjectOnlyAdds(bool squeeze)
    {
        foreach (var spec in new[] { CardHair, new StandardShaderSpec { Diffuse = StandardShaderSpec.DiffuseKind.Lambert, NormalMap = true },
                                     CardHair with { Shading = StandardShaderSpec.ShadingKind.PerVertex, SrgbVertexColor = true } })
        {
            var code = StandardShaderCode.Generate(spec)!;
            var patched = GarmentPush.Inject(code, squeeze);
            var block = GarmentPush.Block(squeeze);
            Assert.Equal(1, Regex.Matches(patched, Regex.Escape(block)).Count);
            Assert.Equal(1, Regex.Matches(patched, Regex.Escape(GarmentPush.Apply)).Count);
            Assert.Equal(code, patched.Replace(block, "").Replace(GarmentPush.Apply, ""));
            Assert.True(patched.IndexOf(block, StringComparison.Ordinal) < patched.IndexOf("void vertex()", StringComparison.Ordinal));
            var vertex = patched[patched.IndexOf("void vertex()", StringComparison.Ordinal)..];
            var applyAt = vertex.IndexOf(GarmentPush.Apply, StringComparison.Ordinal);
            Assert.Equal("}", vertex[(applyAt + GarmentPush.Apply.Length)..].Split('\n')[0]);   // nothing after the call in vertex()
            var uniforms = StandardShaderCode.Uniforms(spec);
            Assert.All(uniforms, u => Assert.Matches(@"uniform [^;]*\b" + u + @"\b", patched));
            Assert.Throws<ArgumentException>(() => GarmentPush.Inject(patched, squeeze));   // not twice
        }
    }

    [Fact]
    public void InjectRefusesWhatItCannotCarry()
    {
        var code = StandardShaderCode.Generate(CardHair)!;
        Assert.Throws<ArgumentException>(() => GarmentPush.Inject(code.Replace("render_mode ", "render_mode skip_vertex_transform, "), false));
        Assert.Throws<ArgumentException>(() => GarmentPush.Inject(code.Replace("render_mode ", "render_mode world_vertex_coords, "), false));
        Assert.Throws<ArgumentException>(() => GarmentPush.Inject(code.Replace("UV = UV", "return;\n\tUV = UV"), false));
        Assert.Throws<ArgumentException>(() => GarmentPush.Inject(code.Replace("UV = UV", "COLOR = CUSTOM0;\n\tUV = UV"), false));
        Assert.Throws<ArgumentException>(() => GarmentPush.Inject("shader_type canvas_item;\nvoid fragment() {}\n", false));
        // A spatial shader without vertex() gets one, holding only the call.
        var noVertex = GarmentPush.Inject("shader_type spatial;\nuniform vec4 c;\nvoid fragment() { ALBEDO = c.rgb; }\n", true);
        Assert.EndsWith("void vertex() {\n" + GarmentPush.Apply + "}\n", noVertex);
    }

    /// <summary>garmentCollision.ts <c>garmentCapsules</c> / <c>garmentKind</c> by name.</summary>
    [Fact]
    public void CapsulesPerKind()
    {
        var regions = new[] { "torso", "arm", "head", "leg", "shoulder_hair", "chest_hair", "chest", "outer_trunk", "attached_part", "appendage" };
        Assert.Equal(new[] { "torso", "arm", "head", "shoulder_hair", "chest_hair" }, GarmentPush.Capsules("hair", regions, r => r));
        Assert.Equal(new[] { "torso", "head", "leg", "chest", "attached_part", "appendage" }, GarmentPush.Capsules("dress", regions, r => r));
        Assert.Equal(new[] { "torso", "head", "leg", "chest", "attached_part", "appendage" }, GarmentPush.Capsules("", regions, r => r));
        Assert.Empty(GarmentPush.Capsules("footwear", regions, r => r));
        Assert.Empty(GarmentPush.Capsules("accessory", regions, r => r));
        Assert.Equal(Collision.CollideMax, GarmentPush.Capsules("hair", Enumerable.Repeat("torso", 40), r => r).Count);
        Assert.True(GarmentPush.Collides("hair") && GarmentPush.Collides("top") && !GarmentPush.Collides("footwear") && !GarmentPush.Collides("accessory"));
        Assert.Equal("hair", GarmentPush.KindFromName("garment_hair_01"));
        Assert.Equal("", GarmentPush.KindFromName("garment_hair"));
        Assert.Equal("", GarmentPush.KindFromName("body"));
    }
}
