using System;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AnimaNative.Gltf;

/// <summary>
/// Turns a Meshopt-compressed GLB back into a plain one that Godot's
/// <c>GLTFDocument</c> can read (controller ruling P2-R5 — the server keeps
/// delivering compressed copies; Godot 4.7.2 does not list
/// <c>EXT_meshopt_compression</c> among its supported extensions).
///
/// What the server writes (app/blender/scripts/meshopt.py): every compressed
/// bufferView points at a FALLBACK buffer that carries no bytes
/// (<c>extensions.EXT_meshopt_compression.fallback = true</c>), and its
/// extension object names the real compressed range in the GLB's BIN buffer
/// together with <c>count</c>, <c>byteStride</c>, <c>mode</c> and an optional
/// <c>filter</c>. The extension is listed as REQUIRED.
///
/// The rewrite: every bufferView — decoded where it carries the extension,
/// copied otherwise — is laid into ONE fresh binary buffer (4-byte aligned),
/// the views are re-pointed at it, the old buffers (fallback included) are
/// replaced by that one, and the extension name leaves
/// <c>extensionsUsed</c>/<c>extensionsRequired</c>. Accessors, meshes,
/// materials and images keep their indices untouched. A GLB without the
/// extension is returned as the very same array.
/// </summary>
public static class GlbMeshoptDecoder
{
    private const uint Magic = 0x46546C67;     // "glTF"
    private const uint ChunkJson = 0x4E4F534A; // "JSON"
    private const uint ChunkBin = 0x004E4942;  // "BIN\0"

    /// <summary>Both spellings of the extension (KHR_ is the ratified name of the same codec).</summary>
    private static readonly string[] ExtNames = { "EXT_meshopt_compression", "KHR_meshopt_compression" };

    /// <summary>Statistics of the last decode, for logs and the check.</summary>
    public readonly record struct DecodeStats(int Views, int Attributes, int Triangles, int Indices, int OutputBytes);

    public static byte[] Decode(byte[] glb) => Decode(glb, out _);

    public static byte[] Decode(byte[] glb, out DecodeStats stats)
    {
        stats = default;
        var (json, bin) = ReadGlb(glb);
        var root = JsonNode.Parse(json)?.AsObject() ?? throw new InvalidDataException("GLB JSON is not an object");
        var used = root["extensionsUsed"]?.AsArray();
        if (used is null || !used.Any(n => ExtNames.Contains(n?.GetValue<string>()))) return glb;

        var buffers = root["buffers"]?.AsArray() ?? new JsonArray();
        var views = root["bufferViews"]?.AsArray() ?? new JsonArray();
        byte[]? BufferBytes(int index)
        {
            if (index < 0 || index >= buffers.Count) throw new InvalidDataException($"buffer {index} out of range");
            var b = buffers[index]!.AsObject();
            if (b["uri"] is not null) throw new NotSupportedException("GLB buffers with a uri are not supported");
            // GLB rule: the BIN chunk is buffer 0 (when it has no uri). Any other
            // uri-less buffer is a Meshopt fallback without bytes.
            return index == 0 ? bin : null;
        }

        var output = new MemoryStream();
        int attributes = 0, triangles = 0, indices = 0;
        for (int vi = 0; vi < views.Count; vi++)
        {
            var view = views[vi]!.AsObject();
            var extObj = view["extensions"]?.AsObject();
            JsonObject? ext = null;
            string? extName = null;
            if (extObj is not null)
                foreach (var name in ExtNames)
                    if (extObj[name] is JsonObject o) { ext = o; extName = name; break; }

            byte[] data;
            int viewLength = Int(view, "byteLength");
            if (ext is not null)
            {
                var src = BufferBytes(Int(ext, "buffer"))
                          ?? throw new InvalidDataException($"bufferView {vi}: compressed data points at a fallback buffer");
                int offset = Int(ext, "byteOffset"), length = Int(ext, "byteLength");
                int stride = Int(ext, "byteStride"), count = Int(ext, "count");
                string mode = ext["mode"]?.GetValue<string>() ?? "ATTRIBUTES";
                string filter = ext["filter"]?.GetValue<string>() ?? "NONE";
                if (offset < 0 || length <= 0 || offset + length > src.Length)
                    throw new InvalidDataException($"bufferView {vi}: compressed range out of bounds");
                data = new byte[Math.Max((long)count * stride, viewLength)];
                DecodeView(data, count, stride, src.AsSpan(offset, length), mode, filter, vi);
                switch (mode) { case "ATTRIBUTES": attributes++; break; case "TRIANGLES": triangles++; break; default: indices++; break; }
                extObj!.Remove(extName!);
                if (extObj.Count == 0) view.Remove("extensions");
            }
            else
            {
                var src = BufferBytes(Int(view, "buffer"))
                          ?? throw new InvalidDataException($"bufferView {vi}: points at a fallback buffer without the extension");
                int offset = Int(view, "byteOffset");
                if (offset < 0 || viewLength < 0 || offset + viewLength > src.Length)
                    throw new InvalidDataException($"bufferView {vi}: range out of bounds");
                data = src.AsSpan(offset, viewLength).ToArray();
            }
            Pad(output, 4, 0);
            long newOffset = output.Position;
            output.Write(data, 0, data.Length);
            view["buffer"] = 0;
            view["byteOffset"] = newOffset;
            if (viewLength <= 0) view["byteLength"] = data.Length;
        }
        Pad(output, 4, 0);

        root["buffers"] = new JsonArray(new JsonObject { ["byteLength"] = output.Length });
        foreach (var key in new[] { "extensionsUsed", "extensionsRequired" })
        {
            if (root[key] is not JsonArray list) continue;
            for (int i = list.Count - 1; i >= 0; i--)
                if (ExtNames.Contains(list[i]?.GetValue<string>())) list.RemoveAt(i);
            if (list.Count == 0) root.Remove(key);
        }
        var result = WriteGlb(root.ToJsonString(), output.ToArray());
        stats = new DecodeStats(attributes + triangles + indices, attributes, triangles, indices, result.Length);
        return result;
    }

    /// <summary>True when the GLB's JSON lists one of the Meshopt extensions as used.</summary>
    public static bool IsCompressed(byte[] glb)
    {
        var (json, _) = ReadGlb(glb);
        using var doc = JsonDocument.Parse(json);
        return doc.RootElement.TryGetProperty("extensionsUsed", out var used)
               && used.ValueKind == JsonValueKind.Array
               && used.EnumerateArray().Any(e => e.ValueKind == JsonValueKind.String && ExtNames.Contains(e.GetString()));
    }

    private static unsafe void DecodeView(byte[] dst, int count, int stride, ReadOnlySpan<byte> src,
                                          string mode, string filter, int vi)
    {
        if (count <= 0 || stride <= 0) throw new InvalidDataException($"bufferView {vi}: bad count/stride");
        int rc;
        fixed (byte* d = dst)
        fixed (byte* s = src)
        {
            rc = mode switch
            {
                "ATTRIBUTES" => MeshoptNative.meshopt_decodeVertexBuffer(d, (nuint)count, (nuint)stride, s, (nuint)src.Length),
                "TRIANGLES" => MeshoptNative.meshopt_decodeIndexBuffer(d, (nuint)count, (nuint)stride, s, (nuint)src.Length),
                "INDICES" => MeshoptNative.meshopt_decodeIndexSequence(d, (nuint)count, (nuint)stride, s, (nuint)src.Length),
                _ => throw new InvalidDataException($"bufferView {vi}: unknown meshopt mode '{mode}'"),
            };
            if (rc != 0) throw new InvalidDataException($"bufferView {vi}: meshopt {mode} decode failed (rc={rc})");
            if (mode == "ATTRIBUTES")
            {
                switch (filter)
                {
                    case "NONE": break;
                    case "OCTAHEDRAL": MeshoptNative.meshopt_decodeFilterOct(d, (nuint)count, (nuint)stride); break;
                    case "QUATERNION": MeshoptNative.meshopt_decodeFilterQuat(d, (nuint)count, (nuint)stride); break;
                    case "EXPONENTIAL": MeshoptNative.meshopt_decodeFilterExp(d, (nuint)count, (nuint)stride); break;
                    case "COLOR": MeshoptNative.meshopt_decodeFilterColor(d, (nuint)count, (nuint)stride); break;
                    default: throw new InvalidDataException($"bufferView {vi}: unknown meshopt filter '{filter}'");
                }
            }
            else if (filter != "NONE")
                throw new InvalidDataException($"bufferView {vi}: filter '{filter}' on index data");
        }
    }

    private static int Int(JsonObject o, string name)
        => o[name] is JsonValue v ? (int)v.GetValue<double>() : 0;

    private static void Pad(Stream s, int align, byte value)
    {
        while (s.Position % align != 0) s.WriteByte(value);
    }

    /// <summary>Split a GLB v2 into its JSON text and its BIN chunk (empty when absent).</summary>
    public static (string Json, byte[] Bin) ReadGlb(byte[] glb)
    {
        if (glb.Length < 20) throw new InvalidDataException("GLB too short");
        var span = glb.AsSpan();
        if (BinaryPrimitives.ReadUInt32LittleEndian(span) != Magic) throw new InvalidDataException("not a GLB (magic)");
        if (BinaryPrimitives.ReadUInt32LittleEndian(span[4..]) != 2) throw new InvalidDataException("GLB version is not 2");
        uint total = BinaryPrimitives.ReadUInt32LittleEndian(span[8..]);
        if (total > glb.Length) throw new InvalidDataException("GLB length exceeds data");
        string? json = null;
        byte[] bin = Array.Empty<byte>();
        int pos = 12;
        while (pos + 8 <= total)
        {
            int length = (int)BinaryPrimitives.ReadUInt32LittleEndian(span[pos..]);
            uint kind = BinaryPrimitives.ReadUInt32LittleEndian(span[(pos + 4)..]);
            pos += 8;
            if (length < 0 || pos + length > total) throw new InvalidDataException("GLB chunk out of bounds");
            if (kind == ChunkJson && json is null) json = Encoding.UTF8.GetString(span.Slice(pos, length)).TrimEnd(' ', '\0');
            else if (kind == ChunkBin && bin.Length == 0) bin = span.Slice(pos, length).ToArray();
            pos += length;
        }
        return (json ?? throw new InvalidDataException("GLB has no JSON chunk"), bin);
    }

    /// <summary>Pack JSON (space-padded) and BIN (zero-padded) into a GLB v2.</summary>
    public static byte[] WriteGlb(string json, byte[] bin)
    {
        var jsonBytes = Encoding.UTF8.GetBytes(json);
        int jsonLen = (jsonBytes.Length + 3) & ~3;
        int binLen = (bin.Length + 3) & ~3;
        int total = 12 + 8 + jsonLen + (bin.Length > 0 ? 8 + binLen : 0);
        var outBytes = new byte[total];
        var span = outBytes.AsSpan();
        BinaryPrimitives.WriteUInt32LittleEndian(span, Magic);
        BinaryPrimitives.WriteUInt32LittleEndian(span[4..], 2);
        BinaryPrimitives.WriteUInt32LittleEndian(span[8..], (uint)total);
        BinaryPrimitives.WriteUInt32LittleEndian(span[12..], (uint)jsonLen);
        BinaryPrimitives.WriteUInt32LittleEndian(span[16..], ChunkJson);
        jsonBytes.CopyTo(span[20..]);
        span.Slice(20 + jsonBytes.Length, jsonLen - jsonBytes.Length).Fill((byte)' ');
        if (bin.Length > 0)
        {
            int p = 20 + jsonLen;
            BinaryPrimitives.WriteUInt32LittleEndian(span[p..], (uint)binLen);
            BinaryPrimitives.WriteUInt32LittleEndian(span[(p + 4)..], ChunkBin);
            bin.CopyTo(span[(p + 8)..]);
        }
        return outBytes;
    }
}
