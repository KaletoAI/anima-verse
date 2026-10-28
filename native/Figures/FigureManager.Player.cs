using System;
using System.Text.Json;
using AnimaNative.Scatter;
using Godot;

namespace AnimaNative.Figures;

/// <summary>Task 49 / E7-T4: npcs.ts player ownership; movement continues through the ordinary figure tick.</summary>
public partial class FigureManager
{
    public string? PlayerDriven { get; private set; }
    private string? _playerAnimation;
    /// <summary>Task 50: keep the controlled identity while E6 owns its movement; suppression survives cached placement.</summary>
    public bool ServerDriven { get; private set; }
    /// <summary>Task 50: preserve an owned route across polls requested before a local correction/seat write.</summary>
    public bool HoldAvatarPlacement { get; set; }
    public Func<string?, bool>? SuppressAvatarJourney { get; set; }
    public event Action<JsonElement, double>? PositionMapApplying;
    public event Action<JsonElement, double>? PositionMapApplied;
    public event Action? AfterTick;
    public bool IsPlayerDriven(string name) => name == PlayerDriven && !ServerDriven;

    /// <summary>Task 50: SERVER keeps E6 routes; input takes over at the rendered point, arrival at the server point.</summary>
    public void SetServerDriven(bool server, Vector3? arriveAt = null)
    {
        if (ServerDriven == server) return;
        ServerDriven = server;
        _playerAnimation = null;
        if (PlayerDriven is { } name && _figures.TryGetValue(name, out var f))
        {
            if (!server) { TakeOver(f); if (arriveAt is { } at) SnapPlayerTo(name, at); }
            else if (_lastPlans.TryGetValue(name, out var plan)) ApplyPlan(f, plan, false);
        }
    }
    /// <summary>Steering runs immediately before figures step, including manually advanced check frames.</summary>
    public event Action<double>? BeforeTick;
    public MeshInstance3D? WalkTarget { get; private set; }

    /// <summary>Clear all competing placement goals on takeover, including a takeover before the first poll.</summary>
    public void SetPlayerDriven(string? name)
    {
        if (name == PlayerDriven) return;
        PlayerDriven = name;
        ServerDriven = false;
        HoldAvatarPlacement = false;
        _playerAnimation = null;
        if (name is not null && _figures.TryGetValue(name, out var f)) TakeOver(f);
        if (name is null) SetWalkTarget(null);
    }

    private static void TakeOver(Figure f)
    {
        f.Route = null; f.Reckon = null; f.Travelling = false; f.DropTravelLine();
        f.Waypoints.Clear(); f.Ride = null; f.Target = f.Position; f.Settle = null; f.Pace = 1;
        f.Face = null; f.SetHidden(false);
    }

    /// <summary>Task 49: pace scales the step, never the fixed lead; invalid pace restores walking speed.</summary>
    public void SetPlayerTarget(string name, Vector3 goal, double pace = 1)
    {
        if (!_figures.TryGetValue(name, out var f)) return;
        f.Target = goal;
        f.Pace = double.IsFinite(pace) && pace > 0 ? pace : 1;
    }

    /// <summary>Task 51 / E7-T6: avatar climbs through the same ramp and swept landing tick as NPCs.</summary>
    public void SetStairRide(string name, AnimaNative.Scene.StairRide? ride)
    { if (_figures.TryGetValue(name, out var f)) f.Ride = ride; }

    /// <summary>Task 49: correction/teleport resets competing routes, climb, pace and secondary motion.</summary>
    public void SnapPlayerTo(string name, Vector3 point)
    {
        if (!_figures.TryGetValue(name, out var f)) return;
        f.SnapTo(point); f.Route = null; f.Reckon = null; f.Settle = null; f.Pace = 1;
        f.DropTravelLine();
    }

    /// <summary>Task 49: poll activity remains observable; held steering overrides it until release, once.</summary>
    public void SetPlayerAnimation(string name, string? animation)
    {
        if (name != PlayerDriven || !_figures.TryGetValue(name, out var f)) return;
        _playerAnimation = animation;
        f.Activity = animation ?? "";
    }

    /// <summary>Task 49: transfer completed bridge root motion once; move the goal equally so idle cannot walk back.</summary>
    public P2? TakePlayerTravel(string name)
    {
        if (!_figures.TryGetValue(name, out var f) || f.Bridging || !f.HoldsTravel || f.TakeTravel() is not { } t) return null;
        var offset = new Vector3((float)t.X, 0, (float)t.Z);
        f.Position += offset; f.Target += offset;
        return new(f.Position.X, f.Position.Z);
    }

    /// <summary>Task 49: unpickable world-space ring, browser radius .55, inner .72, lift .06; no custom shader.</summary>
    public void SetWalkTarget(Vector3? point)
    {
        if (point is not { } p) { if (WalkTarget is not null) WalkTarget.Visible = false; return; }
        if (WalkTarget is null)
        {
            var vertices = new Vector3[32*6];
            for (int i=0; i<32; i++)
            {
                double a = i*Math.Tau/32, b = (i+1)*Math.Tau/32;
                Vector3 At(double angle, double radius) => new((float)(Math.Cos(angle)*radius),0,(float)(Math.Sin(angle)*radius));
                var ao = At(a,.55); var ai = At(a,.55*.72); var bo = At(b,.55); var bi = At(b,.55*.72);
                int j=i*6; vertices[j]=ao; vertices[j+1]=ai; vertices[j+2]=bo;
                vertices[j+3]=ai; vertices[j+4]=bi; vertices[j+5]=bo;
            }
            var arrays = new Godot.Collections.Array(); arrays.Resize((int)Mesh.ArrayType.Max);
            arrays[(int)Mesh.ArrayType.Vertex] = vertices;
            var mesh = new ArrayMesh(); mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
            WalkTarget = new MeshInstance3D { Name = "WalkTarget", Mesh = mesh,
                CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
                MaterialOverride = new StandardMaterial3D { ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
                    Transparency = BaseMaterial3D.TransparencyEnum.Alpha, CullMode = BaseMaterial3D.CullModeEnum.Disabled,
                    AlbedoColor = new Color("f2d98c", .8f) } };
            AddChild(WalkTarget);
        }
        WalkTarget.Position = p + Vector3.Up*.06f;
        WalkTarget.Visible = true;
    }
}
