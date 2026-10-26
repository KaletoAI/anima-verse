using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check</c>, labels part (Task 11): name tags, speech bubbles, location names and the performance readout on
/// the fixture world, against values derived BY HAND here (positions from native/fixtures/README.md, rules from
/// client3d/src/scene/nameTags.ts — the rules themselves are vector-checked in the C# tests).
///
/// Camera of every case: its own 1600 × 900 viewport, yaw 0 (lens on +Z looking −Z), pitch offset 0, target T =
/// Bram's feet (64, 4.0675, 132.32). Base pitch at 40 m = 18 + 44·√(39.2/149.2) = 40.55336239889695°
/// (sin 0.650245, cos 0.759729). A point P lies at the lens depth d − (Py − Ty)·sin p − (Pz − Tz)·cos p.
///
///   T1 tag anchors = feet + height + 0.45: Ada (−50, 3.595947265625 + 1.60 + 0.45 = 5.645947265625, 30), Bram
///      (64, 4.0675 + 1.80 + 0.45 = 6.3175, 132.32); Cleo has no model and no pool here, so she is a PORTRAIT and her
///      tag hangs below it (tagAnchorY(null) = −0.15, Task 29): (263, 4.875 − 0.15 = 4.725, −100).
///      Depths at 40 m: Ada 40 − 1.578447·0.650245 + 102.32·0.759729 = 116.709; Bram 40 − 2.25·0.650245 = 38.537;
///      Cleo 40 − 0.6575·0.650245 + 232.32·0.759729 = 216.075 — all between near 0.2 and far 800, so at 40 m ALL
///      three tags show (camDist 40 < 55); at 60 m NONE (60 ≥ 55), whatever the depth.
///   T2 texts: Ada "Ada Wren", Bram "Bram Holt", Cleo travels (travel block, starts_in_s null, no eta_hhmm) →
///      "🚶 Cleo Marsh"; no row has an activity → "" (no second line); the fixture has no avatar → none gold.
///   T3 projection = the inverse of the camera's ray: the ray through each projected tag passes its anchor (< 0.05 px
///      off), also with the chat panel's view shift applied (a frustum offset); Godot's UnprojectPosition is
///      compared and its offset reported.
///   B  bubble: say("Ada Wren", "  Hello   there ") at clock 1000 → "Hello there" (11 chars), until 1000 + 3500 +
///      55·11 = 5105: shown at 5104, gone at 5105 (now ≥ until). One line → box height 14.85 + 2·(5 + 1) = 26.85;
///      the tag grows by that + 4. A 140-character line wraps: the box is exactly 22ch wide. "Nobody" and a blank
///      line are ignored.
///   L  location labels: house, yard and meadow are all non-area places → 3 labels, anchored at ground datum +
///      height + 2.2: house (64, 4 + its building height + 2.2, 128), yard (−100, 2.91357421875 + 3 + 2.2 =
///      8.11357421875, 50), meadow unbuilt (300, 1.75 + 4 + 2.2 = 7.95, −200) — no distance LOD, so 3 at 40 m and
///      3 at 60 m.
///   P  perf: a box (24 vertices), a hidden subtree with a box, a multimesh of a box ×5 → 24 + 0 + 24 = 48 vertices;
///      the readout of 0.02 s frames goes out on the 15th frame (15 × 20 ms = 300 ms) with fps 15 / 0.3 = 50, and
///      nothing while perfOn is off.
/// </summary>
public static class LabelCheck
{
    private const string Ada = "Ada Wren", Bram = "Bram Holt", Cleo = "Cleo Marsh";
    private static readonly Vector3 Target = new(64, 4.0675f, 132.32f);

    public static async Task<string> RunAsync(Node3D host, Node3D world, WorldBuilder builder, string fixtures)
    {
        var vp = new SubViewport { Name = "LabelCheckViewport", Size = new Vector2I(1600, 900) };
        host.AddChild(vp);
        var cam = new OverviewCamera { Name = "LabelCheckCamera" };
        vp.AddChild(cam);
        var source = new FixtureSource(fixtures);
        var mgr = new FigureManager(source, builder.Height!, line => GD.Print("[check-labels] " + line), strict: true) { ClipFit = ClipFitMode.OnDemandSync, AutoTick = false, Slots = () => builder.Slots };
        world.AddChild(mgr);
        try
        {
            cam.Current = true;
            cam.SetProcess(false);
            cam.Control.Yaw = cam.Control.TargetYaw = 0;
            await mgr.InitAsync();
            using var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "worldmap.json")));
            await mgr.Apply(map.RootElement);

            double clock = 1000;
            var tags = new NameTags(mgr, () => clock) { CamDist = () => cam.Distance };
            tags.Apply(map.RootElement);
            var rows = LocationInfo.ParseList(builder.FirstMap!.Value).ToDictionary(l => l.Id);
            var places = new LocationLabels();
            places.Sync(builder.Known, rows);
            var overlay = new LabelOverlay { Camera = cam };
            overlay.Sources.Add(tags.Visible);
            overlay.Sources.Add(() => places.Visible(id => PickCheck.PlaceOfFor(builder, rows, id)));
            vp.AddChild(overlay);
            var size = new Vector2(1600, 900);
            Expect("overlay ignores the mouse", overlay.MouseFilter == Control.MouseFilterEnum.Ignore, $"{overlay.MouseFilter}");

            // ---- T2 texts ----
            Expect("T2 tags", tags.Tags.Keys.OrderBy(k => k).SequenceEqual(new[] { Ada, Bram, Cleo }), string.Join(",", tags.Tags.Keys));
            Expect("T2 names", tags.Tags[Ada].NameText == Ada && tags.Tags[Bram].NameText == Bram && tags.Tags[Cleo].NameText == "🚶 Cleo Marsh",
                   string.Join("|", tags.Tags.Values.Select(t => t.NameText)));
            Expect("T2 no activity, no avatar", tags.Tags.Values.All(t => t.ActivityText == "" && !t.IsAvatar), "");

            // ---- T1 visibility at 40 m and 60 m ----
            Frame(cam, 40);
            var at40 = overlay.Collect(size, cullOffscreen: false);
            var tags40 = at40.Where(p => p.Label is NameTags.Tag).ToList();
            Expect("T1 all tags at 40 m", tags40.Count == 3, $"{tags40.Count}");
            NearV("T1 Ada anchor", tags.Tags[Ada].Anchor, new Vector3(-50, 5.645947265625f, 30));
            NearV("T1 Bram anchor", tags.Tags[Bram].Anchor, new Vector3(64, 6.3175f, 132.32f));
            NearV("T1 Cleo anchor", tags.Tags[Cleo].Anchor, new Vector3(263, 4.725f, -100));
            Near("T1 Ada depth", Depth(cam, tags.Tags[Ada].Anchor), 116.709, 0.02);
            Near("T1 Bram depth", Depth(cam, tags.Tags[Bram].Anchor), 38.537, 0.02);
            Near("T1 Cleo depth", Depth(cam, tags.Tags[Cleo].Anchor), 216.075, 0.02);
            // Far → near: Cleo, Ada, Bram (the nearest drawn last, on top).
            Expect("T1 order far → near", tags40.Select(p => ((NameTags.Tag)p.Label).Character).SequenceEqual(new[] { Cleo, Ada, Bram }),
                   string.Join(",", tags40.Select(p => ((NameTags.Tag)p.Label).Character)));
            int onScreen40 = overlay.Collect(size).Count(p => p.Label is NameTags.Tag);
            double err = tags40.Max(p => RayErrorPx(cam, p.Label.Anchor, p.Screen));
            Expect("T3 projection = inverse of the camera ray", err < 0.05, $"{err} px");
            double godot = tags40.Max(p => (cam.UnprojectPosition(p.Label.Anchor) - p.Screen).Length());
            int places40 = at40.Count(p => p.Label is LocationLabels.PlaceLabel);

            Frame(cam, 60);
            var at60 = overlay.Collect(size, cullOffscreen: false);
            Expect("T1 no tags at 60 m", at60.Count(p => p.Label is NameTags.Tag) == 0, $"{at60.Count(p => p.Label is NameTags.Tag)}");
            int places60 = at60.Count(p => p.Label is LocationLabels.PlaceLabel);
            Frame(cam, 54.99);
            Expect("T1 54.99 m: tags back", overlay.Collect(size, false).Count(p => p.Label is NameTags.Tag) == 3, "");
            Frame(cam, 55);
            Expect("T1 55 m: gone", overlay.Collect(size, false).Count(p => p.Label is NameTags.Tag) == 0, "");

            // ---- T3 with the view shift (chat panel open on the right) ----
            Frame(cam, 40);
            cam.SetChatBox(new HudRect(1100, 100, 450, 700));
            for (int i = 0; i < 180; i++) cam.Step(1.0 / 60);
            var shift = cam.ViewShiftPx;
            Expect("T3 a view shift is applied", Math.Abs(shift.Dx) > 10, $"{shift}");
            var shifted = overlay.Collect(size, false).Where(p => p.Label is NameTags.Tag).ToList();
            double errShift = shifted.Max(p => RayErrorPx(cam, p.Label.Anchor, p.Screen));
            Expect("T3 shifted projection = inverse of the shifted ray", errShift < 0.05, $"{errShift} px");
            double godotShift = shifted.Max(p => (cam.UnprojectPosition(p.Label.Anchor) - p.Screen).Length());
            var bramShifted = shifted.Single(p => ((NameTags.Tag)p.Label).Character == Bram).Screen;
            var bramPlain = tags40.Single(p => ((NameTags.Tag)p.Label).Character == Bram).Screen;
            cam.SetChatBox(null);
            for (int i = 0; i < 180; i++) cam.Step(1.0 / 60);

            // ---- B bubbles ----
            var ada = tags.Tags[Ada];
            float plainH = ada.Size.Y;
            Expect("B unknown speaker ignored", !tags.Say("Nobody", "hello"), "");
            Expect("B blank line ignored", !tags.Say(Ada, "  \n "), "");
            Expect("B say", tags.Say(Ada, "  Hello   there "), "");
            Expect("B text", ada.BubbleText == "Hello there", ada.BubbleText);
            Near("B until", ada.BubbleUntilMs, 5105, 1e-9);
            Expect("B one line", ada.BubbleLines == 1, $"{ada.BubbleLines}");
            Near("B box height", ada.BubbleBoxSize.Y, 26.85, 1e-3);
            float maxW = NameTags.Tag.BubbleMaxWidth();
            Expect("B short box narrower than 22ch", ada.BubbleBoxSize.X < maxW && ada.BubbleBoxSize.X > 20, $"{ada.BubbleBoxSize.X} / {maxW}");
            Near("B tag grows by the bubble", ada.Size.Y - plainH, 26.85 + 4, 1e-3);
            clock = 5104;
            tags.Expire();
            Expect("B shown at 5104", ada.BubbleText == "Hello there", "gone early");
            clock = 5105;
            tags.Expire();
            Expect("B gone at 5105", ada.BubbleText == "" && ada.BubbleLines == 0, ada.BubbleText);
            Near("B tag shrinks back", ada.Size.Y, plainH, 1e-4);
            string longLine = string.Join(" ", Enumerable.Repeat("words", 40));   // 239 chars → cut to 140
            tags.Say(Ada, longLine);
            Expect("B long line cut", ada.BubbleText.Length == 140 && ada.BubbleText.EndsWith('…'), $"{ada.BubbleText.Length}");
            Expect("B long line wraps", ada.BubbleLines > 1, $"{ada.BubbleLines}");
            Near("B wrapped box is 22ch wide", ada.BubbleBoxSize.X, maxW, 0.01);
            int wrapLines = ada.BubbleLines;
            clock = 1e9;
            tags.Expire();

            // ---- L location labels ----
            Expect("L labels", places.Labels.Keys.OrderBy(k => k).SequenceEqual(new[] { "loc-house", "loc-meadow", "loc-yard" }),
                   string.Join(",", places.Labels.Keys));
            var houseH = builder.Slots["loc-house"].Height;
            NearV("L house anchor", places.Labels["loc-house"].Anchor, new Vector3(64, (float)(4 + houseH + 2.2), 128));
            NearV("L yard anchor", places.Labels["loc-yard"].Anchor, new Vector3(-100, 8.11357421875f, 50));
            NearV("L meadow anchor", places.Labels["loc-meadow"].Anchor, new Vector3(300, 7.95f, -200));
            Expect("L 3 at 40 m and 60 m", places40 == 3 && places60 == 3, $"{places40} / {places60}");
            Expect("L names", places.Labels["loc-house"].Name == "Harbour House", places.Labels["loc-house"].Name);
            float caps = LabelStyle.Line("HARBOUR HOUSE", LabelStyle.Serif, LabelStyle.LocSize).GetSize().X;
            float lower = LabelStyle.Line("Harbour House", LabelStyle.Serif, LabelStyle.LocSize).GetSize().X;
            float small = places.Labels["loc-house"].Size.X;
            Expect("L small caps narrower than capitals", small < caps && small > 0, $"{small} vs {caps} (plain {lower})");
            // A dropped place loses its label; an area location never gets one.
            var less = builder.Known.Where(id => id != "loc-meadow").ToList();
            places.Sync(less, rows);
            Expect("L dropped place", !places.Labels.ContainsKey("loc-meadow"), "kept");

            // ---- emoji in a name ----
            var walker = LabelStyle.Line("🚶", LabelStyle.SansSemiBold, LabelStyle.NameSize).GetSize();
            Expect("emoji in a name has a size", walker.X > 4 && walker.X < 24, $"{walker}");

            // ---- cost: 60 tags shaped and collected ----
            var sw = Stopwatch.StartNew();
            var many = new List<NameTags.Tag>();
            for (int i = 0; i < 60; i++)
            {
                var t = new NameTags.Tag($"Figure {i}");
                t.SetText($"🚶 12:{i % 60:00} Figure {i}", "walking to the harbour", false);
                t.Anchor = Target + new Vector3(i % 10 - 5, 2, -(i / 10) * 3);
                many.Add(t);
            }
            double shapeMs = sw.Elapsed.TotalMilliseconds;
            var heavy = new LabelOverlay { Camera = cam };
            heavy.Sources.Add(() => many);
            vp.AddChild(heavy);
            heavy.Collect(size);
            sw.Restart();
            const int Rounds = 100;
            int shown = 0;
            for (int r = 0; r < Rounds; r++) shown = heavy.Collect(size).Count;
            double collectMs = sw.Elapsed.TotalMilliseconds / Rounds;
            heavy.QueueFree();

            // ---- P perf ----
            var perf = CheckPerf(host);

            return $"labels T1..P ok (tags at 40 m 3 of 3 ({onScreen40} on screen), at 60 m 0; places 3/3; projection "
                   + $"{err:0.####} px, shifted ({shift.Dx:0.#},{shift.Dy:0.#}) px {errShift:0.####} px — Godot UnprojectPosition off by "
                   + $"{godot:0.###} px plain, {godotShift:0.###} px shifted; Bram moved {(bramShifted - bramPlain).Length():0.#} px; "
                   + $"bubble 22ch = {maxW:0.#} px, 140 chars in {wrapLines} lines; 🚶 {walker.X:0.#}×{walker.Y:0.#} px; "
                   + $"60 tags shaped {shapeMs:0.##} ms, collected {collectMs:0.###} ms/frame ({shown} on screen); {perf})";
        }
        finally
        {
            mgr.QueueFree();
            vp.QueueFree();
        }
    }

    /// <summary>The camera on <see cref="Target"/> at <paramref name="dist"/>, yaw 0, one zero-length frame.</summary>
    private static void Frame(OverviewCamera cam, double dist)
    {
        cam.JumpTo(Target, dist);
        cam.Step(0);
    }

    /// <summary>The lens depth of a world point (metres in front of the camera).</summary>
    private static double Depth(Camera3D cam, Vector3 p) => -(cam.GlobalTransform.AffineInverse() * p).Z;

    /// <summary>How far (in px at the point's depth) the ray through <paramref name="screen"/> passes the world point.</summary>
    private static double RayErrorPx(OverviewCamera cam, Vector3 p, Vector2 screen)
    {
        var (o, d) = cam.RayAt(screen);
        var op = new Vec3(p.X - o.X, p.Y - o.Y, p.Z - o.Z);
        double along = op.X * d.X + op.Y * d.Y + op.Z * d.Z;
        double dx = op.X - along * d.X, dy = op.Y - along * d.Y, dz = op.Z - along * d.Z;
        double off = Math.Sqrt(dx * dx + dy * dy + dz * dz);
        double pxPerM = 900 / (2 * Math.Tan(Math.PI / 8) * Depth(cam, p));
        return off * pxPerM;
    }

    private static string CheckPerf(Node3D host)
    {
        var root = new Node3D { Name = "PerfTree" };
        host.AddChild(root);
        try
        {
            root.AddChild(new MeshInstance3D { Mesh = new BoxMesh() });
            var hidden = new Node3D { Visible = false };
            hidden.AddChild(new MeshInstance3D { Mesh = new BoxMesh() });
            root.AddChild(hidden);
            var mm = new MultiMesh { TransformFormat = MultiMesh.TransformFormatEnum.Transform3D, Mesh = new BoxMesh(), InstanceCount = 5 };
            root.AddChild(new MultiMeshInstance3D { Multimesh = mm });
            long verts = PerfProbe.VisibleVertices(root);
            Expect("P visible vertices", verts == 48, $"{verts}");

            var probe = new PerfProbe();
            Expect("P off sends nothing", probe.Frame(false, 0.02, root) is null, "sent");
            System.Text.Json.Nodes.JsonObject? sent = null;
            int at = 0;
            for (int i = 1; i <= 15 && sent is null; i++)
            {
                sent = probe.Frame(true, 0.02, root);
                at = i;
            }
            Expect("P first readout on frame 15", sent is not null && at == 15, $"frame {at}");
            Near("P fps", (double)sent!["fps"]!, 50, 1e-9);
            Expect("P vertices in the readout", (long)sent["vertices"]! == 48, sent["vertices"]!.ToJsonString());
            Expect("P every key", sent.Count == 11, sent.ToJsonString());
            Expect("P off again", probe.Frame(false, 0.02, root) is null, "sent");
            return $"perf vertices {verts}, readout at frame {at}, fps {(double)sent["fps"]!:0.#}";
        }
        finally
        {
            root.QueueFree();
        }
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"labels {what}: {detail}");
    }

    private static void Near(string what, double got, double want, double eps)
        => Expect(what, Math.Abs(got - want) <= eps, $"got {got}, expected {want}");

    private static void NearV(string what, Vector3 got, Vector3 want, float eps = 1e-3f)
        => Expect(what, got.DistanceTo(want) <= eps, $"got {got}, expected {want}");
}
