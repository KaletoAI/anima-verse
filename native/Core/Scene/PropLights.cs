using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>What the selection needs of one light source (lightPool.ts <c>LightSourceView</c>); an empty room = none.</summary>
public sealed record LightSourceView(string Id, Vec3 Pos, double RangeM, string When, string RoomId = "");

/// <summary>One pool slot as the fade sees it: which source it shows (<c>""</c> = none) and at what gain.</summary>
public readonly record struct LightSlotState(string Id, double Gain);

/// <summary>
/// The pure half of the prop light pool, a port of client3d/src/scene/lightPool.ts (<c>pickLights</c>,
/// <c>flickerFactor</c>, <c>nightLightGain</c>, <c>haloVisible</c>, <c>fireColourMix</c>, <c>stepLightSlot</c>,
/// <c>lightPositionInFrame</c>), checked against shared/test-vectors/light_pool.json (hand derivations in
/// client3d/scripts/smoke_light_pool.mjs).
/// </summary>
public static class PropLights
{
    /// <summary><c>LIGHT_POOL_SIZE</c>: six permanent slots (three compiles the light count into every lit shader).</summary>
    public const int PoolSize = 6;
    /// <summary>The selection runs at 5 Hz (<c>elapsed ≥ .2</c>).</summary>
    public const double SelectIntervalS = 0.2;
    /// <summary>A slot fades in and out over 0.4 s.</summary>
    public const double FadeS = 0.4;
    /// <summary>The fire's dip colour <c>#ff6a20</c>.</summary>
    public const string FireColour = "#ff6a20";

    /// <summary>
    /// <c>pickLights</c>: candidates are the sources with (when ≠ night or night &gt; .3), a shown room (or none) and a 3D
    /// distance to the focus ≤ range_m + 30; nearest first (stable), the first <paramref name="n"/> win; a previous slot
    /// whose id still wins keeps it, the other winners fill the empty slots in distance order; trailing empty slots go.
    /// </summary>
    public static List<string> PickLights(IReadOnlyList<LightSourceView> sources, Vec3 focus, int n, double night,
                                          ISet<string> visibleRooms, IReadOnlyList<string>? previous = null)
    {
        double Distance(LightSourceView s)
        {
            double dx = s.Pos.X - focus.X, dy = s.Pos.Y - focus.Y, dz = s.Pos.Z - focus.Z;
            return Math.Sqrt(dx * dx + dy * dy + dz * dz);
        }
        var winners = sources.Where(s => (s.When != "night" || night > .3)
                                         && (s.RoomId.Length == 0 || visibleRooms.Contains(s.RoomId))
                                         && Distance(s) <= s.RangeM + 30)
                             .OrderBy(Distance)   // LINQ's OrderBy is stable, like Array.prototype.sort
                             .Take(Math.Max(0, n))
                             .Select(s => s.Id)
                             .ToList();
        var slots = new string[Math.Max(0, n)];
        for (int i = 0; i < slots.Length; i++)
        {
            var prev = previous is not null && i < previous.Count ? previous[i] : null;
            slots[i] = prev is not null && winners.Contains(prev) ? prev : "";
        }
        var free = new Queue<string>(winners.Where(id => !slots.Contains(id)));
        var assigned = slots.Select(id => id.Length > 0 ? id : free.Count > 0 ? free.Dequeue() : "").ToList();
        while (assigned.Count > 0 && assigned[^1].Length == 0) assigned.RemoveAt(assigned.Count - 1);
        return assigned;
    }

    /// <summary><c>flickerFactor</c>: two phased waves, candle 8 Hz ±.08, fire 4 Hz ±.25, anything else 1.</summary>
    public static double FlickerFactor(string kind, double t, double phase)
    {
        double hz = kind == "candle" ? 8 : 4;
        double a = kind == "candle" ? .08 : kind == "fire" ? .25 : 0;
        double t0 = t * hz * Math.PI * 2 + phase;
        return 1 + a * (Math.Sin(t0) + Math.Sin(t0 * Math.Sqrt(2))) / 2;
    }

    /// <summary>three's <c>MathUtils.smoothstep</c>.</summary>
    public static double SmoothStep(double x, double lo, double hi)
    {
        if (x <= lo) return 0;
        if (x >= hi) return 1;
        double t = (x - lo) / (hi - lo);
        return t * t * (3 - 2 * t);
    }

    /// <summary><c>nightLightGain</c>: a night lamp fades in between night .3 and .6, every other lamp is at 1.</summary>
    public static double NightLightGain(string when, double night) => when == "night" ? SmoothStep(night, .3, .6) : 1;

    /// <summary><c>haloVisible</c>: the room is shown and (when ≠ night or night &gt; .3).</summary>
    public static bool HaloVisible(bool roomShown, string when, double night) => roomShown && (when != "night" || night > .3);

    /// <summary><c>fireColourMix</c>: how far a fire leans towards <see cref="FireColour"/> (0.1 at the deepest dip).</summary>
    public static double FireColourMix(double t, double phase) => Math.Max(0, (1 - FlickerFactor("fire", t, phase)) / .25) * .1;

    /// <summary><c>stepLightSlot</c>: the wanted id fades in; another id fades out first and is swapped only at gain 0.</summary>
    public static LightSlotState StepLightSlot(LightSlotState slot, string wanted, double dt)
    {
        if (slot.Id != wanted)
        {
            double gain = Math.Max(0, slot.Gain - dt / FadeS);
            return new LightSlotState(gain == 0 ? wanted : slot.Id, gain);
        }
        return new LightSlotState(slot.Id, Math.Min(1, slot.Gain + dt / FadeS));
    }

    /// <summary>
    /// <c>lightPositionInFrame</c> (<c>placementLightPosition</c>): the base anchor (anchor x, bottom, anchor z) through
    /// the parent's column-major world matrix, then + (offset x, height, offset z) in world metres.
    /// </summary>
    public static Vec3 LightPositionInFrame(IReadOnlyList<double> frame, double anchorX, double anchorZ, double bottom,
                                            double offsetX, double offsetZ, double heightM)
    {
        double ax = anchorX, ay = bottom, az = anchorZ;
        double w = frame[3] * ax + frame[7] * ay + frame[11] * az + frame[15];
        return new Vec3((frame[0] * ax + frame[4] * ay + frame[8] * az + frame[12]) / w + offsetX,
                        (frame[1] * ax + frame[5] * ay + frame[9] * az + frame[13]) / w + heightM,
                        (frame[2] * ax + frame[6] * ay + frame[10] * az + frame[14]) / w + offsetZ);
    }
}

/// <summary>What the pool asks the scene to show for one slot this frame.</summary>
public readonly record struct LightSlotOutput(string SourceId, Vec3 Pos, double RangeM, string Colour, double FireMix, double Intensity);

/// <summary>What the pool asks the scene to show for one halo this frame.</summary>
public readonly record struct HaloOutput(string SourceId, bool Visible, double Opacity);

/// <summary>
/// The per-frame state of <c>LightPool</c> (lightPool.ts) without a renderer: every registered source, the six slots,
/// the 5 Hz selection and the per-frame fade/flicker. The Godot side (World/PropLightPool.cs) only copies the
/// outputs onto its OmniLight3D slots and halo quads.
/// </summary>
public sealed class LightPoolState
{
    private sealed class Source
    {
        public required LightSourceView View;
        public required ScenePropLight Light;
        public double Phase;
    }

    private readonly Dictionary<string, Source> _sources = new();
    private readonly LightSlotState[] _slots = Enumerable.Repeat(new LightSlotState("", 0), PropLights.PoolSize).ToArray();
    private List<string> _selected = new();
    private double _elapsed = PropLights.SelectIntervalS;
    private double _time;
    private int _serial;

    public int Count => _sources.Count;
    public IReadOnlyList<string> Selected => _selected;
    public IReadOnlyList<LightSlotState> Slots => _slots;

    /// <summary><c>register</c>: a source keeps its place independently of any mesh; the next update selects again.</summary>
    public string Register(ScenePropLight light, Vec3 pos, string roomId, double phase)
    {
        var id = (++_serial).ToString(System.Globalization.CultureInfo.InvariantCulture);
        _sources[id] = new Source { View = new LightSourceView(id, pos, light.RangeM, light.When, roomId), Light = light, Phase = phase };
        _elapsed = PropLights.SelectIntervalS;
        return id;
    }

    public void Move(string id, Vec3 pos)
    {
        if (_sources.TryGetValue(id, out var s)) s.View = s.View with { Pos = pos };
    }

    public Vec3? PositionOf(string id) => _sources.TryGetValue(id, out var s) ? s.View.Pos : null;

    public ScenePropLight? LightOf(string id) => _sources.TryGetValue(id, out var s) ? s.Light : null;

    /// <summary><c>remove</c>: once; the next update selects again.</summary>
    public bool Remove(string id)
    {
        if (!_sources.Remove(id)) return false;
        _elapsed = PropLights.SelectIntervalS;
        return true;
    }

    /// <summary>
    /// <c>update(dt, focus, night, visibleRooms)</c>: select at 5 Hz, fade and flicker every frame. Returns the six slot
    /// outputs (an empty slot has intensity 0) and one halo output per source.
    /// </summary>
    public (LightSlotOutput[] Slots, List<HaloOutput> Halos) Update(double dt, Vec3 focus, double night, ISet<string> visibleRooms)
    {
        _time += dt;
        _elapsed += dt;
        if (_elapsed >= PropLights.SelectIntervalS)
        {
            _elapsed = 0;
            _selected = PropLights.PickLights(_sources.Values.Select(s => s.View).ToList(), focus, PropLights.PoolSize, night,
                                              visibleRooms, _selected);
        }
        bool Active(Source s) => s.View.RoomId.Length == 0 || visibleRooms.Contains(s.View.RoomId);
        double Factor(Source s) => PropLights.FlickerFactor(s.Light.Flicker, _time, s.Phase) * PropLights.NightLightGain(s.View.When, night);
        var halos = new List<HaloOutput>();
        foreach (var s in _sources.Values)
            if (s.Light.GlowM > 0)
                halos.Add(new HaloOutput(s.View.Id, PropLights.HaloVisible(Active(s), s.View.When, night), Factor(s)));
        var outs = new LightSlotOutput[PropLights.PoolSize];
        for (int i = 0; i < _slots.Length; i++)
        {
            var wanted = i < _selected.Count ? _selected[i] : "";
            _slots[i] = PropLights.StepLightSlot(_slots[i], wanted, dt);
            if (!_sources.TryGetValue(_slots[i].Id, out var s))
            {
                outs[i] = new LightSlotOutput("", default, 0, "#ffffff", 0, 0);
                continue;
            }
            double mix = s.Light.Flicker == "fire" ? PropLights.FireColourMix(_time, s.Phase) : 0;
            outs[i] = new LightSlotOutput(s.View.Id, s.View.Pos, s.View.RangeM, s.Light.Color, mix,
                                          Active(s) ? s.Light.Intensity * _slots[i].Gain * Factor(s) : 0);
        }
        return (outs, halos);
    }
}
