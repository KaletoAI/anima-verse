using System;
using System.Linq;
using System.Text.Json.Nodes;

namespace AnimaNative.World;

/// <summary>Task 55 / E7-T10: one RGBA pixel per overview support point, row zero north. JSON uses numeric
/// arrays explicitly: System.Text.Json's byte-array default is base64, which the unchanged HUD cannot draw.</summary>
public sealed record HillshadeImage(int Cols, int Rows, byte[] Data)
{
    public JsonObject ToJson() => new()
    {
        ["cols"] = Cols, ["rows"] = Rows,
        ["data"] = new JsonArray(Data.Select(b => (JsonNode?)JsonValue.Create((int)b)).ToArray()),
    };
}

/// <summary>Task 55 / E7-T10: port of packages/scene-render/src/hillshade.ts. X east/Z south; the default
/// cartographic lamp stands NW at 315°/45°. Central differences inside, one-sided at edges; upward normal
/// (-hx,1,-hz), Lambert grey relative to level ground, slope-sine alpha. No Godot, canvas or engine state.</summary>
public static class Hillshade
{
    public const double MapReliefZFactor = 3;
    private static double Option(JsonObject? opts, string key, double fallback)
        => opts?[key] is JsonValue v && v.TryGetValue<double>(out double d) && double.IsFinite(d) ? d : fallback;

    public static HillshadeImage? Build(HeightGrid? field, JsonObject? opts = null)
    {
        if (field is null || field.Rows < 2 || field.Cols < 2 || !(field.Step > 0)) return null;
        double azimuth = Option(opts, "azimuthDeg", 315) * Math.PI / 180;
        double altitude = Math.Clamp(Option(opts, "altitudeDeg", 45), 1, 90) * Math.PI / 180;
        double maxAlpha = Math.Clamp(Option(opts, "maxAlpha", .35), 0, 1);
        double factor = Math.Max(0, Option(opts, "zFactor", 1));
        double lx = Math.Cos(altitude) * Math.Sin(azimuth), ly = Math.Sin(altitude), lz = -Math.Cos(altitude) * Math.Cos(azimuth);
        double H(int i, int j)
        {
            int p = j * field.Cols + i;
            return p < field.Heights.Length && float.IsFinite(field.Heights[p]) ? field.Heights[p] : 0;
        }
        var data = new byte[field.Cols * field.Rows * 4];
        for (int j = 0; j < field.Rows; j++)
        {
            int n = Math.Max(0, j - 1), s = Math.Min(field.Rows - 1, j + 1);
            for (int i = 0; i < field.Cols; i++)
            {
                int w = Math.Max(0, i - 1), e = Math.Min(field.Cols - 1, i + 1);
                double hx = factor * (H(e, j) - H(w, j)) / ((e - w) * field.Step);
                double hz = factor * (H(i, s) - H(i, n)) / ((s - n) * field.Step);
                double grad = Math.Sqrt(hx * hx + hz * hz), len = Math.Sqrt(grad * grad + 1);
                double lambert = (-hx * lx + ly - hz * lz) / len;
                double shade = Math.Min(1, .5 * Math.Max(0, lambert) / ly);
                int p = (j * field.Cols + i) * 4;
                // Math.round for nonnegative channels, not C#'s midpoint-to-even default.
                byte grey = (byte)Math.Floor(255 * shade + .5);
                data[p] = data[p + 1] = data[p + 2] = grey;
                data[p + 3] = (byte)Math.Floor(255 * maxAlpha * grad / len + .5);
            }
        }
        return new(field.Cols, field.Rows, data);
    }
}
