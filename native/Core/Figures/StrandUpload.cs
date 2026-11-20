using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;

namespace AnimaNative.Figures;

/// <summary>
/// Where a surface's vertex buffer keeps its positions and normals (Godot 4.7.2
/// <c>RenderingServer::mesh_surface_make_offsets_from_format</c>, an UNCOMPRESSED surface): positions as 3 floats at
/// <see cref="PosOffset"/> + v·<see cref="PosStride"/>; the normal as two octahedral u16 at <see cref="NrmOffset"/> +
/// v·<see cref="NrmStride"/> (the normal/tangent block follows all positions; the tangent, when present, sits right
/// after each normal and is left as it is).
/// </summary>
public readonly record struct StrandVertexLayout(int VertexCount, int PosOffset, int PosStride, int NrmOffset, int NrmStride);

/// <summary>
/// The per-frame mesh upload of the per-strand hair (hairSim.ts <c>rebuild</c> → <c>posOut / nrmOut.needsUpdate</c>):
/// the rebuilt positions and normals written into the surface's vertex-buffer bytes in Godot's own encoding, so ONE
/// <c>RenderingServer.MeshSurfaceUpdateVertexRegion</c> call replaces them (no surface rebuild, no index or skin
/// upload). The encoding is Godot's (<c>rendering_server.cpp</c> <c>_surface_set_data</c>, uncompressed): position
/// float32 ×3; normal <c>Vector3::octahedron_encode</c> → <c>(uint16_t)CLAMP(o · 65535, 0, 65535)</c>. Godot-free; the
/// check proves the bytes equal what Godot writes for the same arrays.
/// </summary>
public static class StrandUpload
{
    /// <summary>Godot's <c>Vector3::octahedron_encode</c> (float arithmetic) and the u16 quantisation of the normal stream.</summary>
    public static (ushort X, ushort Y) OctNormal(float x, float y, float z)
    {
        float l1 = MathF.Abs(x) + MathF.Abs(y) + MathF.Abs(z);
        float nx = x / l1, ny = y / l1, nz = z / l1;
        float ox, oy;
        if (nz >= 0.0f) { ox = nx; oy = ny; }
        else
        {
            ox = (1.0f - MathF.Abs(ny)) * (nx >= 0.0f ? 1.0f : -1.0f);
            oy = (1.0f - MathF.Abs(nx)) * (ny >= 0.0f ? 1.0f : -1.0f);
        }
        ox = ox * 0.5f + 0.5f;
        oy = oy * 0.5f + 0.5f;
        return (Quantise(ox), Quantise(oy));
    }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    private static ushort Quantise(float v)
    {
        float s = v * 65535;
        // CLAMP(s, 0, 65535) then the C cast (truncation); NaN (a zero normal) clamps like Godot's CLAMP: to 0.
        if (!(s > 0)) return 0;
        return s >= 65535 ? (ushort)65535 : (ushort)s;
    }

    /// <summary>Godot's <c>Vector3::octahedron_decode</c> of a stored normal (the check's read-back).</summary>
    public static (float X, float Y, float Z) OctDecode(ushort ux, ushort uy)
    {
        float fx = ux / 65535.0f * 2.0f - 1.0f, fy = uy / 65535.0f * 2.0f - 1.0f;
        float nz = 1.0f - MathF.Abs(fx) - MathF.Abs(fy);
        float nx = fx, ny = fy;
        float t = Math.Clamp(-nz, 0.0f, 1.0f);
        nx += nx >= 0 ? -t : t;
        ny += ny >= 0 ? -t : t;
        float l = MathF.Sqrt(nx * nx + ny * ny + nz * nz);
        return (nx / l, ny / l, nz / l);
    }

    /// <summary>Write <paramref name="pos"/> / <paramref name="nrm"/> (xyz per vertex) into <paramref name="buffer"/>.</summary>
    public static void Write(byte[] buffer, StrandVertexLayout layout, float[] pos, float[] nrm)
    {
        int n = layout.VertexCount;
        if (pos.Length < 3 * n || nrm.Length < 3 * n) throw new ArgumentException($"{pos.Length / 3} positions for {n} vertices");
        if (layout.PosOffset + (n - 1) * layout.PosStride + 12 > buffer.Length || layout.NrmOffset + (n - 1) * layout.NrmStride + 4 > buffer.Length)
            throw new ArgumentException("the layout runs past the vertex buffer");
        var span = buffer.AsSpan();
        for (int v = 0; v < n; v++)
        {
            int p = layout.PosOffset + v * layout.PosStride;
            BitConverter.TryWriteBytes(span.Slice(p, 4), pos[3 * v]);
            BitConverter.TryWriteBytes(span.Slice(p + 4, 4), pos[3 * v + 1]);
            BitConverter.TryWriteBytes(span.Slice(p + 8, 4), pos[3 * v + 2]);
            var (ox, oy) = OctNormal(nrm[3 * v], nrm[3 * v + 1], nrm[3 * v + 2]);
            int q = layout.NrmOffset + v * layout.NrmStride;
            BitConverter.TryWriteBytes(span.Slice(q, 2), ox);
            BitConverter.TryWriteBytes(span.Slice(q + 2, 2), oy);
        }
    }

    /// <summary>The positions and (decoded) normals a vertex buffer holds (the check's read-back).</summary>
    public static (float[] Pos, float[] Nrm) Read(byte[] buffer, StrandVertexLayout layout)
    {
        int n = layout.VertexCount;
        var pos = new float[3 * n];
        var nrm = new float[3 * n];
        for (int v = 0; v < n; v++)
        {
            int p = layout.PosOffset + v * layout.PosStride;
            for (int d = 0; d < 3; d++) pos[3 * v + d] = BitConverter.ToSingle(buffer, p + 4 * d);
            int q = layout.NrmOffset + v * layout.NrmStride;
            var (x, y, z) = OctDecode(BitConverter.ToUInt16(buffer, q), BitConverter.ToUInt16(buffer, q + 2));
            nrm[3 * v] = x; nrm[3 * v + 1] = y; nrm[3 * v + 2] = z;
        }
        return (pos, nrm);
    }
}

/// <summary>Small runtime rules of the per-strand hair that need no Godot.</summary>
public static class StrandRules
{
    private static readonly ConditionalWeakTable<MotionPayload, MotionPayload> WithoutHair = new();

    /// <summary>
    /// secondaryMotion.ts <c>withoutHairGroups</c>: the payload without its hair groups, <c>rev</c> + <c>":strands"</c> —
    /// a figure whose hair runs per strand solves no hair chain. The same object per payload (cached).
    /// </summary>
    public static MotionPayload? WithoutHairGroups(MotionPayload? payload)
    {
        if (payload is null) return null;
        return WithoutHair.GetValue(payload, p => new MotionPayload($"{p.Rev}:strands", p.Groups.Where(g => !g.Group.Hair).ToList()));
    }
}
