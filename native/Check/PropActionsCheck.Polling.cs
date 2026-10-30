using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Props;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

public static partial class PropActionsCheck
{
    private static async Task<int> CheckPolling(Node3D host,string fixtures)
    {
        int checks=0;
        void Is(string label,bool ok) { checks++; if(!ok) throw new InvalidOperationException("propactions polling "+label); }
        var fixture=new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures);
        var world=new Node3D(); host.AddChild(world); var builder=new WorldBuilder(fixture,_=>{},strict:true);
        HudOverlay? hud=null; AvatarPositionController? position=null; AvatarOffersController? offers=null;
        try {
            await builder.BuildAsync(world,"Fixture Prop Room");
            builder.SetOpen("loc-props",true); builder.Slots["loc-props"].Fade.Snap(1);
            var source=new MenuSource(fixture);
            var manager=new FigureManager(fixture,builder.Height!,_=>{},strict:true) { AutoTick=false,Slots=()=>builder.Slots,GroundYAt=builder.FigureGroundY };
            world.AddChild(manager);
            using var map=await fixture.GetWorldMapAsync(); await manager.Apply(map.RootElement);
            double now=0;
            var steering=new PlayerSteering(manager,builder); steering.SetActive(true);
            position=new(manager,builder,steering,source,()=>now); position.SetActive(true,map.RootElement);
            hud=new HudOverlay(); offers=new(manager,builder,steering,source,hud,position,()=>now);
            offers.SetActive(true); await offers.PendingPropAction!;
            int startupStateReads=source.StateRequests;
            async Task<(int Offers,int State)> Window(bool seated) {
                source.StateOverride=seated ? JsonNode.Parse("{\"current\":[{\"execution_id\":\"seat\",\"status\":\"active\"}],\"outgoing\":[]}")!.AsObject() : null;
                await offers.PropActions!.RefreshAsync();
                int o=source.OfferRequests,s=source.StateRequests;
                double start=now;
                for(int step=0;step<1200;step++) {
                    now=start+step*50;
                    if(step%60==0) { manager.ApplyPolled(map.RootElement.Clone()); }
                    if(!seated) {
                        steering.Step(.05,new HashSet<string>{step%20<10 ? "w" : "s"},0);
                        manager.Tick(.05);
                    }
                    offers.Tick(); if(offers.PendingPropAction is { } pending) await pending;
                    // Furniture hover must consume the cached offer inventory only.
                    offers.Hover(new(3,2,0),new(0,-1,0));
                }
                now=start+60000;
                return(source.OfferRequests-o,source.StateRequests-s);
            }
            var seated=await Window(true); var walking=await Window(false);
            GD.Print($"POLL-MEASURE native 60s seated offers={seated.Offers} state={seated.State}; walking offers={walking.Offers} state={walking.State}");
            int cycleOffers=source.OfferRequests,cycleStates=source.StateRequests;
            double cycleStart=now;
            var buckets=new int[20];
            source.MapOverride=JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir,"worldmap_approach.json")))!.AsObject();
            source.StateOverride=JsonNode.Parse("{\"current\":[{\"execution_id\":\"execution-56-solo\",\"status\":\"approaching\"}],\"outgoing\":[]}")!.AsObject();
            source.PendingRequest=new TaskCompletionSource<JsonDocument>();
            source.PendingRequest.SetResult(JsonDocument.Parse("{\"execution_id\":\"execution-56-solo\",\"status\":\"approaching\"}"));
            var action=source.Offers[0]!;
            hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
            await offers.PendingPropAction!; source.PendingRequest=null;
            int lastReads=cycleOffers+cycleStates;
            for(int step=0;step<400;step++) {
                now=cycleStart+step*50;
                if(step==20) {
                    source.StateOverride["current"]![0]!["status"]="active";
                    source.MapOverride=JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir,"worldmap_active.json")))!.AsObject();
                }
                if(step==160) {
                    hud.Handlers["cancelPropAction"](new JsonArray("execution-56-solo"));
                    await offers.PendingPropAction!;
                }
                offers.Tick(); if(offers.PendingPropAction is { } pending) await pending;
                manager.Tick(.05);
                int readsNow=source.OfferRequests+source.StateRequests;
                buckets[step/20]+=readsNow-lastReads; lastReads=readsNow;
            }
            int peak=0; foreach(int count in buckets) peak=Math.Max(peak,count);
            GD.Print($"POLL-MEASURE native request-seat-release 20s offers={source.OfferRequests-cycleOffers} state={source.StateRequests-cycleStates} peak_total_per_s={peak}; after_bursts_last_3s={buckets[17]+buckets[18]+buckets[19]}");
            Is("startup and activation share one state read",startupStateReads==1);
            Is("seated budget <=20 offers +20 state per 60s",seated.Offers<=20 && seated.State<=20);
            Is("walking budget <=20 offers +20 state per 60s",walking.Offers<=20 && walking.State<=20);
            Is("own motion stays at normal polling cadence",peak<=4);
            Is("normal polling continues after own mutation",buckets[17]+buckets[18]+buckets[19]<=2);
            Is("release remains steerable",!offers.PropActions!.Paused && !steering.PropActionDriven);
            offers.PropPollPeriod=()=>6000;
            var pushed=await Window(false);
            GD.Print($"POLL-MEASURE native pushed 60s offers={pushed.Offers} state={pushed.State}");
            Is("push cadence <=10 offers +10 state per 60s",pushed.Offers<=10 && pushed.State<=10);
            offers.PropPollPeriod=()=>3000;
            source.PendingState=new TaskCompletionSource<JsonDocument>();
            int reads=source.StateRequests;
            var first=offers.PropActions!.RefreshAsync(); var second=offers.PropActions.RefreshAsync();
            Is("state requests coalesce",source.StateRequests-reads==1);
            source.PendingState.SetResult(JsonDocument.Parse("{\"current\":[],\"outgoing\":[]}"));
            await Task.WhenAll(first,second); source.PendingState=null;
            source.PendingOffers=new TaskCompletionSource<JsonDocument>(); reads=source.OfferRequests;
            first=offers.RefreshSemanticOffersAsync(); second=offers.RefreshSemanticOffersAsync();
            Is("offers requests coalesce",source.OfferRequests-reads==1);
            source.PendingOffers.SetResult(JsonDocument.Parse(source.Offers.ToJsonString()));
            await Task.WhenAll(first,second); source.PendingOffers=null;
            source.PendingOffers=new TaskCompletionSource<JsonDocument>();
            var heldOffers=source.PendingOffers;
            reads=source.OfferRequests;
            first=offers.RefreshSemanticOffersAsync();
            hud.PropActionsChanged!("hud-during-offers");
            second=offers.PendingPropAction!;
            var oldOffers=JsonDocument.Parse(source.Offers.ToJsonString());
            source.Offers[0]!["enabled"]=true;
            source.PendingOffers=null; heldOffers.SetResult(oldOffers);
            await Task.WhenAll(first,second);
            Is("offer invalidation waits then revalidates once",source.OfferRequests==reads+2
                && hud.SceneOwned("propActionSnapshot")!["offers"]![0]!["enabled"]!.GetValue<bool>());
            // A mutation arriving during a read must await a new post-mutation state.
            int earlyMaps=0;
            using var control=new PropActionControl(source,()=>now) { RefreshWorld=()=> { earlyMaps++; return Task.CompletedTask; } };
            source.PendingState=new TaskCompletionSource<JsonDocument>();
            var held=source.PendingState;
            first=control.RefreshAsync();
            await control.PrepareAsync("during-read");
            second=control.ChangedAsync("during-read");
            Is("joined own answer does not request a burst world poll",earlyMaps==0);
            reads=source.StateRequests;
            source.PendingState=null;
            held.SetResult(JsonDocument.Parse("{\"current\":[{\"execution_id\":\"stale\",\"status\":\"active\"}],\"outgoing\":[]}"));
            await Task.WhenAll(first,second);
            Is("changed read revalidates once after the old read",source.StateRequests==reads+1 && control.OwnedRun is null && !control.Paused);
            offers.PropActions!.PrepareWrites=()=>Task.CompletedTask;
            await offers.PropActions.PrepareAsync("disconnected-hud");
            now+=10000; reads=source.StateRequests;
            offers.Tick(); await offers.PendingPropAction!;
            Is("lease expiry uses one canonical state read",source.StateRequests==reads+1 && !offers.PropActions.Paused);
            // Room entry may spend one read outside the normal timer, including during a slow old-room read.
            source.PendingOffers=new TaskCompletionSource<JsonDocument>();
            var oldRoomOffers=source.PendingOffers;
            reads=source.OfferRequests;
            first=offers.RefreshSemanticOffersAsync();
            position.AdoptRoom("task85-new-room");
            position.AdoptRoom("task85-new-room");
            second=offers.PendingPropAction!;
            Is("room change joins old flight",source.OfferRequests==reads+1);
            var staleOffers=JsonDocument.Parse(source.Offers.ToJsonString());
            source.Offers[0]!["target"]!["room_id"]="task85-new-room";
            source.PendingOffers=null; oldRoomOffers.SetResult(staleOffers);
            await Task.WhenAll(first,second);
            Is("room change re-reads once and publishes immediately",source.OfferRequests==reads+2
                && hud.SceneOwned("propActionSnapshot")!["offers"]![0]!["target"]!["room_id"]!.GetValue<string>()=="task85-new-room");
            reads=source.OfferRequests;
            position.AdoptRoom("task85-new-room");
            await offers.RefreshSemanticOffersAsync(false);
            Is("same room spends no extra read",source.OfferRequests==reads);
            position.AdoptRoom("task85-next-room");
            await offers.PendingPropAction!;
            Is("idle room change bypasses normal budget",source.OfferRequests==reads+1);
            var relocated=JsonNode.Parse(map.RootElement.GetRawText())!;
            foreach(var character in relocated["characters"]!.AsArray())
                if(character!["name"]!.GetValue<string>()==manager.AvatarName) {
                    character["room_id"]="task85-next-room"; character["location_id"]="task85-new-location";
                }
            using var relocatedReceipt=new MapReceipt(now,now,now).Attach(JsonSerializer.SerializeToElement(relocated));
            manager.ApplyPolled(relocatedReceipt.RootElement.Clone());
            await offers.PendingPropAction!;
            Is("location-only change also reads immediately",source.OfferRequests==reads+2);
            return checks;
        } finally { offers?.Dispose(); position?.Dispose(); hud?.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree(); }
    }
}
