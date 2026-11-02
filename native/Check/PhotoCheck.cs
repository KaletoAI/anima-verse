using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Photo;
using AnimaNative.Scene;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Offline production camera/lifecycle/HTTP/bridge check. Dummy renderer substitutes only readback pixels.</summary>
public static class PhotoCheck
{
    public static async Task<string> RunAsync(Node3D host,string fixtures)
    {
        int checks=0;
        void Is(string name,bool value) { checks++; if (!value) throw new InvalidOperationException("photo "+name); }
        var source=new FixtureSource(Path.Combine(fixtures,"placement"),fixtures);
        var world=new Node3D { Name="PhotoCheckWorld" }; host.AddChild(world);
        var builder=new WorldBuilder(source,_=>{},strict:true);
        var vp=new SubViewport { Size=new(1600,900), HandleInputLocally=true }; host.AddChild(vp);
        var cam=new OverviewCamera { Current=true }; vp.AddChild(cam); cam.SetProcess(false);
        var visibleLayer=new CanvasLayer(); host.AddChild(visibleLayer);
        var hiddenLayer=new CanvasLayer { Visible=false }; host.AddChild(hiddenLayer);
        var loose=new Label { Text="not in shot" }; host.AddChild(loose);
        var marker=new Node3D { Name="PhotoMarker" }; world.AddChild(marker);
        var hiddenMarker=new Node3D { Visible=false }; world.AddChild(hiddenMarker);
        var extraMarkers=new List<Node3D> { marker,hiddenMarker };
        var hud=new HudInputProbe(); host.AddChild(hud);
        var messages=new List<JsonObject>(); hud.MessageProbe=json=>messages.Add(JsonNode.Parse(json)!.AsObject());
        var shotLogs=new List<string>();
        using var transport=new UploadFixture();
        using var api=new AnimaApi("http://fixture.invalid",transport); api.AdoptSession("fixture-session");
        var photo=new PhotoMode { Camera=cam, Markers=()=>extraMarkers,
            View=()=>PhotoView.Build(new(0,3,0),new(0,0,-1),new(1,0,0),new(0,1,0),90,2,.2,100,[new("Tess Vale",new(0,3,-10))],1),
            Upload=async (bytes,ct)=> { Is("restore before upload", !cam.Photo.Active && visibleLayer.Visible && !hiddenLayer.Visible); return await api.UploadPhotoAsync(bytes,ct); },
            Screenshot=hud.OpenScreenshotPhoto, Toast=message=>hud.SendUi("toast",message,true), Log=shotLogs.Add,
            Readback=()=> {
                Is("frame has no overlays", !visibleLayer.Visible && !hiddenLayer.Visible && !loose.Visible && !marker.Visible && !hiddenMarker.Visible);
                return Image.CreateEmpty(3000,1500,false,Image.Format.Rgb8);
            }
        };
        host.AddChild(photo);
        InputEventKey KeyEvent(Key key,bool pressed=true,bool echo=false)=>new() { Keycode=key,Pressed=pressed,Echo=echo };
        async Task Settle(Task task)
        {
            ulong until=Time.GetTicksMsec()+10000;
            while (!task.IsCompleted && Time.GetTicksMsec()<until)
            {
                RenderingServer.ForceDraw();
                await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
            }
            Is("async deadline", task.IsCompleted); await task;
        }
        FigureManager? figures=null;
        var main=new Main();
        try
        {
            await builder.BuildAsync(world,"Inn");
            figures=new FigureManager(source,builder.Height!,_=>{},strict:true) {
                AutoTick=false,ClipFit=ClipFitMode.OnDemandSync,Slots=()=>builder.Slots };
            world.AddChild(figures); await figures.InitAsync();
            var node=JsonNode.Parse(builder.FirstMap!.Value.GetRawText())!;
            node["characters"]=new JsonArray(
                new JsonObject { ["name"]="Tess Vale",["location_id"]="loc-inn",["room_id"]="r-hall",["height_cm"]=170,
                    ["pos"]=new JsonObject { ["x"]=64,["z"]=128 } },
                new JsonObject { ["name"]="Demo Walker",["height_cm"]=170,["pos"]=new JsonObject { ["x"]=80,["z"]=140 } });
            node["avatar"]="Tess Vale";
            using var map=JsonDocument.Parse(node.ToJsonString());
            await figures.Apply(map.RootElement); await figures.EnsurePool();
            var avatar=figures.Figures["Tess Vale"]; var npc=figures.Figures["Demo Walker"];
            var steering=new PlayerSteering(figures,builder); steering.SetActive(true);
            using var position=new AvatarPositionController(figures,builder,steering,api);
            position.SetActive(true,map.RootElement);
            var inn=builder.Slots["loc-inn"]; inn.Fade.Snap(1);
            builder.SetLevel("loc-inn",0);
            const BindingFlags flags=BindingFlags.NonPublic|BindingFlags.Instance;
            void Field(string name,object value)=>typeof(Main).GetField(name,flags)!.SetValue(main,value);
            Field("_photo",photo); Field("_camera",cam); Field("_figures",figures); Field("_playerSteering",steering);
            Field("_avatarPosition",position); Field("_builder",builder);
            PhotoView MainView() => (PhotoView)typeof(Main).GetMethod("CurrentPhotoView",flags)!.Invoke(main,null)!;
            // Datum 4 plus a flat lattice at 302 cm = 7.02. Without a lattice the browser
            // uses roomAt's smallest rectangle: the hall centre is 4.056875 (fixture README).
            var lattice=new PlacedSurface("photo-floor",new(new(0,0),0,0,2,"xz"),
                new(2,new(-1,-1),2,2,[302,302,302,302],new(-1,0,-1),new(1,1,1),new(2,1,2)),0,1,"r-loft");
            inn.Stands.Surfaces.Add(lattice);
            builder.SetLevel("loc-inn",1);
            Is("shown-storey floor under camera",Math.Abs(builder.PhotoFloorY(new(64,10,128))-7.02)<1e-6);
            Is("floor above camera uses room fallback",Math.Abs(builder.PhotoFloorY(new(64,5,128))-4.056875)<1e-6);
            inn.Stands.Surfaces.Remove(lattice);
            builder.SetLevel("loc-inn",0);
            cam.LookAtFromPosition(avatar.Lens+new Vector3(0,0,10),avatar.Lens);
            Is("live head/eye feeds framing",MainView().visible.Any(v=>v.name==avatar.CharacterName && Math.Abs(v.screen_x-.5)<1e-5));
            bool bodyVisible=avatar.Body!.Visible; avatar.Body.Visible=false;
            Is("hidden body is not a subject",MainView().visible.All(v=>v.name!=avatar.CharacterName)); avatar.Body.Visible=bodyVisible;
            var travelLine=new TravelLine(new[]{(0d,0d),(1d,1d)},(_,_)=>0); figures.AddChild(travelLine); avatar.TravelLine=travelLine;
            var realMarkers=((IEnumerable<Node3D>)typeof(Main).GetMethod("PhotoMarkers",flags)!.Invoke(main,null)!).ToList();
            Is("travel lines and door/boundary markers discovered",realMarkers.Contains(travelLine)
                && (inn.Storeys.DoorMarks is null || realMarkers.Contains(inn.Storeys.DoorMarks))
                && (inn.Storeys.BoundaryMarks is null || realMarkers.Contains(inn.Storeys.BoundaryMarks)));
            photo.Changed=active=> {
                if (active) typeof(Main).GetMethod("PhotoChanged",flags)!.Invoke(main,new object[] { true });
                else { figures.PhotoMode=false; builder.PhotoMode=false; position.Suspended=false; }
            };

            Is("typing blocks F2", !photo.HandleInput(KeyEvent(Key.F2),true) && !photo.Active);
            Is("modified F2 ignored", !photo.HandleInput(new InputEventKey { Keycode=Key.F2,Pressed=true,CtrlPressed=true },false));
            foreach (string mode in new[]{"overview","follow","first person"})
            {
                cam.Follow=null; cam.ZoomCap=cam.ZoomFloor=null; cam.Control.ResetFirstPerson();
                cam.JumpTo(new(10,2,20),40); cam.Control.Yaw=.3; cam.Control.TargetYaw=.6; cam.Control.PitchOffset=7;
                if (mode!="overview")
                {
                    cam.Follow=()=>new Vec3(10,3.598,20); cam.ZoomCap=34; cam.ZoomFloor=.8; cam.NearPitchDeg=8;
                    if (mode=="first person") { cam.Control.Dist=cam.Control.TargetDist=.8; cam.Step(.1); cam.Step(.1); }
                }
                cam.SetChatBox(new HudRect(1000,0,600,900)); cam.Step(.05);
                cam.FlyTo(new(13,4,21),mode=="first person"?.8:12); // preserve a running fly too.
                var state=cam.Control.Save(); var follow=cam.Follow; var shift=cam.ViewShiftPx;
                var transform=cam.Transform; var projection=cam.GetCameraProjection(); bool first=cam.FirstPerson;
                var hiddenState=ControlState(cam.Control);
                Is(mode+" enter",photo.HandleInput(KeyEvent(Key.F2),false) && photo.Active);
                photo.HandleInput(KeyEvent(Key.F2,echo:true),false); Is(mode+" repeat ignored",photo.Active);
                Is(mode+" HUD hidden",!visibleLayer.Visible && !loose.Visible);
                photo.HandleInput(KeyEvent(Key.W),false); cam.Step(.1);
                cam.FlyTo(new(100,100,100),80);
                cam.ZoomTo(new(100,100,100));
                Is(mode+" free camera moved",cam.Transform!=transform && !cam.FirstPerson);
                Is(mode+" camera arithmetic sleeps",cam.Control.Save()==state && cam.Follow==follow && cam.ViewShiftPx==shift && ControlState(cam.Control)==hiddenState);
                var before=avatar.Position; var beforeNpc=npc.Position; npc.Target=npc.Position+new Vector3(2,0,0);
                avatar.Target=avatar.Position+new Vector3(2,0,0);
                typeof(Main).GetMethod("StepPlayerSteering",flags)!.Invoke(main,new object[]{.1});
                typeof(Main).GetMethod("TickEmbody",flags)!.Invoke(main,null);
                figures.Tick(.1);
                Is(mode+" avatar holds, NPC runs",avatar.Position==before && npc.Position!=beforeNpc);
                Is(mode+" no position reports",transport.Paths.Count==0 && !position.Channel.CanReport());
                Is(mode+" open/storey stay",inn.Open && inn.LevelFilter==0);
                photo.HandleInput(new InputEventMouseButton { ButtonIndex=MouseButton.Left,Pressed=true },false);
                int clicks=0; void Click(Vector2 _)=>clicks++;
                cam.Clicked+=Click;
                photo.HandleInput(KeyEvent(Key.Escape),false);
                cam._UnhandledInput(new InputEventMouseButton { ButtonIndex=MouseButton.Left,Pressed=false });
                cam.Clicked-=Click;
                Is(mode+" late release is not a click",clicks==0);
                Is(mode+" exact camera restore",cam.Transform==transform && cam.GetCameraProjection()==projection && cam.FirstPerson==first
                    && cam.Control.Save()==state && cam.Follow==follow && cam.ViewShiftPx==shift && ControlState(cam.Control)==hiddenState);
                Is(mode+" HUD restore",visibleLayer.Visible && !hiddenLayer.Visible && loose.Visible);
                Is(mode+" keys released",cam.Control.KeysDown.Count==0 && cam.Photo.Keys.Count==0);
            }

            // The real post-draw boundary; freshly streamed markers/layers are included.
            photo.Enter();
            photo.HandleInput(new InputEventKey { Keycode=Key.Space,Pressed=true,CtrlPressed=true },false);
            Is("modified Space does not shoot",!photo.Busy);
            var lateLayer=new CanvasLayer(); host.AddChild(lateLayer);
            var lateMarker=new Node3D(); world.AddChild(lateMarker); extraMarkers.Add(lateMarker);
            photo.HandleInput(KeyEvent(Key.Space),false); var pending=photo.Pending;
            photo.HandleInput(KeyEvent(Key.Space),false);
            await Settle(pending);
            Is("one upload, multipart JPEG",transport.Paths.SequenceEqual(new[]{"/chat/me/upload-image"}) && transport.ValidJpeg);
            Is("late overlays restore",lateLayer.Visible && lateMarker.Visible && !hiddenMarker.Visible);
            Is("session retained",api.SessionToken()=="fixture-session");
            var shot=messages.Single(m=>m["name"]?.GetValue<string>()=="openScreenshotPhoto");
            Is("bridge v4 id/url/view", shot["v"]!.GetValue<int>()==4 && shot["kind"]!.GetValue<string>()=="ui"
                && shot["args"]![0]!["imageId"]!.GetValue<string>()=="fixture/id"
                && shot["args"]![0]!["imageUrl"]!.GetValue<string>()=="/chat/me/upload-image/fixture%2Fid"
                && shot["args"]![0]!["view"]!["visible"]![0]!["screen_x"]!.GetValue<double>()==.5);

            messages.Clear(); transport.Paths.Clear(); transport.Fail=true;
            photo.Enter(); photo.HandleInput(KeyEvent(Key.Space),false); await Settle(photo.Pending);
            Is("upload failure toasts once after restore", !photo.Active && visibleLayer.Visible && messages.Count(m=>m["name"]!.GetValue<string>()=="toast")==1
                && messages.All(m=>m["name"]!.GetValue<string>()!="openScreenshotPhoto"));

            messages.Clear(); transport.Paths.Clear(); transport.Fail=false;
            photo.Enter(); photo.HandleInput(KeyEvent(Key.Space),false); photo.HandleInput(KeyEvent(Key.Escape),false);
            await Settle(photo.Pending);
            Is("capture cancellation is silent",transport.Paths.Count==0 && messages.Count==0 && !photo.Active);

            transport.Hold=new TaskCompletionSource();
            photo.Enter(); photo.HandleInput(KeyEvent(Key.Space),false);
            ulong deadline=Time.GetTicksMsec()+10000;
            while (transport.Paths.Count==0 && Time.GetTicksMsec()<deadline)
            {
                RenderingServer.ForceDraw();
                await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
            }
            Is("upload starts outside photo",transport.Paths.Count==1 && !photo.Active && photo.Busy);
            photo.HandleInput(KeyEvent(Key.F2),false); transport.Hold.SetResult(); await Settle(photo.Pending);
            Is("pending upload cancelled silently",messages.Count==0 && !photo.Active);

            messages.Clear(); transport.Paths.Clear(); transport.Hold=null;
            var readback=photo.Readback;
            photo.Readback=()=>throw new InvalidOperationException("fixture capture failure");
            photo.Enter(); photo.HandleInput(KeyEvent(Key.Space),false); await Settle(photo.Pending);
            Is("capture error restores and toasts",!photo.Active && visibleLayer.Visible && transport.Paths.Count==0
                && messages.Count(m=>m["name"]!.GetValue<string>()=="toast")==1);
            messages.Clear();
            photo.Readback=()=> { photo.Cancel(); return Image.CreateEmpty(10,10,false,Image.Format.Rgb8); };
            photo.Enter(); photo.HandleInput(KeyEvent(Key.Space),false); await Settle(photo.Pending);
            Is("cancel during readback/encoding is silent",!photo.Active && transport.Paths.Count==0 && messages.Count==0);
            photo.Readback=readback;
            Is("one metric line per requested shot",shotLogs.Count==6 && shotLogs.All(line=>line.Contains("bytes, visible=") && line.Contains("upload=")));

            // Real HUD input precedence even without CEF: Escape cannot fall through to exitEmbodied.
            int exits=0; hud.Handlers["exitEmbodied"]=_=>exits++; hud.SetState("mode","embodied");
            hud.ScenePhotoInput=input=>photo.HandleInput(input,hud.Ui.Typing);
            photo.Enter(); hud._Input(KeyEvent(Key.Escape)); Is("HUD Escape belongs to photo",!photo.Active && exits==0);
            hud.Ui.Apply(new JsonObject { ["typing"]=true }); hud._Input(KeyEvent(Key.F2)); Is("HUD typing blocks toggle",!photo.Active);
            lateLayer.Free();
            return $"photo_cases={checks} jpeg=2048x1024 multipart=1 bridge=1 (dummy readback pixels)";
        }
        catch (Exception e)
        {
            GD.PrintErr($"photo after {checks} checks: {e}");
            throw;
        }
        finally
        {
            photo.Cancel(); photo.Free(); main.Free(); hud.Free();
            visibleLayer.Free(); hiddenLayer.Free(); loose.Free(); vp.Free();
            world.Free(); builder.Models?.FreeAll();
        }
    }

    private static string ControlState(OverviewControl control)
    {
        // Include private fly progression, follow sample and first-person dwell/hysteresis state.
        var values=new List<string>();
        void Read(object obj)
        {
            foreach (var field in obj.GetType().GetFields(BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic))
            {
                if (field.Name is "_keys" or "_orbiting" or "_moved" or "_orbitLast" or "_orbitStart") continue;
                object? value=field.GetValue(obj);
                if (value is not null && field.Name=="_firstPersonZoom") Read(value);
                else values.Add(field.Name+"="+value);
            }
        }
        Read(control); return string.Join(";",values);
    }

    private sealed class UploadFixture : HttpMessageHandler
    {
        public List<string> Paths { get; } = new();
        public bool Fail, ValidJpeg;
        public TaskCompletionSource? Hold;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken ct)
        {
            Paths.Add(request.RequestUri!.AbsolutePath);
            if (request.Method!=HttpMethod.Post || request.RequestUri.AbsolutePath!="/chat/me/upload-image"
                || request.RequestUri.Query!="?purpose=scene_photo"
                || request.Content is not MultipartFormDataContent multi) throw new InvalidOperationException("expected multipart player upload");
            var file=multi.Single(); var bytes=await file.ReadAsByteArrayAsync(ct);
            using var decoded=new Image();
            ValidJpeg=file.Headers.ContentDisposition!.Name!.Trim('"')=="file"
                && file.Headers.ContentDisposition.FileName!.Trim('"')=="photo.jpg"
                && file.Headers.ContentType!.MediaType=="image/jpeg" && bytes[0]==255 && bytes[1]==216
                && decoded.LoadJpgFromBuffer(bytes)==Error.Ok && decoded.GetWidth()==2048 && decoded.GetHeight()==1024;
            if (Hold is not null) await Hold.Task.WaitAsync(ct);
            return new(Fail?HttpStatusCode.RequestEntityTooLarge:HttpStatusCode.OK) {
                Content=new StringContent(Fail?"{\"detail\":\"fixture upload limit\"}":"{\"image_id\":\"fixture/id\"}") };
        }
    }
}
