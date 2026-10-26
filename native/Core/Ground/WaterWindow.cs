using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Water;

namespace AnimaNative.Ground;

/// <summary>
/// The water window the water variant samples (the browser's water pyramid base level over the near window):
/// the loaded wet tiles merged onto ONE 2 m lattice spanning their bounding tiles — sd (R32F, dry = −1e4), kind
/// row (R32F, resolved on the CPU like <c>buildKindRows</c>, unknown kind → row 0 = the primary water) and flow
/// (RG32F, 0 = still). Tiles share their edge rows, so the merge is exact.
/// </summary>
public sealed class WaterWindow
{
    public double OriginX, OriginZ, Step;
    public int Cols, Rows;
    public float[] Sd = Array.Empty<float>();
    public float[] KindRow = Array.Empty<float>();
    public float[] Flow = Array.Empty<float>();
    public int Tiles, WetTexels;

    public static WaterWindow? Build(IEnumerable<(int Tx, int Tz, WaterTileField F)> tiles, double tileM,
                                     IReadOnlyDictionary<string, int> rowOfKind)
    {
        var list = tiles.ToList();
        if (list.Count == 0) return null;
        double step = list[0].F.Step;
        int per = (int)Math.Round(tileM / step);
        int tx0 = list.Min(t => t.Tx), tz0 = list.Min(t => t.Tz);
        int tx1 = list.Max(t => t.Tx), tz1 = list.Max(t => t.Tz);
        var w = new WaterWindow
        {
            OriginX = tx0 * tileM, OriginZ = tz0 * tileM, Step = step,
            Cols = (tx1 - tx0 + 1) * per + 1, Rows = (tz1 - tz0 + 1) * per + 1, Tiles = list.Count,
        };
        w.Sd = new float[w.Cols * w.Rows];
        Array.Fill(w.Sd, (float)WaterShade.SdDry);
        w.KindRow = new float[w.Cols * w.Rows];
        w.Flow = new float[w.Cols * w.Rows * 2];
        foreach (var (tx, tz, f) in list)
        {
            int oi = (int)Math.Round((f.OriginX - w.OriginX) / step), oj = (int)Math.Round((f.OriginZ - w.OriginZ) / step);
            var rows = f.Kinds.Select(k => rowOfKind.TryGetValue(k.ToLowerInvariant(), out var r) ? r : 0).ToArray();
            for (int j = 0; j < f.Rows; j++)
            for (int i = 0; i < f.Cols; i++)
            {
                int gi = oi + i, gj = oj + j;
                if (gi < 0 || gj < 0 || gi >= w.Cols || gj >= w.Rows) continue;
                int k = j * f.Cols + i, g = gj * w.Cols + gi;
                w.Sd[g] = f.Sd[k];
                int idx = f.KindIdx[k];
                w.KindRow[g] = idx >= 0 && idx < rows.Length ? rows[idx] : 0;
                w.Flow[2 * g] = f.FlowX?[k] ?? 0;
                w.Flow[2 * g + 1] = f.FlowZ?[k] ?? 0;
            }
            w.WetTexels += f.Wet;
        }
        return w;
    }
}
