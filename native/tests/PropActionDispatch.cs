using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Props;

namespace AnimaNative.Tests;

/// <summary>Task 57: shape adapters only, mirroring Task 56's JS adapters; state machines are production objects.</summary>
internal static class PropActionDispatch
{
    private static double N(JsonNode? n) => n?.GetValue<double>() ?? 0;
    private static string S(JsonNode? n) => n?.GetValue<string>() ?? "";
    public static Dictionary<string,Func<JsonArray,JsonNode?>> Create() => new()
    {
        ["localApproachPoint"]=a=> { var p=PropActionMotion.LocalApproachPoint(a[0]!,N(a[1])); return new JsonArray(p.X,p.Z); },
        ["projectApproachM"]=a=>JsonValue.Create(PropActionMotion.ProjectApproachM(a[0]!.AsArray().Select(p=>(N(p![0]),N(p[1]))).ToArray(),(N(a[1]![0]),N(a[1]![1])))),
        ["ownedApproachCatchUp"]=a=>JsonValue.Create(PropActionMotion.OwnedApproachCatchUp(N(a[0]),N(a[1]),N(a[2]),N(a[3]),N(a[4]),N(a[5]))),
        ["ownedApproachStep"]=a=>JsonValue.Create(PropActionMotion.OwnedApproachStep(N(a[0]),N(a[1]),N(a[2]),N(a[3]),N(a[4]),a.Count>5 ? N(a[5]) : 0,a.Count>6 ? N(a[6]) : 0)),
        ["entryPhase"]=a=>JsonValue.Create(PropActionMotion.EntryPhase(a[0]!,N(a[1]))),
        ["entrySupportLift"]=a=>JsonValue.Create(PropActionMotion.EntrySupportLift(N(a[0]),N(a[1]),N(a[2]),N(a[3]),N(a[4]),N(a[5]))),
        ["entryIdentity"]=a=>JsonValue.Create(PropActionMotion.EntryIdentity(a[0]!)),
        ["entryClipSample"]=a=> { double phase=PropActionMotion.EntryPhase(a[0]!,N(a[1])); return new JsonObject { ["phase"]=phase,["clip_s"]=phase*N(a[0]!["clip_duration_s"]) }; },
        ["entrySupportSample"]=a=> { var v=a[0]!; double? lift=PropActionMotion.EntrySupportLift(N(v["first_hips_y"]),N(v["last_hips_y"]),N(v["hips_y"]),N(v["access_y"]),N(v["anchor_y"]),N(v["root_offset"])); return new JsonObject { ["supported"]=lift is not null,["lift"]=lift }; },
        ["pickablePropRows"]=a=>PropActionMotion.PickablePropRows(a[0]!),
        ["propActionChoices"]=a=>PropActionMotion.Choices(a[0]!),
        ["preparationTrace"]=a=>Preparation(a[0]!.AsArray()),
        ["manualGateTrace"]=a=>Manual(a[0]!.AsArray(),a[1]!.AsArray()).GetAwaiter().GetResult(),
        ["positionDrainTrace"]=a=>Drain(a[0]!.AsArray(),a[1]!.AsArray()),
    };
    private static JsonArray Preparation(JsonArray steps)
    {
        var barrier=new PropPreparationBarrier(); var rows=new JsonArray();
        foreach(var step in steps) {
            var row=new JsonObject(); string id=S(step!["id"]);
            switch(S(step["op"])) {
                case "begin": barrier.Begin(id,N(step["now"])); break;
                case "changed": barrier.Changed(id); break;
                case "adopt": barrier.AdoptFreshState(); break;
                case "expire": row["expired"]=barrier.Expire(N(step["now"])); break;
                default: throw new InvalidOperationException();
            }
            row["pending"]=barrier.Pending; rows.Add(row);
        }
        return rows;
    }
    private static async Task<JsonArray> Manual(JsonArray steps,JsonArray journeys)
    {
        var gate=new ManualPropGate(); var attempts=new Dictionary<string,Task>();
        var deferred=new Dictionary<string,TaskCompletionSource>(); int calls=0; var rows=new JsonArray();
        foreach(var step in steps) {
            string id=S(step!["id"]); var row=new JsonObject();
            if(S(step["op"])=="cancel") {
                var task=gate.Cancel(S(step["execution"]),step["journey"]?.GetValue<string>(),()=>{ calls++; var d=new TaskCompletionSource(); deferred[id]=d; return d.Task; });
                if(step["same_as"] is { } same) row["samePromise"]=ReferenceEquals(task,attempts[S(same)]);
                attempts[id]=task;
            } else {
                if(step["accept"]!.GetValue<bool>()) deferred[id].SetResult(); else deferred[id].SetException(new InvalidOperationException("refused"));
                try { await attempts[id].ConfigureAwait(false); row["result"]="resolved"; } catch { row["result"]="rejected"; }
            }
            row["pending"]=gate.Pending; row["calls"]=calls;
            row["withdrawn"]=new JsonArray(journeys.Select(j=>(JsonNode?)JsonValue.Create(gate.Withdrawn(j?.GetValue<string>()))).ToArray()); rows.Add(row);
        }
        return rows;
    }
    private static JsonArray Drain(JsonArray steps,JsonArray waiters)
    {
        var drain=new PositionDrain(); var finishes=new Dictionary<string,Action>(); var waiting=new Dictionary<string,Task>(); var rows=new JsonArray();
        foreach(var step in steps) {
            string id=S(step!["id"]);
            switch(S(step["op"])) {
                case "begin": finishes[id]=drain.Begin(); break;
                case "finish": finishes[id](); finishes.Remove(id); break;
                case "wait": waiting[id]=drain.WaitAsync(); break;
                default: throw new InvalidOperationException();
            }
            rows.Add(new JsonObject { ["drained"]=new JsonArray(waiters.Select(w=>(JsonNode?)JsonValue.Create(waiting.TryGetValue(S(w),out var t) && t.IsCompletedSuccessfully)).ToArray()) });
        }
        return rows;
    }
}
