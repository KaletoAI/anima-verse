using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 51: catches early/duplicate writes, dropped interlocks and cooldowns measured from request instead of answer.</summary>
public sealed class RoomEntryTests
{
    private static PositionAnswer Answer(int status = 200)
    { using var doc = JsonDocument.Parse("{\"ok\":true}"); return new(status,doc.RootElement.Clone()); }

    [Fact]
    public async Task HoldFlightConfirmationAndRejectionUseIndependentClocks()
    {
        double now=0; int requests=0;
        var pending=new TaskCompletionSource<PositionAnswer>();
        using var channel=new RoomEntryChannel((_,_)=>{requests++; return pending.Task;},()=>now);
        var rooms=new List<ElevatorRoom> { new("a",0,new(-3,0)),new("b",0,new(3,0)) };
        channel.Walk("a",new P2(3,0),rooms,0);
        now=1499; channel.Walk("a",new(3,0),rooms,0); Assert.Equal(0,requests);
        now=1500; channel.Walk("a",new(3,0),rooms,0); Assert.Equal(1,requests);
        now=3500; channel.Walk("a",new(3,0),rooms,0); Assert.Equal(1,requests);
        Assert.False(await channel.EnterAsync("a"));
        pending.SetResult(Answer()); await channel.Pending!;
        now=11500; channel.Walk("a",new(3,0),rooms,0); Assert.Equal(1,requests);
        now=11501; channel.Walk("a",new(3,0),rooms,0); Assert.Equal(2,requests);

        using var refused=new RoomEntryChannel((_,_)=>Task.FromResult(Answer(403)),()=>now);
        Assert.False(await refused.EnterAsync("b"));
        now+=3999; Assert.True(refused.Rejected("b"));
        now+=1; Assert.False(refused.Rejected("b"));
    }

    [Fact]
    public async Task CancellationCannotAdoptLateSuccess()
    {
        var pending=new TaskCompletionSource<PositionAnswer>();
        using var channel=new RoomEntryChannel((_,_)=>pending.Task,()=>0);
        var write=channel.EnterAsync("b"); channel.Reset();
        pending.SetResult(Answer()); Assert.False(await write);
        Assert.Null(channel.RequestedRoom);
    }
}
