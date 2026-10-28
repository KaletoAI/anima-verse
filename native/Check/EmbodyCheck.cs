using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task 48 / E7-T3, --check embody. Hand derivations from fixtures/embody/camera.json:
/// root (10,2,20), height 1.7 → standing eye (10,3.598,20), because .94*1.7=1.598.
/// Enter requests 7 m; 200 capped .05 s frames damp by exp(-rate*10), reaching 7 within 1e-9.
/// Wheel +10000 requests 7*exp(12)&gt;34, so stops at 34; repeated requests emit one session hint.
/// Wheel -10000 requests below .8, so stops at .8. First person requires EASED and requested zoom ≤1.2;
/// .10+.079=.179 is too short, +.001=.180 enters. Third person remains at least 2 m from the target.
/// Rest head y=1.4, crown y=1.8: eye y=1.4+.45*.4=1.58, z=.055*1.7=.0935;
/// translated by root → lens (10,3.58,20.0935). Pose +.2 y moves the lens +.2, ignoring render head scale.
/// Yaw 60° holds, strictly 61° turns. Exit clears follow/cap/floor and flies to root at 70 m.
/// Esc with menu open resolves menu; a second press can leave the mode. A modal/typing owns its Esc.
/// Controller regression: earlier sections can resume this check at a different point in the frame.
/// Advance queues a deferred skeleton pass; ProcessFrame alone is not its completion signal. Each pass
/// waits for SkeletonUpdated and a deferred barrier after Godot restores its CPU pose, with a 5 s deadline.
/// </summary>
public static class EmbodyCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(fixtures, "embody", "camera.json")));
        var data = doc.RootElement;
        Vector3 V(string key) { var a = data.GetProperty(key); return new(a[0].GetSingle(), a[1].GetSingle(), a[2].GetSingle()); }
        var root = V("root");
        double height = data.GetProperty("height").GetDouble();
        var vp = new SubViewport { Size = new Vector2I(800, 600), OwnWorld3D = true };
        host.AddChild(vp);
        var cam = new OverviewCamera { Current = true };
        vp.AddChild(cam);
        cam.SetProcess(false);
        var fig = new Figure(data.GetProperty("avatar").GetString()!) { HeightM = height, Position = root };
        vp.AddChild(fig);
        fig.FaceTowards(Vector3.Back, snap: true);
        var hud = new HudOverlay();

        int n = 0;
        void Is(string name, bool value) { n++; if (!value) throw new InvalidOperationException("embody " + name); }
        void Near(string name, double got, double want, double tol = 1e-5) => Is($"{name}: {got:R}, expected {want:R}", Math.Abs(got-want) <= tol);
        Vec3 Vec(Vector3 p) => new(p.X, p.Y, p.Z);
        var eye = root + Vector3.Up * (float)CameraFraming.EyeHeight(height);
        var mode = new EmbodyMode(cam.Control, () => Vec(fig.GlobalPosition), () => Vec(cam.FirstPerson ? fig.Lens : fig.Eye));
        int hints = 0, exits = 0;
        mode.CapHint += () => hints++;
        mode.Changed += () => hud.SetState("mode", mode.Active ? "embodied" : "overview");
        hud.Handlers["enterEmbodied"] = _ => mode.Enter();
        hud.Handlers["exitEmbodied"] = _ => { exits++; mode.Exit(); };
        cam.Posed += () => fig.SetFirstPerson(cam.FirstPerson);
        try
        {
            cam.JumpTo(Vector3.Zero, 70);
            Is("enter", mode.Enter());
            cam.Control.KeyDown("w");
            for (int i=0; i<200; i++) cam.Step(.05);
            Near("enter distance", cam.Distance, 7, 1e-9);
            Is("eye target", cam.Target.DistanceTo(eye) < 1e-5);
            Is("mode camera fields", cam.Follow is not null && cam.ZoomCap == 34 && cam.ZoomFloor == .8 && cam.NearPitchDeg == 8 && cam.OrbitOnDrag);
            cam.ZoomTo(new Vector3(90,0,90));
            Near("zoomTo ignored", cam.Control.TargetDist, 7);
            cam._UnhandledInput(new InputEventMouseButton { ButtonIndex = MouseButton.WheelDown, Pressed = true, Factor = 100 });
            for (int i=0; i<5; i++) cam.Control.Wheel(100, () => throw new Exception("follow must not raycast"));
            Near("cap", cam.Control.TargetDist, 34);
            Is("one hint", hints == 1);
            Is("repeat enter no-op", !mode.Enter());
            cam.Control.Wheel(100, () => null);
            Is("repeat enter preserves hint", hints == 1);
            cam._UnhandledInput(new InputEventMouseButton { ButtonIndex = MouseButton.WheelUp, Pressed = true, Factor = 100 });
            Near("floor", cam.Control.TargetDist, .8);
            cam.Step(.1);
            Is("eased zoom gate", !cam.FirstPerson);
            cam.Control.Dist = cam.Control.TargetDist = 1.2;
            cam.Step(.1); cam.Step(.079);
            Is("179 ms holds", !cam.FirstPerson);
            cam.Step(.001);
            Is("180 ms first person", cam.FirstPerson);
            Is("fallback lens exact", cam.GlobalPosition.DistanceTo(eye) < 1e-5);
            var body = new Node3D();
            var skel = new Skeleton3D(); body.AddChild(skel);
            skel.AddBone("mixamorig_Head");
            skel.SetBoneRest(0, new Transform3D(Basis.Identity, V("head")));
            skel.AddBone("mixamorig_HeadTop_End"); skel.SetBoneParent(1,0);
            skel.SetBoneRest(1, new Transform3D(Basis.Identity, V("crown")-V("head")));
            skel.ResetBonePoses();
            fig.SetBody(body, true, skel, null, bodyHeight: height);
            fig.SetFirstPerson(true);
            fig.FirstPersonBody!.StepNow();
            var lens = new Vector3(10, 3.58f, 20.0935f);
            Is("head lens", fig.Lens.DistanceTo(lens) < 1e-5);
            Near("head render scale", skel.GetBonePoseScale(0).X, .001, 1e-7);
            Is("body retained", body.Visible);
            fig.FirstPersonBody.RestoreHead();
            skel.SetBonePosePosition(0, V("head") + Vector3.Up * .2f);
            fig.FirstPersonBody.StepNow(); cam.RefreshFirstPerson();
            Is("posed lens exact", cam.GlobalPosition.DistanceTo(lens + Vector3.Up * .2f) < 1e-5);
            // Drive the actual Godot modifier pipeline, including its pose backup/restore across frames.
            fig.FirstPersonBody.RestoreHead();
            fig.HeadPosed += cam.RefreshFirstPerson;
            skel.ModifierCallbackModeProcess = Skeleton3D.ModifierCallbackModeProcessEnum.Manual;
            int renderHeads = 0;
            bool renderScaleCorrect = true;
            skel.SkeletonUpdated += () =>
            {
                if (!fig.FirstPersonBody.Enabled) return;
                renderHeads++;
                renderScaleCorrect &= Math.Abs(skel.GetBonePoseScale(0).X - .001) < 1e-7;
            };
            for (int i=0; i<3; i++)
            {
                cam.GlobalPosition = Vector3.Zero;
                int before = renderHeads;
                await SkeletonPassAsync(skel);
                Is("requested skeleton pass completed " + i, renderHeads > before);
                Is("automatic skeleton lens " + i, cam.GlobalPosition.DistanceTo(lens + Vector3.Up * .2f) < 1e-5);
                Is("automatic skeleton target " + i, cam.Target.DistanceTo(lens + Vector3.Up * .2f) < 1e-5);
                Near("modifier restores CPU pose " + i, skel.GetBonePoseScale(0).X, 1);
            }
            Is("render-time head shrinks without accumulation", renderHeads >= 3 && renderScaleCorrect);
            fig.SetFirstPerson(false);
            Near("head restored", skel.GetBonePoseScale(0).X, 1);
            Is("60 deg holds", CameraFraming.BodyYawForView(0, Math.PI/3) is null);
            Is("61 deg turns", CameraFraming.BodyYawForView(0, 61*Math.PI/180) is not null);
            hud.Ui.Apply(new JsonObject { ["menuOpen"] = true });
            hud.RouteSceneKey(new InputEventKey { Keycode = Key.Escape, Pressed = true });
            Is("Esc menu only", mode.Active && exits == 0);
            hud.Ui.Apply(new JsonObject { ["menuOpen"] = false, ["overlayOpen"] = true });
            Is("overlay keeps Esc", !hud.RouteSceneKey(new InputEventKey { Keycode = Key.Escape, Pressed = true }) && mode.Active);
            hud.Ui.Apply(new JsonObject { ["overlayOpen"] = false });
            Is("Enter unbound", !hud.RouteSceneKey(new InputEventKey { Keycode = Key.Enter, Pressed = true }));
            hud.RouteSceneKey(new InputEventKey { Keycode = Key.Escape, Pressed = true });
            Is("Esc exits", !mode.Active && exits == 1);
            cam.Control.ReleaseKeys(); fig.SetFirstPerson(false);
            for (int i=0; i<200; i++) cam.Step(.05);
            Near("exit distance", cam.Distance, 70, 1e-9);
            Is("exit at avatar", cam.Target.DistanceTo(root) < 1e-5);
            Is("overview fields", cam.Follow is null && cam.ZoomCap is null && cam.ZoomFloor is null && cam.NearPitchDeg == 18 && !cam.OrbitOnDrag);
            hud.SetState("selected", new JsonObject { ["isAvatar"] = true });
            hud.RouteSceneKey(new InputEventKey { Keycode = Key.F, Pressed = true });
            Is("F selected avatar embodies", mode.Active);
            cam.Control.Wheel(10000, () => null);
            Is("new session hint", hints == 2);
            int stairs = 0;
            hud.Handlers["rideStairs"] = _ => stairs++;
            hud.SetState("talkTarget", new JsonObject { ["dist"] = 2.4 });
            hud.SetState("stairs", new JsonObject { ["dist"] = 1.0 });
            hud.RouteSceneKey(new InputEventKey { Keycode = Key.F, Pressed = true });
            Is("F nearest offer", stairs == 1);
            Is("readiness far holds", Readiness.AvatarWaitsForPlace(true, "home", new("far", true)));
            Is("readiness unready holds", Readiness.AvatarWaitsForPlace(true, "home", new("near", false)));
            Is("readiness near ready", !Readiness.AvatarWaitsForPlace(true, "home", new("near", true)));
            Is("wilderness", !Readiness.AvatarWaitsForPlace(true, "", null));
            var fallback = new Figure("headless fallback") { HeightM = 1.7 };
            vp.AddChild(fallback);
            fallback.SetBody(new Node3D(), false, null, null, bodyHeight: 1.2);
            fallback.SetFirstPerson(true);
            Is("no-head body hides whole", !fallback.Body!.Visible);
            Near("drawn-height eye", fallback.Eye.Y, 1.128);
            fallback.SetFirstPerson(false);
            Is("no-head body restored", fallback.Body.Visible);
            string walking = await EmbodyWalkCheck.RunAsync(host, fixtures);
            string position = await EmbodyPositionCheck.RunAsync(host, fixtures);
            string rooms = await EmbodyRoomsCheck.RunAsync(host, fixtures);
            string offers = await EmbodyOffersCheck.RunAsync(host, fixtures);
            return $"embody cases={n} {walking} {position} {rooms} {offers} fly=7 cap=34 hints=1/session floor=0.8 first_person=180ms exit=70 menu_esc=only";
        }
        finally { hud.Free(); vp.QueueFree(); }
    }

    /// <summary>
    /// Task 48 controller regression: wait for this skeleton's deferred pass, not an unrelated frame signal.
    /// SkeletonUpdated is emitted before Godot restores the unmodified CPU pose; the deferred callback runs
    /// after that restoration. The deadline fails a missing modifier pass instead of hanging the full suite.
    /// </summary>
    private static async Task SkeletonPassAsync(Skeleton3D skeleton)
    {
        var finished = new TaskCompletionSource();
        void Uploaded() => Callable.From(() => finished.TrySetResult()).CallDeferred();
        skeleton.SkeletonUpdated += Uploaded;
        using var stopDeadline = new CancellationTokenSource();
        try
        {
            skeleton.Advance(.016);
            var deadline = Task.Delay(TimeSpan.FromSeconds(5), stopDeadline.Token);
            if (await Task.WhenAny(finished.Task, deadline) != finished.Task)
                throw new InvalidOperationException("embody skeleton pass did not finish within 5 seconds");
            await finished.Task;
        }
        finally
        {
            stopDeadline.Cancel();
            skeleton.SkeletonUpdated -= Uploaded;
        }
    }
}
