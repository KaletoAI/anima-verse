using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Sync;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The Godot-free parts of the per-strand hair RUNTIME (stage 4 wiring): the record cache's ETag / retry rules
/// (the browser scene's deleted smoke_strand_record.mjs [a]–[d], ported case for case), the GLB attribute reader with Godot's
/// vertex order (an unreferenced vertex dropped, an interleaved buffer view), the vertex-buffer encoding of the upload
/// (hand values of Godot's octahedral normal) and <c>withoutHairGroups</c>.
/// </summary>
public class StrandRuntimeTests
{
    // ---- smoke_strand_record.mjs ---------------------------------------------------------------------------------

    private static JsonElement Record(string sha) => JsonDocument.Parse($"{{\"version\":2,\"item_id\":\"hair\",\"fit_sha256\":\"{sha}\"}}").RootElement;

    private sealed class Server
    {
        public readonly Queue<ConditionalAnswer> Answers = new();
        public int Downloads;
        public Task<ConditionalAnswer> Fetch(string url) { Downloads++; return Task.FromResult(Answers.Dequeue()); }
    }

    [Fact]
    public void RecordCacheFollowsTheEtagAndRetryRules()
    {
        var server = new Server();
        double now = 1000;
        var lib = new StrandRecordCache(server.Fetch, () => now);
        const string url = "/characters/demo/model/hair-strands";

        // [a] an answer for another sha is not kept; no second download inside the retry time, one after it; [d]
        server.Answers.Enqueue(new ConditionalAnswer(200, "\"bbb\"", Record("bbb")));
        Assert.Equal(StrandRecordState.Pending, lib.Get(url, "aaa").State);
        Assert.Equal(StrandRecordState.Pending, lib.Get(url, "aaa").State);
        Assert.Equal(1, server.Downloads);
        lib.SetRetryAt("aaa", 0);
        server.Answers.Enqueue(new ConditionalAnswer(200, "\"aaa\"", Record("aaa")));
        Assert.Equal(StrandRecordState.Pending, lib.Get(url, "aaa").State);
        Assert.Equal(2, server.Downloads);
        var (state, record) = lib.Get(url, "aaa");
        Assert.Equal(StrandRecordState.Ready, state);
        Assert.Equal("aaa", record!.FitSha256);

        // [b] a 503 is a passing failure: pending, asked again after the retry time
        server.Answers.Enqueue(new ConditionalAnswer(503, "", null));
        lib.Get(url, "ccc");
        Assert.Equal(StrandRecordState.Pending, lib.Get(url, "ccc").State);
        Assert.Equal(3, server.Downloads);
        now += StrandRecordCache.RetryMs + 1;
        server.Answers.Enqueue(new ConditionalAnswer(200, "\"ccc\"", Record("ccc")));
        lib.Get(url, "ccc");
        Assert.Equal("ccc", lib.Get(url, "ccc").Record!.FitSha256);

        // [c] 404 = no strands, no further download
        server.Answers.Enqueue(new ConditionalAnswer(404, "", null));
        lib.Get(url, "ddd");
        Assert.Equal(StrandRecordState.None, lib.Get(url, "ddd").State);
        Assert.Equal(5, server.Downloads);

        // another record version is none, a network failure is pending
        server.Answers.Enqueue(new ConditionalAnswer(200, "\"eee\"", JsonDocument.Parse("{\"version\":1}").RootElement));
        lib.Get(url, "eee");
        Assert.Equal(StrandRecordState.None, lib.Get(url, "eee").State);
        var failing = new StrandRecordCache(_ => Task.FromException<ConditionalAnswer>(new IOException("down")), () => now);
        failing.Get(url, "fff");
        Assert.Equal(StrandRecordState.Pending, failing.Get(url, "fff").State);
        Assert.Equal(1, failing.Downloads);
    }

    // ---- the GLB attribute reader ----------------------------------------------------------------------------------

    /// <summary>A GLB of one primitive: 5 vertices (POSITION interleaved with a padding float, stride 16), _STRAND_CARD u16,
    /// _STRAND_U f32, indices referencing 0, 1, 3, 4 (vertex 2 is unreferenced).</summary>
    internal static byte[] AttributeGlb(bool indexed = true)
    {
        float[][] pos = { new[] { 0f, 1f, 2f }, new[] { 3f, 4f, 5f }, new[] { 6f, 7f, 8f }, new[] { 9f, 10f, 11f }, new[] { 12f, 13f, 14f } };
        ushort[] card = { 0, 1, 1, 2, 2 };
        float[] u = { 0, 0.5f, 7, 16, 3.25f };
        ushort[] idx = { 0, 1, 3, 1, 4, 3 };
        using var bin = new MemoryStream();
        using (var w = new BinaryWriter(bin, Encoding.UTF8, true))
        {
            foreach (var p in pos) { w.Write(p[0]); w.Write(p[1]); w.Write(p[2]); w.Write(-1f); }   // 80 B, stride 16
            foreach (var c in card) w.Write(c);                                                     // 10 B (+2 pad)
            w.Write((ushort)0);
            foreach (var x in u) w.Write(x);                                                        // 20 B
            foreach (var i in idx) w.Write(i);                                                      // 12 B
        }
        var data = bin.ToArray();
        string prim = indexed ? ",\"indices\":3" : "";
        string json = "{\"asset\":{\"version\":\"2.0\"},\"meshes\":[{\"name\":\"body\",\"primitives\":[{\"attributes\":{\"POSITION\":0}}]},"
            + "{\"name\":\"hair\",\"primitives\":[{\"attributes\":{\"POSITION\":0,\"_STRAND_CARD\":1,\"_STRAND_U\":2}" + prim + "}]}],"
            + "\"accessors\":[{\"bufferView\":0,\"componentType\":5126,\"count\":5,\"type\":\"VEC3\"},"
            + "{\"bufferView\":1,\"componentType\":5123,\"count\":5,\"type\":\"SCALAR\"},"
            + "{\"bufferView\":2,\"componentType\":5126,\"count\":5,\"type\":\"SCALAR\"},"
            + "{\"bufferView\":3,\"componentType\":5123,\"count\":6,\"type\":\"SCALAR\"}],"
            + "\"bufferViews\":[{\"buffer\":0,\"byteOffset\":0,\"byteLength\":80,\"byteStride\":16},{\"buffer\":0,\"byteOffset\":80,\"byteLength\":10},"
            + "{\"buffer\":0,\"byteOffset\":92,\"byteLength\":20},{\"buffer\":0,\"byteOffset\":112,\"byteLength\":12}],"
            + $"\"buffers\":[{{\"byteLength\":{data.Length}}}]}}";
        return Pack(json, data);
    }

    internal static byte[] Pack(string json, byte[] data)
    {
        var text = Encoding.UTF8.GetBytes(json);
        int padded = (text.Length + 3) & ~3, binPadded = (data.Length + 3) & ~3;
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(0x46546C67u); w.Write(2u); w.Write((uint)(12 + 8 + padded + 8 + binPadded));
        w.Write((uint)padded); w.Write(0x4E4F534Au); w.Write(text);
        for (int i = text.Length; i < padded; i++) w.Write((byte)0x20);
        w.Write((uint)binPadded); w.Write(0x004E4942u); w.Write(data);
        for (int i = data.Length; i < binPadded; i++) w.Write((byte)0);
        w.Flush();
        return ms.ToArray();
    }

    [Fact]
    public void GlbAttributesFollowGodotsKeptVertices()
    {
        var prims = StrandGlb.Read(AttributeGlb());
        var p = Assert.Single(prims);   // the body primitive has no strand attribute
        Assert.Equal((1, 0, "hair", 5), (p.Mesh, p.Primitive, p.MeshName, p.SourceVertices));
        Assert.Equal(new[] { 0, 1, 3, 4 }, p.Kept);                       // vertex 2 is referenced by no index
        Assert.Equal(new float[] { 0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14 }, p.Pos);   // stride 16 honoured
        Assert.Equal(new double[] { 0, 1, 2, 2 }, p.Attributes["_STRAND_CARD"]);
        Assert.Equal(new double[] { 0, 0.5, 16, 3.25 }, p.Attributes["_STRAND_U"]);
        Assert.True(StrandGlb.Matches(p, p.Pos.ToArray()));
        var moved = p.Pos.ToArray(); moved[4] = BitConverter.Int32BitsToSingle(BitConverter.SingleToInt32Bits(moved[4]) + 1);
        Assert.False(StrandGlb.Matches(p, moved));                        // one ulp off: not this primitive
        Assert.False(StrandGlb.Matches(p, p.Pos.Take(9).ToArray()));

        var plain = Assert.Single(StrandGlb.Read(AttributeGlb(indexed: false)));
        Assert.Equal(new[] { 0, 1, 2, 3, 4 }, plain.Kept);               // no indices: every vertex, in order
        Assert.Equal(new[] { 1, 2 }, StrandGlb.KeptVertices(4, new[] { 2, 1, 2 }));
        Assert.Throws<InvalidDataException>(() => StrandGlb.KeptVertices(2, new[] { 2 }));
        Assert.Throws<InvalidDataException>(() => StrandGlb.Read(new byte[] { 1, 2, 3 }));
    }

    // ---- the upload encoding ---------------------------------------------------------------------------------------

    [Fact]
    public void OctahedralNormalIsGodotsQuantisation()
    {
        // octahedron_encode: +Z → (0.5, 0.5) → 0.5·65535 = 32767.5 → 32767; +X → (1, 0.5); −Z → the folded corner (1, 1);
        // −X → (0, 0.5); (1, 1, 0)/√2 → L1 1 → (0.5, 0.5)+(0.25, 0.25) = (0.75, 0.75) → 49151.25 → 49151.
        Assert.Equal(((ushort)32767, (ushort)32767), StrandUpload.OctNormal(0, 0, 1));
        Assert.Equal(((ushort)65535, (ushort)32767), StrandUpload.OctNormal(1, 0, 0));
        Assert.Equal(((ushort)65535, (ushort)65535), StrandUpload.OctNormal(0, 0, -1));
        Assert.Equal(((ushort)0, (ushort)32767), StrandUpload.OctNormal(-1, 0, 0));
        float h = MathF.Sqrt(0.5f);
        Assert.Equal(((ushort)49151, (ushort)49151), StrandUpload.OctNormal(h, h, 0));
        var rng = new Random(7);
        for (int i = 0; i < 1000; i++)
        {
            float x = (float)(rng.NextDouble() * 2 - 1), y = (float)(rng.NextDouble() * 2 - 1), z = (float)(rng.NextDouble() * 2 - 1);
            float l = MathF.Sqrt(x * x + y * y + z * z);
            var (ox, oy) = StrandUpload.OctNormal(x, y, z);
            var (dx, dy, dz) = StrandUpload.OctDecode(ox, oy);
            Assert.True(MathF.Abs(dx - x / l) + MathF.Abs(dy - y / l) + MathF.Abs(dz - z / l) < 4e-4f, $"{x},{y},{z} -> {dx},{dy},{dz} ({ox},{oy})");   // truncation, not rounding: ≤ 1 step of 2/65535 per oct axis
        }
    }

    [Fact]
    public void UploadWritesPositionsAndNormalsIntoTheirStreams()
    {
        // 3 vertices: positions stride 12 at 0, normal + tangent stride 8 at 36 (Godot: the normal block after every position).
        var layout = new StrandVertexLayout(3, 0, 12, 36, 8);
        var buffer = Enumerable.Repeat((byte)0xAB, 60).ToArray();
        float[] pos = { 1, 2, 3, -4, 5.5f, 6, 7, 8, 9.25f };
        float[] nrm = { 0, 0, 1, 1, 0, 0, 0, 0, -1 };
        StrandUpload.Write(buffer, layout, pos, nrm);
        var (p, n) = StrandUpload.Read(buffer, layout);
        Assert.Equal(pos, p);
        Assert.Equal(32767, BitConverter.ToUInt16(buffer, 36));
        Assert.Equal(65535, BitConverter.ToUInt16(buffer, 44));
        for (int i = 0; i < 9; i++) Assert.True(Math.Abs(n[i] - nrm[i]) < 2e-4);
        // the tangent bytes are untouched
        Assert.All(new[] { 40, 41, 42, 43, 48, 49, 50, 51, 56, 57, 58, 59 }, o => Assert.Equal(0xAB, buffer[o]));
        Assert.Throws<ArgumentException>(() => StrandUpload.Write(new byte[40], layout, pos, nrm));
    }

    [Fact]
    public void WithoutHairGroupsDropsTheChainsAndKeepsTheRest()
    {
        var payload = MotionPayload.Parse(JsonDocument.Parse(
            "{\"rev\":\"r7\",\"groups\":{\"hair_c00\":{\"hair\":true,\"bones\":[\"HairGen_c00_00\"]},\"tail\":{\"bones\":[\"Tail_01\"]}}}").RootElement)!;
        var out_ = StrandRules.WithoutHairGroups(payload)!;
        Assert.Equal("r7:strands", out_.Rev);
        Assert.Equal(new[] { "tail" }, out_.Groups.Select(g => g.Name));
        Assert.Same(out_, StrandRules.WithoutHairGroups(payload));
        Assert.Null(StrandRules.WithoutHairGroups(null));
    }
}
