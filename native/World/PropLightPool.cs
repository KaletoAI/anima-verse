using System;
using System.Collections.Generic;
using AnimaNative.Scene;
using Godot;
using CoreVec3 = AnimaNative.Overview.Vec3;

namespace AnimaNative.World;

/// <summary>
/// The prop light pool of the 3D client (client3d/src/scene/lightPool.ts <c>LightPool</c>): SIX permanent OmniLight3D
/// slots (no shadows), re-assigned by <see cref="PropLights.PickLights"/> at 5 Hz from every registered source, faded
/// over 0.4 s and flickered per frame, with a night gate; plus one additive halo per source that has a <c>glow_m</c>
/// (not limited by the pool: a distant lamp still glows). The state is <see cref="LightPoolState"/> (Godot-free,
/// vector-checked arithmetic); this node only copies its outputs onto the lights and halos.
///
/// Units: a three PointLight intensity I (decay 2, distance <c>range_m</c>) becomes an OmniLight3D energy I/π
/// (<see cref="Sky.StageLight.Energy"/>, the stage's mapping). three lights a Lambert surface with
/// <c>albedo/π · I · colour · N·L · (1 − (d/R)⁴)₊² / max(d², 0.01)</c> (lights_pars_begin <c>getDistanceAttenuation</c>);
/// Godot 4.7.2 with <c>(albedo/π) · (E·π) · colour · N·L · (1 − (d/R)⁴)₊² · max(d, 1e-4)^−attenuation</c>
/// (light_storage.cpp ×π, scene_forward_lights_inc.glsl <c>get_omni_attenuation</c>). With attenuation 2 and range R =
/// <c>range_m</c> both agree for d ≥ 0.1 m. The omni specular amount is <c>light_specular · 2</c> = 1 at Godot's default
/// 0.5, three's unscaled GGX.
/// </summary>
public sealed partial class PropLightPool : Node3D
{
    /// <summary>three's PointLight with distance 0 has no cutoff; an OmniLight3D needs a range.</summary>
    public const float UnboundedRangeM = 4096f;

    private readonly OmniLight3D[] _lamps = new OmniLight3D[PropLights.PoolSize];
    private readonly Dictionary<string, MeshInstance3D> _halos = new();
    private static GradientTexture2D? _haloTexture;
    private Random _rng = new();

    public LightPoolState State { get; } = new();

    /// <summary>The last frame's slot outputs (for the check and the perf readout).</summary>
    public LightSlotOutput[] LastSlots { get; private set; } = Array.Empty<LightSlotOutput>();

    public PropLightPool()
    {
        Name = "PropLights";
        for (int i = 0; i < _lamps.Length; i++)
        {
            _lamps[i] = new OmniLight3D
            {
                Name = $"Lamp{i}",
                ShadowEnabled = false,
                OmniAttenuation = 2f,
                OmniRange = 1f,
                LightEnergy = 0f,
                // An empty or dark slot is hidden (Task 26b): Godot clusters every VISIBLE omni light by its range and
                // runs light_compute for it on every fragment inside, energy 0 or not — a range-0 source is 4096 m.
                Visible = false,
            };
            AddChild(_lamps[i]);
        }
    }

    /// <summary>The flicker phases are random like the browser's; the check seeds them.</summary>
    public void Seed(int seed) => _rng = new Random(seed);

    public IReadOnlyList<OmniLight3D> Lamps => _lamps;

    public MeshInstance3D? HaloOf(string id) => _halos.GetValueOrDefault(id);

    /// <summary>
    /// <c>register(light, pos, room_id)</c>: independent of any mesh (a failed model still emits light); a source with a
    /// <c>glow_m</c> gets its halo, a quad of 2·glow_m that always faces the camera.
    /// </summary>
    public string Register(ScenePropLight light, Vector3 pos, string roomKey)
    {
        var id = State.Register(light, new CoreVec3(pos.X, pos.Y, pos.Z), roomKey, _rng.NextDouble() * Math.PI * 2);
        if (light.GlowM > 0)
        {
            var halo = new MeshInstance3D
            {
                Name = "Halo" + id,
                Mesh = new QuadMesh { Size = new Vector2((float)(2 * light.GlowM), (float)(2 * light.GlowM)) },
                MaterialOverride = HaloMaterial(light.Color),
                CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
                Position = pos,
            };
            AddChild(halo);
            _halos[id] = halo;
        }
        return id;
    }

    public void Move(string id, Vector3 pos)
    {
        State.Move(id, new CoreVec3(pos.X, pos.Y, pos.Z));
        if (_halos.TryGetValue(id, out var halo) && IsInstanceValid(halo)) halo.Position = pos;
    }

    /// <summary><c>remove()</c>: once; the halo (this source's own material) goes with it.</summary>
    public void Remove(string id)
    {
        if (!State.Remove(id)) return;
        if (_halos.Remove(id, out var halo) && IsInstanceValid(halo)) halo.QueueFree();
    }

    /// <summary>
    /// <c>update(dt, focus, night, visibleRooms)</c>: the 5 Hz selection, the fades, the flicker and the fire colour on the
    /// six lamps; every halo shown under the room/night gate at the flicker × night-gain opacity.
    /// </summary>
    public void Tick(double dt, Vector3 focus, double night, ISet<string> visibleRooms)
    {
        var (slots, halos) = State.Update(dt, new CoreVec3(focus.X, focus.Y, focus.Z), night, visibleRooms);
        LastSlots = slots;
        for (int i = 0; i < _lamps.Length; i++)
        {
            var s = slots[i];
            var lamp = _lamps[i];
            if (s.SourceId.Length == 0)
            {
                lamp.LightEnergy = 0f;
                if (lamp.Visible) lamp.Visible = false;
                continue;
            }
            lamp.Position = new Vector3((float)s.Pos.X, (float)s.Pos.Y, (float)s.Pos.Z);
            lamp.OmniRange = s.RangeM > 0 ? (float)s.RangeM : UnboundedRangeM;
            lamp.LightColor = LampColour(s.Colour, s.FireMix);
            lamp.LightEnergy = (float)Sky.StageLight.Energy(s.Intensity);
            // Energy 0 adds exactly nothing (diffuse and specular both scale with it): no reason to cluster the lamp.
            bool lit = lamp.LightEnergy > 0f;
            if (lamp.Visible != lit) lamp.Visible = lit;
        }
        foreach (var h in halos)
        {
            if (!_halos.TryGetValue(h.SourceId, out var halo) || !IsInstanceValid(halo)) continue;
            halo.Visible = h.Visible;
            if (halo.MaterialOverride is StandardMaterial3D m)
            {
                var c = m.AlbedoColor;
                m.AlbedoColor = new Color(c.R, c.G, c.B, (float)h.Opacity);
            }
        }
    }

    /// <summary>The light colour, leaning towards the fire dip colour in LINEAR space (three lerps its working colours).</summary>
    public static Color LampColour(string hex, double fireMix)
    {
        var c = ParseColour(hex);
        if (fireMix <= 0) return c;
        var lin = c.SrgbToLinear().Lerp(ParseColour(PropLights.FireColour).SrgbToLinear(), (float)fireMix);
        return lin.LinearToSrgb();
    }

    private static Color ParseColour(string hex) => Color.HtmlIsValid(hex) ? Color.FromHtml(hex) : Colors.White;

    /// <summary>The halo look: the shared radial map, additive, unshaded, a billboard, no depth write (SpriteMaterial).</summary>
    private static StandardMaterial3D HaloMaterial(string hex) => new()
    {
        ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
        BillboardMode = BaseMaterial3D.BillboardModeEnum.Enabled,
        Transparency = BaseMaterial3D.TransparencyEnum.Alpha,
        BlendMode = BaseMaterial3D.BlendModeEnum.Add,
        DepthDrawMode = BaseMaterial3D.DepthDrawModeEnum.Disabled,
        AlbedoTexture = HaloTexture(),
        AlbedoColor = ParseColour(hex),
        CullMode = BaseMaterial3D.CullModeEnum.Disabled,
    };

    /// <summary>The 64 px radial gradient, white → transparent over the radius (lightPool.ts <c>texture()</c>), shared.</summary>
    public static GradientTexture2D HaloTexture()
    {
        if (_haloTexture is not null) return _haloTexture;
        var g = new Gradient();
        g.SetColor(0, new Color(1, 1, 1, 1));
        g.SetColor(1, new Color(1, 1, 1, 0));
        _haloTexture = new GradientTexture2D
        {
            Gradient = g, Width = 64, Height = 64, Fill = GradientTexture2D.FillEnum.Radial,
            FillFrom = new Vector2(0.5f, 0.5f), FillTo = new Vector2(1f, 0.5f),
        };
        return _haloTexture;
    }
}
