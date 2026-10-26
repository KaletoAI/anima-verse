using System;
using System.Linq;
using System.Text.Json;
using AnimaNative.World;
using Json = AnimaNative.World.Json;

namespace AnimaNative.Ground;

/// <summary>
/// One height tile's water field (Wasser v2 K-A, client3d/src/scene/waterRaster.ts <c>WaterTileField</c>) on
/// the tile's own lattice: <c>level</c> (NaN = dry), <c>sd</c> (the signed distance to the authored outline,
/// <see cref="SdDry"/> where dry), the tile's kind palette + per-texel index, and the flow (null = still).
/// </summary>
public sealed record WaterTileField(double OriginX, double OriginZ, double Step, int Rows, int Cols,
                                    float[] Level, float[] Sd, string[] Kinds, int[] KindIdx,
                                    float[]? FlowX, float[]? FlowZ)
{
    /// <summary>The signed distance of a dry texel (waterRaster.ts <c>WATER_SD_DRY</c>); <c>Water.SdDry</c> reads it from here.</summary>
    public const double SdDry = -1e4;

    public int Wet => Level.Count(v => !float.IsNaN(v));

    /// <summary>The <c>water</c> block of a tile; the lattice is the HEIGHT tile's (origin, step, size).</summary>
    public static WaterTileField? Parse(JsonElement tile, HeightGrid grid)
    {
        if (!tile.TryGetProperty("water", out var w) || w.ValueKind != JsonValueKind.Object) return null;
        int rows = grid.Rows, cols = grid.Cols;
        float[] Field(string name, float dry, out bool present)
        {
            var a = new float[rows * cols];
            Array.Fill(a, dry);
            present = false;
            if (!w.TryGetProperty(name, out var f) || f.ValueKind != JsonValueKind.Array) return a;
            present = true;
            int j = 0;
            foreach (var row in f.EnumerateArray())
            {
                if (j >= rows) break;
                if (row.ValueKind == JsonValueKind.Array)
                {
                    int i = 0;
                    foreach (var v in row.EnumerateArray())
                    {
                        if (i >= cols) break;
                        if (v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var d) && double.IsFinite(d))
                            a[j * cols + i] = (float)d;
                        i++;
                    }
                }
                j++;
            }
            return a;
        }
        var level = Field("level", float.NaN, out _);
        var sd = Field("sd", (float)SdDry, out _);
        var kindF = Field("kind_idx", 0, out _);
        var fx = Field("flow_x", 0, out bool hasFx);
        var fz = Field("flow_z", 0, out bool hasFz);
        // waterTileFrom: the tile's own palette, a non-string entry as ''; a wire without one (a bake older than
        // HEIGHT_BAKE_VERSION 10) is ONE entry of the empty name, which resolves to the primary water.
        var kinds = w.TryGetProperty("kinds", out var ks) && ks.ValueKind == JsonValueKind.Array && ks.GetArrayLength() > 0
            ? ks.EnumerateArray().Select(k => k.ValueKind == JsonValueKind.String ? k.GetString() ?? "" : "").ToArray()
            : new[] { "" };
        // An index outside the palette is clamped to 0 AT THE WIRE BOUNDARY, so no reader indexes past it.
        var kindIdx = kindF.Select(v => v >= 0 && v < kinds.Length ? (int)Math.Floor(v) : 0).ToArray();
        return new WaterTileField(grid.OriginX, grid.OriginZ, grid.Step, rows, cols, level, sd, kinds,
                                  kindIdx, hasFx ? fx : null, hasFz ? fz : null);
    }
}
