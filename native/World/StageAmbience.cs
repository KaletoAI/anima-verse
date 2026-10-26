using AnimaNative.Scene;
using AnimaNative.Sky;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The stage lights of the browser engine (engine.ts constructor, <c>setGameHour</c>, <c>applyAmbience</c> and the
/// per-frame sun placement) on Godot nodes. Every number comes from <see cref="StageLight.Compose"/> (Godot-free,
/// unit-tested); this class only builds the nodes once and copies a frame onto them.
///
///   - <see cref="SetHour"/> = <c>setGameHour</c>: the clock base (sun colour and intensities, the sky background, the
///     night factor); <see cref="Apply"/> = <c>applyAmbience</c>: base × the eased room ambience; <see cref="Track"/> =
///     the frame's sun placement on the texel-snapped camera target plus the shadow fit to the camera distance.
///   - The sky is also the colour of the distance fog (<see cref="Fog"/>); Godot's own Environment fog stays OFF — the
///     fog is one screen pass (<see cref="DistanceFog"/>, Sky/FogPost.cs) because Godot's fog mixes in linear space.
///   - The hemisphere is an ambient colour plus <see cref="HemiUp"/> / <see cref="HemiDown"/> (see
///     <see cref="StageLight"/>); no sky reflection on any material (<c>ReflectedLightSource.Disabled</c>: three adds no
///     environment specular without an envMap), no tone mapping beyond the linear clamp (three's NoToneMapping).
/// </summary>
public sealed class StageAmbience
{
    public required DirectionalLight3D Sun { get; init; }
    public required DirectionalLight3D Fill { get; init; }
    public required DirectionalLight3D HemiUp { get; init; }
    public required DirectionalLight3D HemiDown { get; init; }
    public required Environment Env { get; init; }
    /// <summary>The terrain's water material (its <c>tw_sky</c>), asked at every apply — the ground may come later.</summary>
    public System.Func<ShaderMaterial?>? Water { get; init; }

    private double? _hour;
    private AmbienceState _ambience = AmbienceState.Neutral;
    private bool _dirty = true;
    private ShaderMaterial? _water;
    private DistanceFog? _fog;

    /// <summary>
    /// The distance fog pass (<c>scene.fog</c>): its colour is the clock's sky, written with the background
    /// (<c>setGameHour</c> copies the sky into both). Setting it hands it the current sky at once.
    /// </summary>
    public DistanceFog? Fog
    {
        get => _fog;
        set
        {
            _fog = value;
            _fog?.SetSky(Frame.Background.Linear);
        }
    }

    /// <summary>The frame last written (for the check and the log).</summary>
    public StageFrame Frame { get; private set; }

    /// <summary>The clock reading in force (null = none yet, the constructor's stage).</summary>
    public double? Hour => _hour;

    /// <summary>
    /// Builds the environment and the four directional lights under <paramref name="parent"/> (Main.BuildStage and the
    /// light check use the same nodes) and writes the stage before the first clock reading.
    /// </summary>
    public static StageAmbience Build(Node parent, System.Func<ShaderMaterial?>? water = null)
    {
        var env = new Environment
        {
            BackgroundMode = Environment.BGMode.Color,
            AmbientLightSource = Environment.AmbientSource.Color,
            AmbientLightSkyContribution = 0f,
            ReflectedLightSource = Environment.ReflectionSource.Disabled,
            TonemapMode = Environment.ToneMapper.Linear,
            TonemapExposure = 1f,
        };
        parent.AddChild(new WorldEnvironment { Name = "Env", Environment = env });
        var sun = new DirectionalLight3D
        {
            Name = "Sun",
            ShadowEnabled = true,
            // One shadow map like the browser's (ShadowFit): Godot's orthogonal mode is one split over the whole atlas.
            DirectionalShadowMode = DirectionalLight3D.ShadowMode.Orthogonal,
            DirectionalShadowMaxDistance = (float)ShadowFit.MaxDistanceM(Overview.OverviewControl.InitialDist),
            LightSpecular = 1f,
            SkyMode = DirectionalLight3D.SkyModeEnum.LightOnly,
        };
        var fill = new DirectionalLight3D { Name = "Fill", LightSpecular = 1f, SkyMode = DirectionalLight3D.SkyModeEnum.LightOnly };
        DirectionalLight3D Hemi(string name, bool negative) => new()
        {
            Name = name,
            LightSpecular = 0f,
            LightNegative = negative,
            ShadowEnabled = false,
            SkyMode = DirectionalLight3D.SkyModeEnum.LightOnly,
        };
        var up = Hemi("HemiSky", false);
        var down = Hemi("HemiGround", true);
        foreach (var l in new[] { sun, fill, up, down }) parent.AddChild(l);
        // The fill's target is the origin and never moves; the hemisphere pair points straight down / straight up.
        fill.Basis = LightBasisOf(StageLight.FillOffset);
        fill.Position = new Vector3((float)StageLight.FillOffset.X, (float)StageLight.FillOffset.Y, (float)StageLight.FillOffset.Z);
        up.Basis = LightBasisOf((0, 1, 0));
        down.Basis = LightBasisOf((0, -1, 0));
        var stage = new StageAmbience { Sun = sun, Fill = fill, HemiUp = up, HemiDown = down, Env = env, Water = water };
        stage.Flush();
        return stage;
    }

    /// <summary>
    /// three's <c>lookAt</c> basis for a light at <paramref name="offset"/> from its target (<see cref="ShadowSnap.Basis"/>):
    /// Godot's directional light shines along its −Z, which is then exactly from the offset towards the target, and its
    /// X/Y axes are the browser shadow camera's.
    /// </summary>
    public static Basis LightBasisOf((double X, double Y, double Z) offset)
    {
        var b = ShadowSnap.Basis(offset);
        static Vector3 V((double X, double Y, double Z) v) => new((float)v.X, (float)v.Y, (float)v.Z);
        return new Basis(V(b.X), V(b.Y), V(b.Z));
    }

    /// <summary><c>setGameHour(hour)</c>: the new clock base (the ambience stays applied on top).</summary>
    public void SetHour(double hour)
    {
        if (_hour == hour) return;
        _hour = hour;
        _dirty = true;
        Flush();
    }

    /// <summary><c>applyAmbience(daylight, tint)</c>: an unchanged state writes nothing.</summary>
    public void Apply(AmbienceState a)
    {
        // The ground (and its water material) may arrive after the clock: hand a new material the current sky.
        if (Water?.Invoke() is { } water && !ReferenceEquals(water, _water)) _dirty = true;
        if (a == _ambience && !_dirty) return;
        _ambience = a;
        _dirty = true;
        Flush();
    }

    /// <summary>
    /// The frame's sun: on the texel-snapped camera target (<c>snapShadowCentre</c>) at the clock's offset, shining
    /// towards it; the shadow's max distance follows the camera distance (<see cref="ShadowFit.MaxDistanceM"/>).
    /// </summary>
    public void Track(Vector3 target, double cameraDist)
    {
        var (_, pos) = StageLight.SunPlacement((target.X, target.Y, target.Z), Frame.SunAngle);
        var off = StageLight.SunOffset(Frame.SunAngle);
        Sun.Transform = new Transform3D(LightBasisOf(off), new Vector3((float)pos.X, (float)pos.Y, (float)pos.Z));
        float maxD = (float)ShadowFit.MaxDistanceM(cameraDist);
        if (Sun.DirectionalShadowMaxDistance != maxD) Sun.DirectionalShadowMaxDistance = maxD;
    }

    private static Color C(GodotSrgb c) => new((float)c.R, (float)c.G, (float)c.B);

    private void Flush()
    {
        if (!_dirty) return;
        _dirty = false;
        var f = StageLight.Compose(_hour, _ambience);
        Frame = f;
        Sun.LightColor = C(f.Sun.Color);
        Sun.LightEnergy = (float)f.Sun.Energy;
        Fill.LightColor = C(f.Fill.Color);
        Fill.LightEnergy = (float)f.Fill.Energy;
        Env.AmbientLightColor = C(f.Ambient.Color);
        Env.AmbientLightEnergy = (float)f.Ambient.Energy;
        foreach (var hemi in new[] { HemiUp, HemiDown })
        {
            hemi.LightColor = C(f.HemiPair.Color);
            hemi.LightEnergy = (float)f.HemiPair.Energy;
        }
        Env.BackgroundColor = C(f.Background);
        // The fog colour follows the sky (engine.ts: `scene.fog.color.copy(sky)`); the ambience does not touch it.
        if (_fog is not null && GodotObject.IsInstanceValid(_fog)) _fog.SetSky(f.Background.Linear);
        _water = Water?.Invoke();
        if (f.WaterSky is { } w)
        {
            // ONE sky for every water (surfaceSkyUniform): the terrain's water pixels and the prop water sheets.
            var sky = new Vector3((float)w.R, (float)w.G, (float)w.B);
            _water?.SetShaderParameter("tw_sky", sky);
            PropWaterSheets.SetSky(sky);
        }
    }
}
