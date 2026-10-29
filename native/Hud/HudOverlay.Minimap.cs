namespace AnimaNative.Hud;

/// <summary>Task 55 / E7-T10: the v3 minimap slice belongs to the scene. Keep its wire, including null on
/// exit, for PublishAll after CEF reconnects; step publishes reuse the producer's serialized relief fragment.</summary>
public partial class HudOverlay
{
    private string _minimapWire = HudProtocol.Minimap(null);

    public void SetMinimap(MinimapState? state)
    {
        _minimapWire = HudProtocol.Minimap(state);
        Send(_minimapWire);
    }
}
