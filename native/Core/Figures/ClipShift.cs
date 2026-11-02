using System;
using System.Text.Json;

namespace AnimaNative.Figures;

/// <summary>Whole-clip [side, forward] centimetres; absolute distance, independent of figure height.</summary>
public readonly record struct ClipShift(double Side, double Forward)
{
    public static ClipShift Parse(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 2) return default;
        if (value[0].ValueKind != JsonValueKind.Number || value[1].ValueKind != JsonValueKind.Number
            || !value[0].TryGetDouble(out var side) || !value[1].TryGetDouble(out var forward)
            || !double.IsFinite(side) || !double.IsFinite(forward)) return default;
        return new(side, forward);
    }

    /// <summary>Same Y rotation as clipShiftM, shared/test-vectors/clip_shift.json.</summary>
    public V3 World(double yaw) => new(
        (Side * Math.Cos(yaw) + Forward * Math.Sin(yaw)) / 100, 0,
        (-Side * Math.Sin(yaw) + Forward * Math.Cos(yaw)) / 100);

    /// <summary>Inverse lean: Rz(-roll) Rx(-tilt) [side,0,forward].</summary>
    public V3 Local(double tilt, double roll)
    {
        double x = Side / 100, y = Forward / 100 * Math.Sin(tilt), z = Forward / 100 * Math.Cos(tilt);
        return new(x * Math.Cos(roll) + y * Math.Sin(roll), -x * Math.Sin(roll) + y * Math.Cos(roll), z);
    }
}
