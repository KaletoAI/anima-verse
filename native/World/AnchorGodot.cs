using Godot;

namespace AnimaNative.World;

/// <summary>The Godot side of <see cref="AnchorInfo"/> (which lives in the engine-free core).</summary>
public static class AnchorGodot
{
    /// <summary>The anchor as a Godot position (world metres, y up).</summary>
    public static Vector3 Position(this AnchorInfo anchor) => new((float)anchor.X, (float)anchor.Y, (float)anchor.Z);
}
