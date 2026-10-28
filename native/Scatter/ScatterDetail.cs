using AnimaNative.World;

namespace AnimaNative.Scatter;

/// <summary>Task 40 (E4-T5): one validated Graphics-tab distance update drives trees, billboards and landmarks.</summary>
public static class ScatterDetail
{
    public static void Apply(ScatterLodCfg cfg, ScatterField? scatter, WorldPropsLayer? props)
    {
        scatter?.SetLod(cfg);
        props?.SetLod(cfg);
    }
}
