using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Scene;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check storeys</c> (part of every <c>--check</c>, Task 16): the storey switch at runtime, on the hand-written
/// multi-storey world <c>fixtures/storeys/</c> (README "Storeys world"), against numbers derived there by hand:
///
///   S1 the mount: every storey mounted once (interior primitives 11 + 2, room groups, door marks 3 on 3 storeys, the
///      boundary mark, 4 room labels), the build's view (storey 0) in the stats, § B5a over every storey;
///   S2 for the tower at storeys 0, 1 and −1 (fade 1): which room groups, slabs and outline walls stand, which room
///      plates wear their solid twin, which door-mark storey shows, which labels are drawn where, where the switch
///      floats and which button is active — and that nothing was rebuilt or fetched;
///   S3 the basement hole: off at storey 0 and 1, the tower's rectangle grown towards the camera at −1, off again when
///      the location closes; the pit's display-ground model hides at −1 (fade &gt; 0.03) and comes back;
///   S4 the lock look: a locked room behind a doorway paints it red (only in the avatar's location, the avatar's own
///      room left out), a refused location shows its boundary mark;
///   S5 the switch takes the pointer like the browser's: a click on a button sets the storey and the camera sees no
///      click; a right-drag starting on the switch turns nothing; a click beside it is the camera's.
/// </summary>
public static class StoreysCheck
{
    private const float Datum = 3.875f;                // tile ground (64, 120) = 2·1 + 1.875
    private const float PitDatum = 4.693359375f;       // overview (−40, 100), README "S3c world"
    private const float Tol = 1e-4f;

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "storeys");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "StoreysWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-storeys] " + line), strict: true);
        var vp = new SubViewport { Name = "StoreysViewport", Size = new Vector2I(1600, 900), HandleInputLocally = true };
        try
        {
            var stats = await builder.BuildAsync(world, "Tower");
            var tower = builder.Slots["loc-tower"];
            var pit = builder.Slots["loc-pit"];

            // ---- S1 the mount ----
            Expect("S1 tower open at storey 0", stats.OpenLocation == "loc-tower" && tower.Open && tower.LevelFilter == 0, stats.OpenLocation);
            Expect("S1 pit near, openable, closed", pit.Ring == Ring.Near && pit.Openable && !pit.Open, "");
            Eq("S1 interior mounted", stats.Recipe.InteriorMounted, 13);
            Eq("S1 primitives (storey 0)", stats.Recipe.Primitives, 6);
            Eq("S1 storey", stats.Recipe.Storey, 6);
            Eq("S1 interior", stats.Recipe.Interior, 2);
            Eq("S1 culled walls", stats.Recipe.CulledWalls, 2);
            Eq("S1 model storey", stats.Models.Storey, 2);
            Eq("S1 placeholders", stats.Models.Placeholders, 3);
            var tv = tower.Verify!;
            var pv = pit.Verify!;
            Expect("S1 tower verify", tv.Checked == 37 && tv.Rows.Count == 0 && tv.Placed == 2 && tv.Total == 2, tv.Headline());
            Expect("S1 pit verify", pv.Checked == 10 && pv.Rows.Count == 0 && pv.Placed == 1 && pv.Total == 1, pv.Headline());
            var st = tower.Storeys;
            Expect("S1 room groups", string.Join(",", st.Rooms.Values.Select(r => $"{r.Id}:{r.Level}:{(r.Outdoor ? "out" : "in")}"))
                   == "r-cellar:-1:in,r-hall:0:in,r-study:1:in,r-terrace:1:out", string.Join(",", st.Rooms.Keys));
            Expect("S1 terrace off the tile", tower.Group.GetNodeOrNull("Room_r-terrace") is not null
                   && tower.Group.GetNodeOrNull("Interior/Room_r-study") is not null, "");
            Expect("S1 switch buttons", string.Join(" ", st.Buttons.Select(b => b.Label)) == "-1. EG 1.", string.Join(" ", st.Buttons.Select(b => b.Label)));
            Expect("S1 lift anchors the switch", st.Elevator == new Scatter.P2(4, -1.5), $"{st.Elevator}");
            Expect("S1 pit switch (storeys -1, 0)", string.Join(" ", pit.Storeys.Buttons.Select(b => b.Label)) == "-1. EG", "");
            var doors = st.DoorMeshes().ToList();
            Expect("S1 door marks", doors.Count == 3 && string.Join(",", doors.Select(d => d.Level)) == "-1,0,1", string.Join(",", doors.Select(d => d.Level)));
            CheckDoorMark(doors.Single(d => d.Level == 0).Mesh, 1.2f, 0.36f, -3, 0.02f, 4);
            CheckDoorMark(doors.Single(d => d.Level == 1).Mesh, 0.9f, 0.27f, -3, 3.22f, -4);
            CheckDoorMark(doors.Single(d => d.Level == -1).Mesh, 1f, 0.3f, 0, -2.98f, -4);
            Expect("S1 no door marks on the pit", pit.Storeys.DoorMarks is null, "");
            var bm = st.BoundaryMarks ?? throw new InvalidOperationException("storeys: no boundary marks");
            var gate = bm.GetChild<MeshInstance3D>(0);
            NearV("S1 boundary mark position", gate.Position, new Vector3(64, 3.83125f, 114));
            NearV("S1 boundary mark scale", gate.Scale, new Vector3(2, 1, 0.6f));
            Near("S1 boundary mark yaw", gate.Rotation.Y, 0);
            Expect("S1 boundary hidden (nothing refused)", !bm.Visible && bm.IsInsideTree(), "");
            Expect("S1 labels", string.Join(",", st.Labels.Select(l => l.Text)) == "Cellar,Hall,Study,Terrace"
                   && pit.Storeys.Labels.Count == 0, string.Join(",", st.Labels.Select(l => l.Text)));

            // ---- S2 the tower at storeys 0, 1, −1 ----
            int scenes = source.SceneRequests.Count;
            var group = tower.Group;
            tower.Fade.Snap(1);
            var cam = new Vector3(100, 30, 147);
            builder.TickView(0, cam);
            var mats = new Mats(tower);
            View(builder, tower, mats, 0, rooms: "r-hall,r-terrace", slabs: "", walls: "0,0", solid: "", doorLevel: 0,
                 labels: "Hall@(64,5.375,123),Terrace@(64,8.375,117)", switchY: Datum + 2, active: "EG");
            Expect("S2 desk hidden at 0", !group.GetNode<Node3D>("Interior/Room_r-study/Placeholder").IsVisibleInTree(), "");
            Expect("S2 SetLevel", builder.SetLevel("loc-tower", 1) && !builder.SetLevel("loc-tower", 5) && !builder.SetLevel("nowhere", 0), "");
            builder.TickView(0, cam);
            View(builder, tower, mats, 1, rooms: "r-study,r-terrace", slabs: "1", walls: "1", solid: "study,terrace", doorLevel: 1,
                 labels: "Study@(64,8.375,123),Terrace@(64,8.375,117)", switchY: Datum + 5, active: "1.");
            Expect("S2 desk shown at 1", group.GetNode<Node3D>("Interior/Room_r-study/Placeholder").IsVisibleInTree(), "");
            Expect("S2 hole off at 1", builder.Ground?.Hole is null, "");
            builder.SetLevel("loc-tower", -1);
            builder.TickView(0, cam);
            View(builder, tower, mats, -1, rooms: "r-cellar,r-terrace", slabs: "-1", walls: "-1", solid: "", doorLevel: -1,
                 labels: "Cellar@(64,2.375,120),Terrace@(64,8.375,117)", switchY: Datum - 1, active: "-1.");
            Expect("S2 barrel shown at -1", group.GetNode<Node3D>("Interior/Room_r-cellar/Placeholder").IsVisibleInTree(), "");
            Expect("S2 no rebuild, no request", ReferenceEquals(group, tower.Group) && source.SceneRequests.Count == scenes, "");

            // ---- S3 the basement hole and the ground model ----
            var ground = builder.Ground ?? throw new InvalidOperationException("storeys: no ground surfaces (the hole needs them)");
            NearHole("S3 tower hole at -1", ground.Hole, 60, 114, 77.6, 133.2);
            Expect("S3 hole uniforms", (float)ground.Material.GetShaderParameter("hole_on") == 1f
                   && ((Vector4)ground.Material.GetShaderParameter("hole_rect")).DistanceTo(new Vector4(60, 114, 77.6f, 133.2f)) < 1e-3f, "");
            builder.SetOpen("loc-tower", false);
            tower.Fade.Snap(0);
            builder.TickView(0, cam);
            Expect("S3 hole closes with the view", ground.Hole is null && (float)ground.Material.GetShaderParameter("hole_on") == 0f, "");
            Expect("S3 closed: terrace keeps the last displayed look (ghost at -1)", mats.Terrace.MaterialOverride is null, "");
            var pitModel = pit.Fade.GroundModels.Single();
            Expect("S3 pit model shown closed", pitModel.Visible, "");
            builder.SetOpen("loc-pit", true);
            pit.Fade.Snap(1);
            builder.SetLevel("loc-pit", -1);
            var pitCam = new Vector3(-10, 30, 140);
            builder.TickView(0, pitCam);
            Expect("S3 pit model hidden at -1", !pitModel.Visible, "");
            NearHole("S3 pit hole", ground.Hole, -44, 96, -31.2, 110.4);
            builder.SetLevel("loc-pit", 0);
            builder.TickView(0, pitCam);
            Expect("S3 pit model back at 0, hole off", pitModel.Visible && ground.Hole is null, "");
            builder.SetLevel("loc-pit", -1);
            pit.Fade.Snap(0.03);
            builder.TickView(0, pitCam);
            Expect("S3 at fade 0.03 nothing opens", pitModel.Visible && ground.Hole is null, "");
            builder.SetOpen("loc-pit", false);
            pit.Fade.Snap(0);

            // ---- S4 locks ----
            builder.SetLocks(new LockState(new Dictionary<string, string> { ["r-terrace"] = "" }, "loc-tower",
                                           new Dictionary<string, string> { ["loc-tower"] = "Gate closed" }, "r-hall"));
            Expect("S4 study↔terrace door locked, the others open",
                   doors.All(d => d.Mesh.MaterialOverride == (d.Level == 1 ? MarkLooks.Locked : MarkLooks.Open)), "");
            Expect("S4 refused location shows its boundary", bm.Visible, "");
            builder.SetLocks(new LockState(new Dictionary<string, string> { ["r-terrace"] = "" }, "loc-tower",
                                           new Dictionary<string, string>(), "r-terrace"));
            Expect("S4 standing on the terrace: nothing barred behind", doors.All(d => d.Mesh.MaterialOverride == MarkLooks.Open) && !bm.Visible, "");
            builder.SetLocks(new LockState(new Dictionary<string, string> { ["r-terrace"] = "" }, "loc-pit",
                                           new Dictionary<string, string>(), "r-hall"));
            Expect("S4 a lock map of another location paints nothing", doors.All(d => d.Mesh.MaterialOverride == MarkLooks.Open), "");
            Expect("S4 marks never picked", doors.All(d => d.Mesh.HasMeta(LocationFade.OverlayMeta)), "");

            // ---- S5 the switch takes the pointer ----
            builder.SetOpen("loc-tower", true);
            tower.Fade.Snap(1);
            builder.SetLevel("loc-tower", 0);
            builder.TickView(0, cam);
            var input = await PointerCheck(host, vp, builder, tower);

            return $"storeys S1..S5 ok (interior {stats.Recipe.InteriorMounted}, verify tower {tv.Checked} pit {pv.Checked}, "
                   + $"door marks {doors.Count}, labels {st.Labels.Count}, hole [60,114,77.6,133.2]; {input})";
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
            if (IsInstanceValidNode(vp)) vp.QueueFree();
        }
    }

    private static bool IsInstanceValidNode(Node n) => GodotObject.IsInstanceValid(n);

    /// <summary>The tower's recipe meshes by role (names carry the unit tag, README "Storeys world").</summary>
    private sealed class Mats
    {
        public readonly MeshInstance3D SlabMinus, SlabOne, WallMinus, WallHall, WallContour, WallStudy, Study, Terrace;

        public Mats(LocationSlot tower)
        {
            var g = tower.Group;
            SlabMinus = Mesh(g, "Interior", "_slab-1_");
            SlabOne = Mesh(g, "Interior", "_slab1_");
            WallMinus = Mesh(g, "Interior/Room_r-cellar", "_wall-1_");
            WallHall = Mesh(g, "Interior/Room_r-hall", "_wall0_");
            WallContour = Mesh(g, "Interior", "_wall0_");
            WallStudy = Mesh(g, "Interior/Room_r-study", "_wall1_");
            Study = Mesh(g, "Interior/Room_r-study", "_plate1_");
            Terrace = Mesh(g, "Room_r-terrace", "_plate1_");
        }

        private static MeshInstance3D Mesh(Node3D g, string path, string tag)
            => g.GetNode(path).GetChildren().OfType<MeshInstance3D>().Single(m => m.Name.ToString().Contains(tag));
    }

    /// <summary>One storey's expected view of the tower (README "Storeys world", the table S2).</summary>
    private static void View(WorldBuilder builder, LocationSlot tower, Mats m, int level, string rooms, string slabs, string walls,
                             string solid, int doorLevel, string labels, float switchY, string active)
    {
        string tag = $"S2 storey {level}";
        var st = tower.Storeys;
        var shownRooms = string.Join(",", st.Rooms.Values.Where(r => r.Node.IsVisibleInTree()).Select(r => r.Id));
        Expect($"{tag} rooms", shownRooms == rooms, shownRooms);
        var shownSlabs = string.Join(",", new[] { (m.SlabMinus, -1), (m.SlabOne, 1) }.Where(x => x.Item1.IsVisibleInTree()).Select(x => x.Item2));
        Expect($"{tag} slabs", shownSlabs == slabs, shownSlabs);
        var shownWalls = string.Join(",", new[] { (m.WallMinus, -1), (m.WallHall, 0), (m.WallContour, 0), (m.WallStudy, 1) }
                                         .Where(x => x.Item1.IsVisibleInTree()).Select(x => x.Item2));
        Expect($"{tag} outline walls", shownWalls == walls, shownWalls);
        var solids = string.Join(",", new[] { (m.Study, "study"), (m.Terrace, "terrace") }
                                     .Where(x => x.Item1.MaterialOverride is ShaderMaterial sm && (float)sm.GetShaderParameter("opacity") == 1f)
                                     .Select(x => x.Item2));
        Expect($"{tag} solid room plates", solids == solid, solids);
        if (!solid.Contains("terrace"))
        {
            var ghost = (ShaderMaterial)m.Terrace.Mesh.SurfaceGetMaterial(0);
            Near($"{tag} terrace ghost", (float)ghost.GetShaderParameter("opacity"), 0.4f);
        }
        var marks = st.DoorMarks!;
        var shownMarks = string.Join(",", marks.GetChildren().OfType<Node3D>().Where(n => n.IsVisibleInTree()).Select(n => (int)n.GetMeta("level")));
        Expect($"{tag} door marks", marks.Visible && shownMarks == doorLevel.ToString(), shownMarks);
        var drawn = builder.VisibleRoomLabels().Cast<RoomLabel>()
                           .Select(l => $"{l.Text}@({Round(l.Anchor.X)},{Round(l.Anchor.Y)},{Round(l.Anchor.Z)})");
        Expect($"{tag} labels", string.Join(",", drawn) == labels, string.Join(",", drawn));
        var local = StoreyView.SwitchPosition(st.Elevator, st.FloorY(tower.LevelFilter), tower.LevelFilter, st.StoreyM);
        var sw = tower.Group.GlobalTransform * new Vector3((float)local.X, (float)local.Y, (float)local.Z);
        NearV($"{tag} switch anchor", sw, new Vector3(62.5f, switchY, 116));
        var buttons = LevelSwitchOverlay.Arrange("loc-tower", st.Buttons, tower.LevelFilter, Vector2.Zero).Buttons;
        Expect($"{tag} active button", string.Join(",", buttons.Where(b => b.Active).Select(b => b.Label)) == active, "");
    }

    private static string Round(float v) => Math.Round(v, 3).ToString(System.Globalization.CultureInfo.InvariantCulture);

    private static void CheckDoorMark(MeshInstance3D mesh, float width, float depth, float x, float y, float z)
    {
        NearV("S1 door mark scale", mesh.Scale, new Vector3(width, 1, depth));
        NearV("S1 door mark position", mesh.Position, new Vector3(x, y, z));
        Near("S1 door mark yaw", mesh.Rotation.Y, 0);
        Expect("S1 door mark look", mesh.MaterialOverride == MarkLooks.Open && mesh.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off, "");
    }

    /// <summary>
    /// S5 through Godot's real input path (<see cref="Viewport.PushInput"/>): a camera and the switch overlay in a
    /// 1600 × 900 viewport, the camera on the switch's anchor.
    /// </summary>
    private static async Task<string> PointerCheck(Node3D host, SubViewport vp, WorldBuilder builder, LocationSlot tower)
    {
        host.AddChild(vp);
        var cam = new OverviewCamera { Name = "StoreysCamera" };
        vp.AddChild(cam);
        cam.Current = true;
        cam.SetProcess(false);
        cam.JumpTo(new Vector3(62.5f, Datum + 2, 116), 20);
        cam.Step(0);
        var overlay = new LevelSwitchOverlay { Camera = cam, Builder = builder, Size = new Vector2(1600, 900) };
        overlay.SetProcess(false);
        vp.AddChild(overlay);
        await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        overlay.Refresh();
        var shown = overlay.Shown;
        Expect("S5 one switch (the open tower)", shown.Count == 1 && shown[0].LocationId == "loc-tower", $"{shown.Count}");
        var box = shown[0].Box;
        Expect("S5 switch centred on its anchor", Math.Abs(box.GetCenter().X - 800) <= 1 && Math.Abs(box.GetCenter().Y - 450) <= 1, $"{box}");
        int clicks = 0;
        cam.Clicked += _ => clicks++;
        void Push(InputEvent e) => vp.PushInput(e);
        InputEventMouseButton Button(MouseButton b, bool pressed, Vector2 at)
            => new() { ButtonIndex = b, Pressed = pressed, Position = at, GlobalPosition = at, Factor = 1,
                       ButtonMask = pressed ? (b == MouseButton.Right ? MouseButtonMask.Right : MouseButtonMask.Left) : 0 };
        var one = shown[0].Buttons.Single(b => b.Label == "1.").Rect.GetCenter();
        Push(Button(MouseButton.Left, true, one));
        Push(Button(MouseButton.Left, false, one));
        Expect("S5 click on '1.' sets storey 1", tower.LevelFilter == 1, $"{tower.LevelFilter}");
        Expect("S5 the camera saw no click", clicks == 0, $"{clicks}");
        double yaw = cam.Control.TargetYaw;
        var eg = shown[0].Buttons.Single(b => b.Label == "EG").Rect.GetCenter();
        Push(Button(MouseButton.Right, true, eg));
        Push(new InputEventMouseMotion { Position = eg + new Vector2(120, 0), GlobalPosition = eg + new Vector2(120, 0), Relative = new Vector2(120, 0), ButtonMask = MouseButtonMask.Right });
        Push(Button(MouseButton.Right, false, eg + new Vector2(120, 0)));
        Expect("S5 right-drag from the switch turns nothing", cam.Control.TargetYaw == yaw && tower.LevelFilter == 1, $"{cam.Control.TargetYaw} vs {yaw}");
        var beside = new Vector2(200, 800);
        Push(Button(MouseButton.Left, true, beside));
        Push(Button(MouseButton.Left, false, beside));
        Expect("S5 a click beside the switch is the camera's", clicks == 1 && tower.LevelFilter == 1, $"{clicks}");
        return $"switch box {box.Size.X:0}×{box.Size.Y:0} px, click → storey 1, camera clicks {clicks}";
    }

    private static void NearHole(string what, double[]? hole, double a, double b, double c, double d)
    {
        Expect(what, hole is { Length: 4 } h && Math.Abs(h[0] - a) < 1e-3 && Math.Abs(h[1] - b) < 1e-3
                     && Math.Abs(h[2] - c) < 1e-3 && Math.Abs(h[3] - d) < 1e-3,
               hole is null ? "null" : string.Join(",", hole.Select(v => v.ToString("0.####"))));
    }

    private static void NearV(string what, Vector3 got, Vector3 want)
        => Expect(what, got.DistanceTo(want) < 1e-3f, $"got {got}, expected {want}");

    private static void Near(string what, double got, double want)
        => Expect(what, Math.Abs(got - want) < Tol, $"got {got}, expected {want}");

    private static void Eq(string what, int got, int want) => Expect(what, got == want, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"storeys {what}: {detail}");
    }
}
