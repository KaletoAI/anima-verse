using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;

namespace AnimaNative.Check;

/// <summary>Task 50: async/timeout and exact fixture checks without VSTest's sandbox-blocked socket.</summary>
public static class PositionChannelCheck
{
    public static async Task<int> RunAsync(FixtureSource source)
    {
        int n=0;
        void Is(string label,bool value) { n++; if(!value) throw new InvalidOperationException("position channel "+label); }
        static PositionAnswer Answer(string json,int status=200)
        { using var doc=JsonDocument.Parse(json); return new(status,doc.RootElement.Clone()); }
        double now=330;
        var pending=new TaskCompletionSource<PositionAnswer>();
        var sent=new List<PositionReport>();
        using(var channel=new PositionChannel((p,_)=>{sent.Add(p);return sent.Count==1 ? pending.Task : Task.FromResult(Answer("{\"ok\":true}"));},()=>now,"fixture-session-46"))
        {
            int adopted=0,corrected=0; channel.Adopted+=_=>adopted++; channel.Corrected+=_=>corrected++;
            channel.Tick(new(1,0),true);
            channel.ApplyDriver(new(true,"j",null)); channel.Input(new(1,0));
            Is("one flight reserves cancel",sent.Count==1 && channel.Seq==2 && channel.Driver.Kind==DriverKind.CANCELLING);
            pending.SetResult(Answer("{\"error\":\"late refusal\",\"pos\":{\"x\":99,\"z\":99}}",409));
            await channel.WhenIdle;
            Is("late refusal below floor ignored",sent.Count==2 && adopted==1 && corrected==0);
            Is("reserved seq and timestamp",sent[1].seq==2 && sent[1].t_ms==330);
            channel.ApplyDriver(new(true,"j",2)); Is("ack owns PLAYER",channel.Driver.Kind==DriverKind.PLAYER);
        }
        now=330;
        using(var quiet=new PositionChannel((_,_)=>Task.FromResult(Answer("{\"detail\":{\"message\":\"Keep out.\",\"reason\":\"locked\"}}",409)),()=>now))
        {
            var messages=new List<string>();quiet.Toast+=messages.Add;
            quiet.Tick(new(1,0),true);now=660;quiet.Tick(new(1,0),true);
            Is("quiet for 4 seconds",messages.Count==1 && messages[0]=="Keep out.");
            now=4331;quiet.Tick(new(1,0),true);Is("quiet expires",messages.Count==2);
        }
        using(var network=new PositionChannel((_,_)=>Task.FromException<PositionAnswer>(new InvalidOperationException("offline")),()=>now))
        { network.Tick(new(1,0),true); Is("network stays dirty",network.Dirty); }
        using(var auth=new PositionChannel((_,_)=>Task.FromResult(Answer("{\"detail\":\"Login\"}",401)),()=>now))
        { int hints=0;auth.Toast+=_=>hints++;auth.Tick(new(1,0),true);Is("auth stays dirty without walk toast",auth.Dirty && hints==0); }
        source.SelectPositionScenario("stale");
        using(var stale=new PositionChannel(source.ReportPositionAsync,()=>330,"fixture-session-46"))
        { stale.Tick(new(-3,0),true);Is("stale stays dirty",stale.Dirty); }
        foreach(var scenario in new[]{"accepted","party-follower","refusal-snap"})
        {
            source.SelectPositionScenario(scenario);
            var p=new PositionReport(scenario=="refusal-snap"?10:-3,scenario=="refusal-snap"?2:0,1,330,"fixture-session-46");
            var answer=await source.ReportPositionAsync(p);
            Is("table "+scenario,scenario=="accepted" ? answer.Ok : scenario=="party-follower" ? answer.Status==403 && answer.Reason=="party_follower" : answer.Status==409 && answer.Pos?.X==-3);
            bool exhausted=false;
            try{await source.ReportPositionAsync(p);}catch(InvalidOperationException){exhausted=true;}
            Is("strict exhaustion "+scenario,exhausted);
        }
        source.SelectPositionScenario("accepted"); bool mismatch=false;
        try { await source.ReportPositionAsync(new(42,0,1,330,"fixture-session-46")); } catch(InvalidOperationException){mismatch=true;}
        Is("strict request matching",mismatch && source.PositionRequests.Count==0);
        var lost=new TaskCompletionSource<PositionAnswer>();bool aborted=false;int lateCorrections=0;
        using(var timeout=new PositionChannel((_,ct)=>{ct.Register(()=>aborted=true);return lost.Task;},()=>now))
        {
            timeout.Corrected+=_=>lateCorrections++;
            var elapsed=Stopwatch.StartNew();timeout.Tick(new(1,0),true);
            await timeout.WhenIdle.WaitAsync(TimeSpan.FromSeconds(12));
            Is("8 second timeout aborts flight",aborted && !timeout.InFlight && timeout.Dirty && elapsed.ElapsedMilliseconds>=7900 && elapsed.ElapsedMilliseconds<12000);
            lost.SetResult(Answer("{\"error\":\"abandoned\",\"pos\":{\"x\":99,\"z\":99}}",409));
            Is("abandoned answer cannot correct",lateCorrections==0);
        }
        var late=new TaskCompletionSource<PositionAnswer>();
        using(var guarded=new PositionChannel((_,_)=>late.Task,()=>now))
        {
            int corrected=0;guarded.Corrected+=_=>corrected++;
            guarded.Tick(new(1,0),true);guarded.DiscardPendingAnswers();
            late.SetResult(Answer("{\"error\":\"pre-prop\",\"pos\":{\"x\":99,\"z\":99}}",409));
            await guarded.WhenIdle;Is("prop/exit floor fences previous flight",corrected==0);
        }
        return n;
    }
}
