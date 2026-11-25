using AnimaNative.Nav;
using AnimaNative.Overview;

namespace AnimaNative.Orders;

/// <summary>Where a link ride stands (review W5).</summary>
public enum LinkRideState { Requested, Riding, Done, Refused }

/// <summary>
/// The client's ride over one off-mesh link (a stair flight, a lift hop), as <see cref="OrderWalk"/> drives it:
/// <see cref="Begin"/> at the link foot, then <see cref="Poll"/> once per frame. <see cref="Begin"/> may answer
/// <see cref="LinkRideState.Requested"/> (the avatar's room entry is still running on the server; the walk holds at
/// the link foot); <see cref="Poll"/> answers <see cref="LinkRideState.Requested"/> until the answer is there, then
/// <see cref="LinkRideState.Riding"/> until <see cref="LinkRideState.Done"/>. <see cref="LinkRideState.Refused"/>
/// ends the order (event <c>link_refused</c>). An NPC ride answers <see cref="LinkRideState.Riding"/> from
/// <see cref="Begin"/> on. <see cref="Abort"/> when the order changes mid-ride.
/// An instance holds the state of ONE figure's ride (no handle): one instance per figure and kind, never shared
/// between figures (second review W5).
/// </summary>
public interface ILinkRide
{
    /// <summary><c>stairs</c> or <c>lift</c>.</summary>
    string Kind { get; }

    LinkRideState Begin(string actor, NavLink link);

    /// <summary>Moves <paramref name="pos"/> along the ride for <paramref name="dt"/> seconds.</summary>
    LinkRideState Poll(ref Vec3 pos, double dt, double speedMS);

    void Abort();
}
