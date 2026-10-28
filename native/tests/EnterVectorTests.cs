using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 47 (E7-T2): every shared enter.json case against the Godot-free browser ports.</summary>
public class EnterVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("enter"));
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = EnterDispatch.Create();
    public static TheoryData<string> Cases => VectorFile.Labels("enter");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
