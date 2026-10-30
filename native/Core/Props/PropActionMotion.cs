using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;

namespace AnimaNative.Props;

/// <summary>
/// Task 57 / E7-T12: propActionMotion.ts and placeGlyphs.ts pure ports. Public motion contains geometry and
/// clocks only; execution/consent identities belong exclusively to the private prop-action state endpoint.
/// Missing segment paces stop movement; exact corners and the last access point are never smoothed.
/// </summary>
public static class PropActionMotion
{
    public static double Number(JsonNode? n) => n?.GetValue<double>() ?? 0;
    public static string Text(JsonNode? n) => n?.GetValue<string>() ?? "";
    public static P2 LocalApproachPoint(JsonNode path,double ageS)
    {
        double distance=Math.Max(0,Number(path["progress_m"]));
        double time=Math.Max(0,ageS-Math.Max(0,Number(path["starts_in_s"])));
        var points=path["waypoints"]!.AsArray(); var paces=path["paces_m_s_real"] as JsonArray;
        for(int i=1;i<points.Count;i++) {
            double ax=Number(points[i-1]![0]),az=Number(points[i-1]![1]);
            double bx=Number(points[i]![0]),bz=Number(points[i]![1]);
            double length=double.Hypot(bx-ax,bz-az);
            if(length==0) continue;
            if(distance>=length) { distance-=length; continue; }
            double pace=paces is not null && i-1<paces.Count ? Number(paces[i-1]) : 0;
            double remaining=length-distance;
            if(pace>0 && time*pace>=remaining) { time-=remaining/pace; distance=0; continue; }
            double fraction=(distance+Math.Max(0,pace)*time)/length;
            return new(ax+(bx-ax)*fraction,az+(bz-az)*fraction);
        }
        return points.Count>0 ? new(Number(points[^1]![0]),Number(points[^1]![1])) : new(0,0);
    }
    /// <summary>Closest rendered route point by arc length. Equal projections keep the first leg.</summary>
    public static double ProjectApproachM(IReadOnlyList<(double X,double Z)> points,(double X,double Z) point)
    {
        double best=double.PositiveInfinity,result=0,distance=0;
        for(int i=1;i<points.Count;i++) {
            var a=points[i-1]; var b=points[i]; double dx=b.X-a.X,dz=b.Z-a.Z,length=double.Hypot(dx,dz);
            if(length==0) continue;
            double t=Math.Clamp(((point.X-a.X)*dx+(point.Z-a.Z)*dz)/(length*length),0,1);
            double error=double.Hypot(point.X-a.X-t*dx,point.Z-a.Z-t*dz);
            if(error<best) { best=error; result=distance+t*length; }
            distance+=length;
        }
        return result;
    }
    /// <summary>Keep owned playback continuous across delayed polls and slow frames.</summary>
    public static double OwnedApproachStep(double shownM,double targetM,double pace,double catchUpRate,double dt,double startsInS=0,double ageS=0)
        =>startsInS>Math.Max(0,ageS) ? shownM : shownM+Math.Min(Math.Min(Math.Max(0,targetM-shownM),.25),Math.Max(0,Math.Max(pace,catchUpRate))*Math.Max(0,dt));
    /// <summary>Future departures hold; catch-up belongs only to late adoption.</summary>
    public static double OwnedApproachCatchUp(double shownM,double targetM,double totalM,double pace,double startsInS,double ageS)
        =>startsInS>Math.Max(0,ageS) || targetM-shownM<=.25 ? 0 : Math.Max(2*Math.Max(0,pace),(totalM-shownM)/.6);
    public static double EntryPhase(JsonNode entry,double ageS) => Math.Min(1,Math.Max(0,
        (Number(entry["elapsed_game_s"])+Math.Max(0,ageS)*Math.Max(0,Number(entry["game_seconds_per_real_second"])))
        /Number(entry["duration_game_s"])));
    public static double? EntrySupportLift(double firstY,double lastY,double currentY,double accessY,double anchorY,double rootOffset)
    {
        double supportY=anchorY+rootOffset, lift=supportY-rootOffset-accessY, span=lastY-firstY;
        if(Math.Abs(span)<1e-6) return Math.Abs(lift)<1e-6 ? 0 : null;
        return lift*Math.Max(0,Math.Min(1,(currentY-firstY)/span));
    }
    public static string EntryIdentity(JsonNode entry)
    {
        string N(JsonNode? n)=>Number(n).ToString("G",CultureInfo.InvariantCulture);
        string At(JsonNode a)=>string.Join(",",new[]{"x","y","z","yaw"}.Select(k=>N(a[k])));
        return $"{Text(entry["kind"])}|{N(entry["started_game_s"])}|{At(entry["access"]!)}|{At(entry["anchor"]!)}";
    }
    public static JsonArray Choices(JsonNode offer)
    {
        if(offer["required_partner"]?.GetValue<bool>()!=true)
            return new JsonArray(new JsonObject { ["enabled"]=offer["enabled"]?.DeepClone(),["reason"]=offer["reason"]?.DeepClone() });
        return offer["available_targets"] is JsonArray { Count:>0 } targets ? (JsonArray)targets.DeepClone()
            : new JsonArray(new JsonObject { ["enabled"]=false,["reason"]=offer["reason"]?.DeepClone() });
    }
    /// <summary>Task 57: exact room/anchor/placement/variant join; blocked semantic offers remain pickable.</summary>
    public static JsonArray PickablePropRows(JsonNode input)
    {
        var entries=input["entries"]!.AsArray(); var free=new Dictionary<string,int[]>();
        foreach(var offer in input["offers"]!.AsArray()) {
            string id=Text(offer!["id"]);
            if(offer["prop_actions"] is JsonArray { Count:>0 }) {
                var entry=entries.FirstOrDefault(e=>Text(e![0])==id)?[1];
                if(entry is not null) free[id]=Enumerable.Range(0,entry["slots"]!.AsArray().Count).ToArray();
            } else if(Number(offer["free"])>0 && offer["free_slots"] is JsonArray { Count:>0 } slots)
                free[id]=slots.Select(s=>(int)Number(s)).ToArray();
        }
        var rows=new JsonArray();
        foreach(var prop in input["props"]!.AsArray()) {
            if(prop!["mounted"]?.GetValue<bool>()!=true) continue;
            var places=new JsonArray();
            foreach(var pair in entries) {
                string id=Text(pair![0]); var e=pair[1]!;
                if(Text(e["roomId"])!=Text(prop["roomId"])) continue;
                if(Text(prop["role"])=="room") { if(e["diorama"]?.GetValue<bool>()!=true) continue; }
                else {
                    if(e["anchor"] is null) continue;
                    if(Text(e["placementId"]).Length>0 && (Text(e["placementId"])!=Text(prop["placementId"]) || Text(e["variantUid"])!=Text(prop["variantUid"]))) continue;
                    if(!JsonNode.DeepEquals(e["anchor"],prop["anchor"])) continue;
                }
                if(!free.TryGetValue(id,out var indices)) continue;
                var points=new JsonArray(); var slots=e["slots"]!.AsArray();
                foreach(int i in indices) if(i>=0 && i<slots.Count && slots[i] is { } p)
                    points.Add(new JsonObject { ["x"]=Number(p[0]),["z"]=Number(p[2]) });
                if(points.Count>0) places.Add(new JsonObject { ["id"]=id,["free"]=points });
            }
            if(places.Count>0) rows.Add(new JsonObject { ["id"]=prop["id"]!.DeepClone(),["role"]=prop["role"]!.DeepClone(),["places"]=places });
        }
        return rows;
    }
}
