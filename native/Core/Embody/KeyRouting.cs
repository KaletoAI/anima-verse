namespace AnimaNative.Embody;

/// <summary>Task 47 (E7-T2): bus.ts keyboard ownership and Escape priority; embody.json, no engine key types.</summary>
public static class KeyRouting
{
    public static bool KeyForScene(bool typing, bool overlayOpen) => !typing && !overlayOpen;
    public static string EscTarget(bool typing, bool overlayOpen, bool menuOpen, bool elevatorOpen)
        => !KeyForScene(typing, overlayOpen) ? "ignore" : elevatorOpen ? "elevator" : menuOpen ? "menu" : "mode";
}
