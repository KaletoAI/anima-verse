using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 55 / E7-T10: real native world/figures on fixtures/embody. The 64m frame gives a .24m
/// anchor step; (-3,1) and (24,0) are the two locally snapped avatar positions while its poll stays (-3,1).
/// The rock polygon remains catalog #555555, three known places retain IDs/names, and the 65x33 relief
/// keeps all 8580 numeric RGBA channels. Steps/orbits reuse the very same relief JSON; a height revision
/// replaces it. Leaving the actual EmbodyMode publishes null exactly once, re-entry clears the anchor.</summary>
public static class MinimapCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var source = new FixtureSource(Path.Combine(fixtures, "embody"), fixtures);
        var world = new Node3D { Name = "MinimapWorld" }; host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        int count = 0;
        void Is(string name, bool ok) { count++; if (!ok) throw new InvalidOperationException("minimap " + name); }
        try
        {
            await builder.BuildAsync(world, "Fixture Hall");
            var figures = new FigureManager(source, builder.Height!, _ => { }, strict: true)
            {
                AutoTick = false, ClipFit = ClipFitMode.OnDemandSync, Slots = () => builder.Slots,
                GroundMoveAt = builder.FigureGroundMove, GroundYAt = builder.FigureGroundY,
            };
            world.AddChild(figures); await figures.InitAsync();
            using var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "embody", "worldmap.json")));
            await figures.Apply(map.RootElement); await figures.EnsurePool();
            var avatar = figures.Figures["fixture-avatar"];
            figures.SetPlayerDriven(avatar.CharacterName);
            var camera = new OverviewControl();
            var mode = new EmbodyMode(camera, () => new(avatar.Position.X, avatar.Position.Y, avatar.Position.Z),
                () => new(avatar.Eye.X, avatar.Eye.Y, avatar.Eye.Z));
            var minimap = new SceneMinimap();
            bool Tick(double dt = .25) => minimap.Tick(dt, mode.Active, builder, figures, camera.Yaw);
            Is("initial overview silent", !Tick() && minimap.State is null);
            mode.Enter(); camera.Yaw = Math.PI / 2;
            figures.SnapPlayerTo(avatar.CharacterName, new(-3, .01f, 1));
            Is("before cadence silent", !Tick(.249));
            Is("first embodied publish", Tick(.001));
            string first = HudProtocol.Minimap(minimap.State);
            using var d = JsonDocument.Parse(first);
            var value = d.RootElement.GetProperty("value");
            Is("v3 minimap", d.RootElement.GetProperty("v").GetInt32() == 3 && d.RootElement.GetProperty("kind").GetString() == "minimap");
            int fields = 0; foreach (var _ in value.EnumerateObject()) fields++;
            Is("six fields", fields == 6);
            Is("first avatar -3,1", value.GetProperty("avatar").GetProperty("x").GetDouble() == -3 && value.GetProperty("avatar").GetProperty("z").GetDouble() == 1);
            Is("follow yaw pi/2", value.GetProperty("yaw").GetDouble() == Math.PI / 2);
            var areas = value.GetProperty("areas");
            Is("one rock area", areas.GetArrayLength() == 1 && areas[0].GetProperty("color").GetString() == "#555555");
            Is("polygon first point", areas[0].GetProperty("polygon")[0][0].GetDouble() == 8 && areas[0].GetProperty("polygon")[0][1].GetDouble() == 8);
            var dots = value.GetProperty("locations");
            Is("three known locations", dots.GetArrayLength() == 3);
            Is("known meadow", dots[1].GetProperty("id").GetString() == "loc-free" && dots[1].GetProperty("name").GetString() == "Fixture Meadow"
                && dots[1].GetProperty("x").GetDouble() == 24 && dots[1].GetProperty("z").GetDouble() == 0);
            var bounds = value.GetProperty("bounds");
            Is("world bounds", bounds.GetProperty("min_x").GetDouble() == -16 && bounds.GetProperty("min_z").GetDouble() == -16
                && bounds.GetProperty("max_x").GetDouble() == 48 && bounds.GetProperty("max_z").GetDouble() == 16);
            var relief = value.GetProperty("relief");
            Is("relief placement", relief.GetProperty("origin_x").GetDouble() == -16 && relief.GetProperty("origin_z").GetDouble() == -16 && relief.GetProperty("step_m").GetDouble() == 1);
            var image = relief.GetProperty("image"); var data = image.GetProperty("data");
            Is("65x33 numeric array", image.GetProperty("cols").GetInt32() == 65 && image.GetProperty("rows").GetInt32() == 33
                && data.ValueKind == JsonValueKind.Array && data.GetArrayLength() == 8580);
            Is("flat point transparent", data[0].GetInt32() == 128 && data[3].GetInt32() == 0);
            // The first step support point (x=9,z=0) sees a central .5 gradient, zFactor3 -> grey146/alpha74.
            int p = (16 * 65 + 25) * 4;
            Is("step shades with factor3", data[p].GetInt32() == 146 && data[p + 3].GetInt32() == 74);
            string cached = minimap.State!.ReliefJson;
            Is("unchanged no publish", !Tick());
            figures.SnapPlayerTo(avatar.CharacterName, new(-2.9f, .01f, 1));
            Is("subpixel walk no publish", !Tick());
            figures.SnapPlayerTo(avatar.CharacterName, new(24, .01f, 0));
            Is("second position publishes", Tick());
            using var second = JsonDocument.Parse(HudProtocol.Minimap(minimap.State));
            var secondDot = second.RootElement.GetProperty("value").GetProperty("avatar");
            Is("second avatar 24,0", secondDot.GetProperty("x").GetDouble() == 24 && secondDot.GetProperty("z").GetDouble() == 0);
            Is("step no relief rebuild", ReferenceEquals(cached, minimap.State!.ReliefJson));
            camera.Yaw += .4 * Math.PI / 180;
            Is("fraction degree no publish", !Tick());
            camera.Yaw += .2 * Math.PI / 180;
            Is("whole degree publishes", Tick());
            Is("orbit no relief rebuild", ReferenceEquals(cached, minimap.State!.ReliefJson));
            builder.Height!.Reset(builder.Height.Overview);
            Is("height revision publishes", Tick());
            Is("height revision rebuilds JSON", !ReferenceEquals(cached, minimap.State!.ReliefJson));
            cached = minimap.State.ReliefJson;
            mode.Exit();
            Is("exit publishes null", Tick() && minimap.State is null);
            using var outside = JsonDocument.Parse(HudProtocol.Minimap(minimap.State));
            Is("outside wire null", outside.RootElement.GetProperty("value").ValueKind == JsonValueKind.Null);
            Is("outside silent thereafter", !Tick());
            mode.Enter(); figures.SnapPlayerTo(avatar.CharacterName, new(0, 0, 0));
            Is("re-entry fresh anchor", Tick() && minimap.State!.Avatar is { X: 0, Z: 0 });
            Is("re-entry reuses relief", ReferenceEquals(cached, minimap.State!.ReliefJson));
            return $"minimap cases={count} positions=-3,1/24,0 rgba=8580 wire_bytes={Encoding.UTF8.GetByteCount(first)} step_rebuild=0 height_rebuild=1 outside=null";
        }
        finally
        {
            builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree();
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }
    }
}
