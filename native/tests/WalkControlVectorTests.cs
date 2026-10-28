using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 47 (E7-T2): every shared walk_control.json case against the Godot-free browser ports.</summary>
public class WalkControlVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("walk_control"));
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = WalkControlDispatch.Create();
    public static TheoryData<string> Cases => VectorFile.Labels("walk_control");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
