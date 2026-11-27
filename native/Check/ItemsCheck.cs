using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check items</c> (Task 10): offline verification of <see cref="ItemsLayer"/> (GLB scaling to <c>SizeM</c>,
/// anchor seating and yaw, billboard image card + neutral placeholder, confirmed-room aura, ray picking, diffing,
/// strict ownership-ledger disposal keeping <see cref="ModelCache"/> templates intact) and
/// <see cref="AvatarOffersController"/> (click &amp; F-key <c>itemMenu</c>, approach → <c>StartClickWalk</c> → pickup
/// on arrival, cancelled walk sending nothing, and server error <c>detail</c> toast).
/// </summary>
public static class ItemsCheck
{
    private const string GlbUrl = "/fixture/embody/diorama.glb";
    private const string CardImageUrl = "/assets/surface-textures/ground_grass.png";

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        int checks = 0;
        void Is(string label, bool ok)
        {
            checks++;
            if (!ok) throw new InvalidOperationException("items check failed: " + label);
        }
        void Near(string label, double got, double want, double tol = 0.001)
            => Is($"{label}: got {got:R}, expected {want:R}", Math.Abs(got - want) <= tol);

        // ---- Part 1: standalone ItemsLayer (GLB + card + placeholder + aura + picking + ledger) ----
        var layerSource = new FixtureSource(Path.Combine(fixtures, "embody"), fixtures);
        var cache = new ModelCache(layerSource, _ => { });
        var tileRoot = new Node3D { Name = "ItemsCheckTile" };
        host.AddChild(tileRoot);
        var layer = new ItemsLayer { Name = "Items" };

        async Task<ImageTexture?> DecodeFixturePicture(string url)
        {
            var bytes = await layerSource.GetBytesAsync(url);
            var img = SurfaceLibrary.Decode(bytes);
            return ImageTexture.CreateFromImage(img);
        }

        try
        {
            layer.Mount(tileRoot, cache, DecodeFixturePicture);
            layer.SetConfirmedRoom("r-a");

            const string payloadJson = """
            {
              "location_id": "loc-hall",
              "items": [
                {
                  "item_id": "iron-chest",
                  "room_id": "r-a",
                  "name": "Iron Chest",
                  "quantity": 2,
                  "at": [-2.0, 1.0],
                  "y": 0.75,
                  "yaw": 0.0,
                  "size_m": 0.42,
                  "model_url": "/fixture/embody/diorama.glb",
                  "model_version": "v1",
                  "image_url": "/assets/surface-textures/ground_grass.png",
                  "actions": [
                    { "id": "look", "label": "Look at", "source": "core" },
                    { "id": "take", "label": "Take", "source": "core" }
                  ]
                },
                {
                  "item_id": "old-letter",
                  "room_id": "r-a",
                  "name": "Old Letter",
                  "quantity": 1,
                  "at": [1.5, -1.0],
                  "y": 0.20,
                  "yaw": 0.0,
                  "size_m": 0.28,
                  "model_url": null,
                  "image_url": "/assets/surface-textures/ground_grass.png",
                  "actions": [
                    { "id": "look", "label": "Look at", "source": "core" },
                    { "id": "read", "label": "Read", "source": "core" }
                  ]
                },
                {
                  "item_id": "foreign-coin",
                  "room_id": "r-b",
                  "name": "Foreign Coin",
                  "quantity": 1,
                  "at": [3.5, 0.5],
                  "y": 0.0,
                  "yaw": 0.0,
                  "size_m": 0.14,
                  "model_url": null,
                  "image_url": null,
                  "actions": [
                    { "id": "look", "label": "Look at", "source": "core" }
                  ]
                }
              ]
            }
            """;

            using (var doc = JsonDocument.Parse(payloadJson))
                await layer.Apply(ItemPayload.Parse(doc.RootElement));

            Is("I1 one node per item", layer.ItemCount == 3 && layer.ItemNodes.Count == 3);
            Is("I1 shader compiled", ShaderSafety.Lines.Any(l => l.StartsWith("shader item_aura: compiled", StringComparison.Ordinal)));

            var glbNode = layer.GetItemNode("r-a", "iron-chest")!;
            var glbTileBox = ModelPlacement.Measure(glbNode, Transform3D.Identity);
            double longest = Math.Max(glbTileBox.Size.X, Math.Max(glbTileBox.Size.Y, glbTileBox.Size.Z));
            Near("I2 GLB longest AABB edge equals SizeM", longest, 0.42, 0.001);
            Near("I2 GLB AABB bottom sits at Y", glbTileBox.Position.Y, 0.75, 0.001);
            Near("I2 GLB AABB center X", glbTileBox.GetCenter().X, -2.0, 0.001);
            Near("I2 GLB AABB center Z", glbTileBox.GetCenter().Z, 1.0, 0.001);

            var cardNode = layer.GetItemNode("r-a", "old-letter")!;
            var cardMesh = WalkMeshes(cardNode).Single();
            var cardMat = cardMesh.MaterialOverride as StandardMaterial3D;
            Is("I3 card material is camera-facing billboard",
                cardMat is not null && cardMat.BillboardMode == BaseMaterial3D.BillboardModeEnum.Enabled);
            Is("I3 card texture loaded", cardMat?.AlbedoTexture is not null);
            Near("I3 card height equals SizeM", ((QuadMesh)cardMesh.Mesh!).Size.Y, 0.28, 0.001);
            Near("I3 card bottom sits at Y", cardNode.Position.Y + cardMesh.Position.Y - ((QuadMesh)cardMesh.Mesh).Size.Y * 0.5f, 0.20, 0.001);

            var placeholderNode = layer.GetItemNode("r-b", "foreign-coin")!;
            var placeholderMat = WalkMeshes(placeholderNode).Single().MaterialOverride as StandardMaterial3D;
            Is("I3b placeholder is camera-facing billboard",
                placeholderMat is not null && placeholderMat.BillboardMode == BaseMaterial3D.BillboardModeEnum.Enabled);

            var glbOverrideMat = WalkMeshes(glbNode).First().GetSurfaceOverrideMaterial(0);
            Is("I4 confirmed-room items wear aura next_pass",
                glbOverrideMat?.NextPass is ShaderMaterial && cardMat!.NextPass is ShaderMaterial);
            Is("I4 foreign-room item has no aura", placeholderMat!.NextPass is null);

            var hitGlb = layer.Hit(new Vec3(-2.0, 3.0, 1.0), new Vec3(0, -1, 0));
            Is("I5 ray through GLB item returns iron-chest", hitGlb?.ItemId == "iron-chest");
            var hitCard = layer.Hit(new Vec3(1.5, 0.34, -3.0), new Vec3(0, 0, 1));
            Is("I5 ray through card item returns old-letter", hitCard?.ItemId == "old-letter");
            Is("I5 ray missing items returns null", layer.Hit(new Vec3(0, 3.0, 0), new Vec3(0, -1, 0)) is null);

            Is("I6 ledger holds owned resources while mounted", layer.OwnedResourceCount > 0);
            layer.Unmount();
            Is("I6 after Unmount ledger holds 0 owned resources", layer.OwnedResourceCount == 0 && layer.ItemCount == 0);

            var cachedTemplate = await cache.GetAsync(GlbUrl);
            Is("I6 ModelCache template remains intact after Unmount",
                cachedTemplate is not null
                && GodotObject.IsInstanceValid(cachedTemplate.Root)
                && WalkMeshes(cachedTemplate.Root).Any(m => m.Mesh is not null));
        }
        finally
        {
            if (GodotObject.IsInstanceValid(layer)) layer.Free();
            cache.FreeAll();
            tileRoot.QueueFree();
        }

        // ---- Part 2: WorldBuilder mount + AvatarOffersController click / F / walk-to-approach / error toast ----
        var source = new FixtureSource(Path.Combine(fixtures, "embody"), fixtures);
        bool chestTaken = false;
        source.LocationItemsProvider = locId =>
        {
            if (locId != "loc-hall") return null;
            string json = chestTaken
                ? """
                  {
                    "location_id": "loc-hall",
                    "items": [
                      {
                        "item_id": "foreign-scroll",
                        "room_id": "r-b",
                        "name": "Foreign Scroll",
                        "quantity": 1,
                        "at": [2.0, 0.0],
                        "y": 0.0,
                        "yaw": 0.0,
                        "size_m": 0.25,
                        "model_url": null,
                        "image_url": null,
                        "actions": [{ "id": "look", "label": "Look at", "source": "core" }, { "id": "take", "label": "Take", "source": "core" }]
                      }
                    ]
                  }
                  """
                : """
                  {
                    "location_id": "loc-hall",
                    "items": [
                      {
                        "item_id": "hall-pack",
                        "room_id": "r-a",
                        "name": "Traveller Pack",
                        "quantity": 2,
                        "at": [-2.0, -1.5],
                        "y": 0.0,
                        "yaw": 25.0,
                        "size_m": 0.36,
                        "model_url": "/fixture/embody/diorama.glb",
                        "image_url": "/assets/surface-textures/ground_grass.png",
                        "actions": [
                          { "id": "look", "label": "Look at", "source": "core" },
                          { "id": "take", "label": "Take", "source": "core" },
                          { "id": "read", "label": "Read", "source": "core" },
                          { "id": "polish", "label": "Polish", "source": "pkg.test" }
                        ]
                      },
                      {
                        "item_id": "foreign-scroll",
                        "room_id": "r-b",
                        "name": "Foreign Scroll",
                        "quantity": 1,
                        "at": [2.0, 0.0],
                        "y": 0.0,
                        "yaw": 0.0,
                        "size_m": 0.25,
                        "model_url": null,
                        "image_url": null,
                        "actions": [{ "id": "look", "label": "Look at", "source": "core" }, { "id": "take", "label": "Take", "source": "core" }]
                      }
                    ]
                  }
                  """;
            return JsonDocument.Parse(json);
        };
        source.ApproachItemHandler = id => JsonDocument.Parse("""{"point":[-2.0,-0.9],"room_id":"r-a"}""");
        source.PickupItemHandler = id =>
        {
            chestTaken = true;
            return JsonDocument.Parse("""{"ok":true,"success":true}""");
        };
        source.RoomItemActionHandler = (id, act) => throw new ApiException(404, "/play/room-item/action", "Item vanished");

        var world = new Node3D { Name = "ItemsControllerWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        var hud = new HudOverlay();
        var wireMessages = new List<string>();
        hud.MessageProbe = wireMessages.Add;
        AvatarOffersController? offers = null;
        AvatarPositionController? position = null;

        try
        {
            await builder.BuildAsync(world, "Fixture Hall");
            var hall = builder.Slots["loc-hall"];
            builder.SetOpen("loc-hall", true);
            hall.Fade.Snap(1);
            builder.TickView(0.016, new Vector3(0, 10, 10));
            Is("I7 WorldBuilder mounted ItemsLayer on near slot", hall.Items is { IsMounted: true });

            for (int i = 0; i < 240 && builder.NavFor(hall) is null; i++)
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
            Is("I7 navigation ready", builder.NavFor(hall) is not null);

            var manager = new FigureManager(source, builder.Height!, _ => { }, strict: true)
            { AutoTick = false, ClipFit = ClipFitMode.OnDemandSync, Slots = () => builder.Slots, GroundYAt = builder.FigureGroundY };
            world.AddChild(manager);
            await manager.InitAsync();
            manager.SetProcess(false);
            using var map = await source.GetWorldMapAsync();
            await manager.Apply(map.RootElement);
            await manager.EnsurePool();

            var avatar = manager.Figures[manager.AvatarName];
            var steering = new PlayerSteering(manager, builder) { RoomId = "r-a" };
            steering.SetActive(true);
            double now = 100;
            var channel = new PositionChannel(source.ReportPositionAsync, () => now, "fixture-items-10");
            position = new AvatarPositionController(manager, builder, steering, source, () => now, channel);
            position.SetActive(true, map.RootElement);
            offers = new AvatarOffersController(manager, builder, steering, source, hud, position, () => now);
            offers.SetActive(true);
            hud.SetState("mode", "embodied");
            if (offers.PendingItems is { } pendingInit) await pendingInit;

            Is("I8 items mounted on hall", hall.Items!.ItemCount == 2);
            manager.SnapPlayerTo(avatar.CharacterName, new Vector3(-3.0f, 0.01f, 1.0f));
            var npc = manager.Figures["fixture-npc"];
            npc.SetHidden(true);
            offers.UpdateOffers();

            // Foreign-room item cannot be clicked.
            var foreignWorld = hall.Items.WorldAnchorOf(hall.Items.Items.Single(i => i.ItemId == "foreign-scroll"));
            Is("I8 foreign-room item click ignored",
                !offers.Pick(new Vec3(foreignWorld.X, foreignWorld.Y + 2, foreignWorld.Z), new Vec3(0, -1, 0), new Vector2(200, 150))
                && hud.SceneOwned("itemMenu") is null);

            // Confirmed-room item hover + click opens itemMenu.
            var packWorld = hall.Items.WorldAnchorOf(hall.Items.Items.Single(i => i.ItemId == "hall-pack"));
            Is("I8 hover highlights confirmed-room item",
                offers.Hover(new Vec3(packWorld.X, packWorld.Y + 2, packWorld.Z), new Vec3(0, -1, 0)) && offers.HasItemHover);
            Is("I8 click opens itemMenu",
                offers.Pick(new Vec3(packWorld.X, packWorld.Y + 2, packWorld.Z), new Vec3(0, -1, 0), new Vector2(210, 160)));
            var menu = hud.SceneOwned("itemMenu") as JsonObject;
            Is("I8 itemMenu carries item_id, quantity and actions",
                menu is not null
                && menu["item"]?["item_id"]?.GetValue<string>() == "hall-pack"
                && menu["item"]?["quantity"]?.GetValue<int>() == 2
                && menu["item"]?["actions"]?.AsArray().Count == 4);

            hud.Handlers["closeItemMenu"](new JsonArray());
            Is("I8 closeItemMenu clears state", hud.SceneOwned("itemMenu") is null);

            // F key opens nearest item menu when item is the nearest offer.
            manager.SnapPlayerTo(avatar.CharacterName, new Vector3(-2.0f, 0.01f, -0.2f));
            offers.UpdateOffers();
            Is("I9 nearest offer is item", offers.NearestOffer == "item");
            hud.RouteSceneKey(new InputEventKey { Keycode = Key.F, Pressed = true });
            Is("I9 F key opens itemMenu", hud.SceneOwned("itemMenu")?["item"]?["item_id"]?.GetValue<string>() == "hall-pack");

            // Cancelled walk sends nothing.
            manager.SnapPlayerTo(avatar.CharacterName, new Vector3(-3.2f, 0.01f, 1.2f));
            hud.Handlers["pickItemAction"](new JsonArray("hall-pack", "take"));
            Is("I10 pickItemAction closes itemMenu immediately", hud.SceneOwned("itemMenu") is null);
            Is("I10 approach called, pickup not yet called",
                source.ApproachItemRequests.Count == 1 && source.PickupItemRequests.Count == 0 && steering.WalkOrderId is not null);
            steering.Step(1.0 / 60, new HashSet<string> { "w" }, 0);
            manager.Tick(1.0 / 60);
            if (offers.PendingItemAction is { } cancelledTask) await cancelledTask;
            Is("I10 cancelled walk sends nothing", source.PickupItemRequests.Count == 0);

            // Read action walks to approach, then sends ui openItemReader(itemId) without calling /play/read.
            manager.SnapPlayerTo(avatar.CharacterName, new Vector3(-3.2f, 0.01f, 1.2f));
            int readFetchesBefore = source.LocationItemsRequests.Count;
            int wireCountBeforeRead = wireMessages.Count;
            hud.Handlers["pickItemAction"](new JsonArray("hall-pack", "read"));
            Is("I11a openItemReader not sent before walk arrives",
                !wireMessages.Skip(wireCountBeforeRead).Any(m => m.Contains("\"openItemReader\"", StringComparison.Ordinal))
                && steering.WalkOrderId is not null);
            for (int i = 0; i < 240 && steering.WalkOrderId is not null; i++)
            {
                steering.Step(1.0 / 60, new HashSet<string>(), 0);
                manager.Tick(1.0 / 60);
            }
            if (offers.PendingItemAction is { } readTask) await readTask;
            Is("I11b read sends ui openItemReader with item id after arrival and makes no server read/pickup/action post",
                wireMessages.Skip(wireCountBeforeRead).Contains("""{"v":4,"kind":"ui","name":"openItemReader","args":["hall-pack"]}""")
                && source.PickupItemRequests.Count == 0
                && source.RoomItemActionRequests.Count == 0
                && !source.ByteRequests.Any(u => u.Contains("/play/read", StringComparison.Ordinal))
                && source.LocationItemsRequests.Count > readFetchesBefore);

            // Error toast on failed package action after arrival.
            manager.SnapPlayerTo(avatar.CharacterName, new Vector3(-3.2f, 0.01f, 1.2f));
            hud.Handlers["pickItemAction"](new JsonArray("hall-pack", "polish"));
            for (int i = 0; i < 240 && steering.WalkOrderId is not null; i++)
            {
                steering.Step(1.0 / 60, new HashSet<string>(), 0);
                manager.Tick(1.0 / 60);
            }
            if (offers.PendingItemAction is { } failedAction) await failedAction;
            Is("I11 package action error sends detail toast over HUD bridge",
                wireMessages.Any(m => m.Contains("\"name\":\"toast\"", StringComparison.Ordinal)
                                      && m.Contains("Item vanished", StringComparison.Ordinal)));

            // Full walk to approach + take on arrival + immediate refetch.
            manager.SnapPlayerTo(avatar.CharacterName, new Vector3(-3.2f, 0.01f, 1.2f));
            int fetchesBefore = source.LocationItemsRequests.Count;
            hud.Handlers["pickItemAction"](new JsonArray("hall-pack", "take"));
            for (int i = 0; i < 240 && steering.WalkOrderId is not null; i++)
            {
                steering.Step(1.0 / 60, new HashSet<string>(), 0);
                manager.Tick(1.0 / 60);
            }
            if (offers.PendingItemAction is { } takeTask) await takeTask;
            Is("I12 pickup called once on arrival and items refetched",
                source.PickupItemRequests.SequenceEqual(new[] { "hall-pack" })
                && source.LocationItemsRequests.Count > fetchesBefore
                && hall.Items.ItemCount == 1
                && hall.Items.Items.All(i => i.ItemId != "hall-pack"));

            return $"items={checks} I1-I12=ok glb=0.42m card=billboard ledger=0 pickup=walk+refetch";
        }
        finally
        {
            offers?.Dispose();
            position?.Dispose();
            hud.Free();
            builder.StopResidency();
            builder.Models?.FreeAll();
            world.QueueFree();
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }
    }

    private static IEnumerable<MeshInstance3D> WalkMeshes(Node node)
    {
        if (node is MeshInstance3D mi) yield return mi;
        foreach (var child in node.GetChildren())
        foreach (var m in WalkMeshes(child))
            yield return m;
    }
}
