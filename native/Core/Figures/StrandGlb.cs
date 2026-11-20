using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;

namespace AnimaNative.Figures;

/// <summary>
/// One glTF primitive that carries per-vertex strand attributes (docs/schnittstellen-3d.md "Hair strands",
/// "Per-vertex binding": <c>_STRAND_CARD</c> u16 card + 1, <c>_STRAND_U</c> f32 row place), read from the GLB bytes
/// because Godot's runtime glTF import drops every custom attribute but <c>_CUSTOM0..3</c>. Everything is in the
/// order of the vertices Godot keeps: <see cref="Kept"/>[j] is the GLB vertex that became Godot's vertex j.
/// </summary>
public sealed class StrandGlbPrimitive
{
    public required int Mesh { get; init; }
    public required int Primitive { get; init; }
    public required string MeshName { get; init; }
    /// <summary>The primitive's vertex count in the GLB (before Godot drops the unreferenced ones).</summary>
    public required int SourceVertices { get; init; }
    /// <summary>Godot vertex j → GLB vertex (<see cref="StrandGlb.KeptVertices"/>).</summary>
    public required int[] Kept { get; init; }
    /// <summary>POSITION of the kept vertices, xyz.</summary>
    public required float[] Pos { get; init; }
    /// <summary>The attributes whose name starts with the prefix (first component), per kept vertex.</summary>
    public required IReadOnlyDictionary<string, double[]> Attributes { get; init; }

    public bool Has(string name) => Attributes.ContainsKey(name);
}

/// <summary>
/// Reads the strand attributes of a plain (meshopt-decoded) GLB and predicts Godot's vertex order. Godot 4.7.2
/// (<c>gltf_document.cpp</c> <c>_parse_meshes</c>): an indexed primitive keeps only the vertices an index references, in
/// ascending GLB order (<c>indices_mapping</c>), and <c>SurfaceTool.index()</c> returns early on an indexed surface, so
/// nothing is merged or reordered; a primitive without indices is welded by <c>SurfaceTool.index()</c> (identical
/// vertices merge) — the prediction is then the identity and <see cref="Matches"/> refuses the merged case.
/// Godot-free.
/// </summary>
public static class StrandGlb
{
    public const string Prefix = "_STRAND";

    /// <summary>The vertices Godot keeps, ascending: the ones <paramref name="indices"/> references (null = all).</summary>
    public static int[] KeptVertices(int count, IReadOnlyList<int>? indices)
    {
        if (indices is null) return Enumerable.Range(0, count).ToArray();
        var used = new bool[count];
        foreach (int i in indices)
        {
            if (i < 0 || i >= count) throw new InvalidDataException($"index {i} outside {count} vertices");
            used[i] = true;
        }
        var kept = new List<int>(count);
        for (int v = 0; v < count; v++) if (used[v]) kept.Add(v);
        return kept.ToArray();
    }

    /// <summary>
    /// Whether Godot's surface positions <paramref name="godotPos"/> (xyz per vertex) are the primitive's kept
    /// positions, bit for bit (a skinned primitive is imported uncompressed: float in, float out).
    /// </summary>
    public static bool Matches(StrandGlbPrimitive p, IReadOnlyList<float> godotPos)
    {
        if (godotPos.Count != p.Pos.Length) return false;
        for (int i = 0; i < p.Pos.Length; i++)
            if (BitConverter.SingleToInt32Bits(godotPos[i]) != BitConverter.SingleToInt32Bits(p.Pos[i])) return false;
        return true;
    }

    /// <summary>Every primitive of a GLB with at least one attribute named <paramref name="prefix"/>…; empty when none.
    /// Throws <see cref="InvalidDataException"/> on a broken container or accessor.</summary>
    public static List<StrandGlbPrimitive> Read(byte[] glb, string prefix = Prefix)
    {
        var (json, bin) = Chunks(glb);
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var found = new List<StrandGlbPrimitive>();
        if (!root.TryGetProperty("meshes", out var meshes) || meshes.ValueKind != JsonValueKind.Array) return found;
        int m = 0;
        foreach (var mesh in meshes.EnumerateArray())
        {
            string name = mesh.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String ? n.GetString()! : "";
            int p = 0;
            if (mesh.TryGetProperty("primitives", out var prims) && prims.ValueKind == JsonValueKind.Array)
                foreach (var prim in prims.EnumerateArray())
                {
                    if (prim.TryGetProperty("attributes", out var attrs) && attrs.ValueKind == JsonValueKind.Object
                        && attrs.EnumerateObject().Any(a => a.Name.StartsWith(prefix, StringComparison.Ordinal))
                        && attrs.TryGetProperty("POSITION", out var posAcc))
                    {
                        var pos = Accessor(root, bin, posAcc.GetInt32());
                        int count = pos.Count;
                        int[]? indices = prim.TryGetProperty("indices", out var ia) && ia.ValueKind == JsonValueKind.Number
                            ? Accessor(root, bin, ia.GetInt32()).Values.Select(x => (int)x).ToArray() : null;
                        var kept = KeptVertices(count, indices);
                        var keptPos = new float[kept.Length * 3];
                        for (int j = 0; j < kept.Length; j++)
                            for (int d = 0; d < 3; d++) keptPos[3 * j + d] = (float)pos.Values[kept[j] * pos.Size + d];
                        var values = new Dictionary<string, double[]>(StringComparer.Ordinal);
                        foreach (var a in attrs.EnumerateObject().Where(a => a.Name.StartsWith(prefix, StringComparison.Ordinal)))
                        {
                            var acc = Accessor(root, bin, a.Value.GetInt32());
                            if (acc.Count != count) throw new InvalidDataException($"{a.Name}: {acc.Count} values for {count} vertices");
                            values[a.Name] = kept.Select(v => acc.Values[v * acc.Size]).ToArray();
                        }
                        found.Add(new StrandGlbPrimitive
                        {
                            Mesh = m, Primitive = p, MeshName = name, SourceVertices = count, Kept = kept, Pos = keptPos, Attributes = values,
                        });
                    }
                    p++;
                }
            m++;
        }
        return found;
    }

    private static (byte[] Json, byte[] Bin) Chunks(byte[] glb)
    {
        if (glb.Length < 20 || BitConverter.ToUInt32(glb, 0) != 0x46546C67u) throw new InvalidDataException("not a GLB");
        int at = 12;
        byte[]? json = null, bin = null;
        while (at + 8 <= glb.Length)
        {
            int len = (int)BitConverter.ToUInt32(glb, at);
            uint type = BitConverter.ToUInt32(glb, at + 4);
            if (at + 8 + len > glb.Length) throw new InvalidDataException("GLB chunk past the end");
            var data = glb.AsSpan(at + 8, len).ToArray();
            if (type == 0x4E4F534Au) json ??= data;
            else if (type == 0x004E4942u) bin ??= data;
            at += 8 + len;
        }
        if (json is null) throw new InvalidDataException("GLB without a JSON chunk");
        return (json, bin ?? Array.Empty<byte>());
    }

    private sealed record AccessorData(int Count, int Size, double[] Values);

    /// <summary>An accessor's values as doubles (normalized integers mapped like glTF says), byteStride honoured.</summary>
    private static AccessorData Accessor(JsonElement root, byte[] bin, int index)
    {
        var acc = root.GetProperty("accessors")[index];
        int count = acc.GetProperty("count").GetInt32();
        int size = acc.GetProperty("type").GetString() switch
        {
            "SCALAR" => 1, "VEC2" => 2, "VEC3" => 3, "VEC4" => 4, "MAT4" => 16,
            var t => throw new InvalidDataException($"accessor type {t}"),
        };
        int ct = acc.GetProperty("componentType").GetInt32();
        bool normalized = acc.TryGetProperty("normalized", out var nz) && nz.ValueKind == JsonValueKind.True;
        if (acc.TryGetProperty("sparse", out _)) throw new InvalidDataException("sparse accessors are not read");
        var values = new double[count * size];
        if (!acc.TryGetProperty("bufferView", out var bvi)) return new AccessorData(count, size, values);   // all zeros (glTF)
        var bv = root.GetProperty("bufferViews")[bvi.GetInt32()];
        if (bv.GetProperty("buffer").GetInt32() != 0) throw new InvalidDataException("only the GLB's own buffer is read");
        int comp = ct switch { 5120 or 5121 => 1, 5122 or 5123 => 2, 5125 or 5126 => 4, _ => throw new InvalidDataException($"componentType {ct}") };
        int start = (bv.TryGetProperty("byteOffset", out var bo) ? bo.GetInt32() : 0) + (acc.TryGetProperty("byteOffset", out var ao) ? ao.GetInt32() : 0);
        int stride = bv.TryGetProperty("byteStride", out var bs) ? bs.GetInt32() : comp * size;
        if (count > 0 && start + (count - 1) * stride + comp * size > bin.Length) throw new InvalidDataException("accessor past the buffer");
        for (int i = 0; i < count; i++)
            for (int c = 0; c < size; c++)
            {
                int o = start + i * stride + c * comp;
                values[i * size + c] = ct switch
                {
                    5120 => normalized ? Math.Max((sbyte)bin[o] / 127.0, -1) : (sbyte)bin[o],
                    5121 => normalized ? bin[o] / 255.0 : bin[o],
                    5122 => normalized ? Math.Max(BitConverter.ToInt16(bin, o) / 32767.0, -1) : BitConverter.ToInt16(bin, o),
                    5123 => normalized ? BitConverter.ToUInt16(bin, o) / 65535.0 : BitConverter.ToUInt16(bin, o),
                    5125 => BitConverter.ToUInt32(bin, o),
                    _ => BitConverter.ToSingle(bin, o),
                };
            }
        return new AccessorData(count, size, values);
    }
}
