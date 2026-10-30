using AnimaNative.Scene;

namespace AnimaNative;

/// <summary>Task 52 / E7-T7: scene-owned talk/entry/place state; HUD-owned neighbour locks stay authoritative.</summary>
public partial class Main
{
    private void TickAvatarOffers()
    {
        if(_avatarOffers is not { } offers || _hud is not { } hud) return;
        offers.SetActive(Embodied && !Leaving);
        offers.LockedLocations=LockState.FromHud(null,null,hud.HudOwned("lockedLocations"),"").Locations;
        offers.Tick();
        // Probe a stationary pointer too: camera easing, re-lifts and availability can change its target.
        if(_camera is { } camera && _hoverAt is { } at && !hud.PointerOverHud && hud.Active)
        {
            var (o,d)=camera.RayAt(at);
            if(offers.Hover(o,d)) _avatarRooms?.Picking.Clear();
            Hover(at);
        }
        else offers.Places.ClearHover();
    }
    private double PropPollPeriod() => _poll?.IntervalMs(WorldmapKey) ?? AnimaNative.Sync.PollSpec.Worldmap3d.IntervalMs;
    private void RefreshOffersMap() => _poll?.Signal(WorldmapKey);
}
