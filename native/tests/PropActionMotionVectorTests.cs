using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 57 / E7-T12: all 72 hand-derived Task 56 vectors, including asynchronous state traces.</summary>
public class PropActionMotionVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("prop_action_motion"));
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = PropActionDispatch.Create();
    public static TheoryData<string> Cases => VectorFile.Labels("prop_action_motion");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
