using System;
using Godot;

namespace AnimaNative.Figures;

public partial class FigureManager
{
    private sealed record PairPreview(string Id, double Previous, double Yaw, Vector3 At);
    private PairPreview? _pairPreview;

    /// <summary>Purely visual invite/accept feedback, sent before the shared HUD starts HTTP.</summary>
    public void PairFacing(string phase, string id, string partner)
    {
        if (!_figures.TryGetValue(AvatarName, out var avatar)) return;
        if (phase == "begin")
        {
            if (avatar.Pair is not null || !_figures.TryGetValue(partner, out var other)) return;
            var direction = other.Position - avatar.Position; direction.Y = 0;
            if (direction.LengthSquared() < 1e-6) return;
            double yaw = Math.Atan2(direction.X, direction.Z);
            _pairPreview = new(id, avatar.Yaw, yaw, avatar.Position);
            avatar.FaceTowards(direction, snap: true);
        }
        else if (phase == "rollback" && _pairPreview is { } preview && preview.Id == id)
        {
            _pairPreview = null;
            if (PairPreviewDistance(avatar, preview) <= .02)
                avatar.FaceTowards(new((float)Math.Sin(preview.Previous), 0, (float)Math.Cos(preview.Previous)), snap: true);
        }
    }

    private static double PairPreviewDistance(Figure avatar, PairPreview preview)
        => Math.Sqrt(Math.Pow(avatar.Position.X - preview.At.X, 2) + Math.Pow(avatar.Position.Z - preview.At.Z, 2));

    private bool HoldsPairFacing(Figure fig)
    {
        if (fig.CharacterName != AvatarName || _pairPreview is not { } preview) return false;
        if (PairPreviewDistance(fig, preview) > .02) { _pairPreview = null; return false; }
        fig.FaceTowards(new((float)Math.Sin(preview.Yaw), 0, (float)Math.Cos(preview.Yaw)), snap: true);
        return true;
    }
}
