using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace AnimaNative.Tests;

/// <summary>
/// A tree-walking interpreter for the GLSL subset the garment push is written in (scalar statements, float/int/bool,
/// vec3/vec4 with .xyzw, uniform and local arrays, for / if / else / break / return, ?:, the built-ins clamp, min,
/// max, sqrt, abs, mix, and <c>#define NAME VALUE</c>) — the native counterpart of the browser smokes' mechanical
/// GLSL→JS rewrite: it EXECUTES the shader text (<see cref="Figures.GarmentPush"/>) so the tests can compare it with
/// the TypeScript's vectors. Arithmetic in double (the GPU runs float32; the vectors' tolerance covers neither, so the
/// comparison is against the double twin). Anything outside the subset throws — the shader text may not drift into
/// constructs this cannot check without the test noticing.
/// </summary>
internal sealed class GlslMini
{
    public sealed class Vec { public double[] C; public Vec(params double[] c) { C = c; } }
    private sealed class Arr { public object[] Items; public Arr(object[] items) { Items = items; } }
    private sealed class BreakSignal : Exception { }
    private sealed class ReturnSignal : Exception { public object Value; public ReturnSignal(object v) { Value = v; } }

    private abstract record Node;
    private sealed record Num(object V) : Node;
    private sealed record Id(string Name) : Node;
    private sealed record Index(Node Target, Node At) : Node;
    private sealed record Member(Node Target, string Name) : Node;
    private sealed record Call(string Name, List<Node> Args) : Node;
    private sealed record Unary(string Op, Node X) : Node;
    private sealed record Binary(string Op, Node L, Node R) : Node;
    private sealed record Cond(Node C, Node A, Node B) : Node;
    private sealed record Assign(string Op, Node Target, Node Value) : Node;
    private sealed record PostInc(string Op, Node Target) : Node;
    private sealed record Decl(string Type, string Name, Node? Size, Node? Init) : Node;
    private sealed record Block(List<Node> Body) : Node;
    private sealed record For(Node? Init, Node? Test, Node? Step, Node Body) : Node;
    private sealed record If(Node C, Node Then, Node? Else) : Node;
    private sealed record BreakNode : Node;
    private sealed record Return(Node? Value) : Node;
    private sealed record ExprStmt(Node X) : Node;
    private sealed record Function(string Name, List<(string Type, string Name)> Params, Block Body);

    private static readonly string[] Types = { "float", "int", "bool", "vec3", "vec4" };
    private readonly Dictionary<string, Function> _functions = new();
    private readonly Dictionary<string, object> _globals = new();
    private List<string> _t = new();
    private int _p;

    /// <summary>Statements executed (a measure that the code ran at all).</summary>
    public long Steps { get; private set; }

    public GlslMini(string source)
    {
        var defines = new Dictionary<string, string>();
        var lines = new List<string>();
        foreach (var raw in source.Split('\n'))
        {
            var line = Regex.Replace(raw, "//.*$", "");
            var m = Regex.Match(line, @"^\s*#define\s+(\w+)\s+(.+?)\s*$");
            if (m.Success) { defines[m.Groups[1].Value] = m.Groups[2].Value; continue; }
            if (line.TrimStart().StartsWith('#')) throw new NotSupportedException("preprocessor: " + line);
            lines.Add(line);
        }
        var tokens = Regex.Matches(string.Join("\n", lines),
                @"\d+\.\d*(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+|\d+|[A-Za-z_]\w*|<=|>=|==|!=|&&|\|\||\+\+|--|\+=|-=|\*=|/=|[-+*/<>=!?:;,.(){}\[\]]|\S")
            .Select(x => x.Value).ToList();
        // #define: whole-token substitution, repeated until stable (a define may name another).
        for (int pass = 0; pass < 4; pass++)
            tokens = tokens.SelectMany(tk => defines.TryGetValue(tk, out var v)
                ? Regex.Matches(v, @"\d+\.\d*(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+|\d+|[A-Za-z_]\w*|\S").Select(x => x.Value) : new[] { tk }).ToList();
        _t = tokens;
        _p = 0;
        while (_p < _t.Count) TopLevel();
    }

    /// <summary>Set a uniform (float / int / Vec / Vec[]).</summary>
    public void Uniform(string name, object value) => _globals[name] = value is Vec[] vs ? new Arr(vs.Cast<object>().ToArray()) : value;

    public object Invoke(string name, params object[] args)
    {
        var f = _functions[name];
        var scope = new Dictionary<string, object>();
        for (int i = 0; i < args.Length; i++) scope[f.Params[i].Name] = Copy(args[i]);
        var scopes = new List<Dictionary<string, object>> { _globals, scope };
        try { Exec(f.Body, scopes); }
        catch (ReturnSignal r) { return r.Value; }
        throw new InvalidOperationException(name + " ended without return");
    }

    // ---- parsing ----------------------------------------------------------------------------------------------------

    private string Peek(int k = 0) => _p + k < _t.Count ? _t[_p + k] : "";
    private string Next() => _t[_p++];
    private void Expect(string tk) { if (Next() != tk) throw new FormatException($"expected '{tk}' at token {_p - 1} ('{_t[_p - 1]}')"); }

    private void TopLevel()
    {
        if (Peek() == "uniform")
        {
            Next(); Next(); Next();   // uniform TYPE NAME
            if (Peek() == "[") { Next(); ParseExpr(); Expect("]"); }
            Expect(";");
            return;
        }
        var type = Next();
        var name = Next();
        Expect("(");
        var ps = new List<(string, string)>();
        while (Peek() != ")")
        {
            var pt = Next();
            ps.Add((pt, Next()));
            if (Peek() == ",") Next();
        }
        Expect(")");
        if (!Types.Contains(type) && type != "void") throw new NotSupportedException("return type " + type);
        _functions[name] = new Function(name, ps, ParseBlock());
    }

    private Block ParseBlock()
    {
        Expect("{");
        var body = new List<Node>();
        while (Peek() != "}") body.Add(ParseStmt());
        Next();
        return new Block(body);
    }

    private Node ParseStmt()
    {
        var tk = Peek();
        if (tk == "{") return ParseBlock();
        if (tk == "for")
        {
            Next(); Expect("(");
            Node? init = Peek() == ";" ? null : ParseSimple();
            Expect(";");
            Node? test = Peek() == ";" ? null : ParseExpr();
            Expect(";");
            Node? step = Peek() == ")" ? null : ParseExpr();
            Expect(")");
            return new For(init, test, step, ParseStmt());
        }
        if (tk == "if")
        {
            Next(); Expect("(");
            var c = ParseExpr();
            Expect(")");
            var then = ParseStmt();
            Node? els = null;
            if (Peek() == "else") { Next(); els = ParseStmt(); }
            return new If(c, then, els);
        }
        if (tk == "break") { Next(); Expect(";"); return new BreakNode(); }
        if (tk == "return") { Next(); var v = Peek() == ";" ? null : ParseExpr(); Expect(";"); return new Return(v); }
        var s = ParseSimple();
        Expect(";");
        return s;
    }

    private Node ParseSimple()
    {
        if (Types.Contains(Peek()))
        {
            var type = Next();
            var name = Next();
            Node? size = null, init = null;
            if (Peek() == "[") { Next(); size = ParseExpr(); Expect("]"); }
            if (Peek() == "=") { Next(); init = ParseExpr(); }
            return new Decl(type, name, size, init);
        }
        return new ExprStmt(ParseExpr());
    }

    private Node ParseExpr()
    {
        var left = ParseCond();
        if (Peek() is "=" or "+=" or "-=" or "*=" or "/=") { var op = Next(); return new Assign(op, left, ParseExpr()); }
        return left;
    }

    private Node ParseCond()
    {
        var c = ParseBin(0);
        if (Peek() != "?") return c;
        Next();
        var a = ParseExpr();
        Expect(":");
        return new Cond(c, a, ParseExpr());
    }

    private static readonly string[][] Levels =
    {
        new[] { "||" }, new[] { "&&" }, new[] { "==", "!=" }, new[] { "<", ">", "<=", ">=" }, new[] { "+", "-" }, new[] { "*", "/" },
    };

    private Node ParseBin(int level)
    {
        if (level == Levels.Length) return ParseUnary();
        var left = ParseBin(level + 1);
        while (Levels[level].Contains(Peek())) { var op = Next(); left = new Binary(op, left, ParseBin(level + 1)); }
        return left;
    }

    private Node ParseUnary()
    {
        if (Peek() is "-" or "!") { var op = Next(); return new Unary(op, ParseUnary()); }
        return ParsePostfix();
    }

    private Node ParsePostfix()
    {
        Node x;
        var tk = Next();
        if (tk == "(") { x = ParseExpr(); Expect(")"); }
        else if (char.IsDigit(tk[0]))
            x = new Num(tk.Contains('.') || tk.Contains('e') || tk.Contains('E')
                ? (object)double.Parse(tk, CultureInfo.InvariantCulture) : int.Parse(tk, CultureInfo.InvariantCulture));
        else if (Peek() == "(")
        {
            Next();
            var args = new List<Node>();
            while (Peek() != ")") { args.Add(ParseExpr()); if (Peek() == ",") Next(); }
            Next();
            x = new Call(tk, args);
        }
        else x = new Id(tk);
        while (true)
        {
            if (Peek() == "[") { Next(); var at = ParseExpr(); Expect("]"); x = new Index(x, at); }
            else if (Peek() == ".") { Next(); x = new Member(x, Next()); }
            else if (Peek() is "++" or "--") x = new PostInc(Next(), x);
            else return x;
        }
    }

    // ---- execution --------------------------------------------------------------------------------------------------

    private static object Copy(object v) => v is Vec vec ? new Vec((double[])vec.C.Clone()) : v;

    private void Exec(Node n, List<Dictionary<string, object>> scopes)
    {
        Steps++;
        switch (n)
        {
            case Block b:
                scopes.Add(new Dictionary<string, object>());
                try { foreach (var s in b.Body) Exec(s, scopes); }
                finally { scopes.RemoveAt(scopes.Count - 1); }
                break;
            case Decl d:
                var top = scopes[^1];
                if (top.ContainsKey(d.Name)) throw new InvalidOperationException("redefinition of " + d.Name);
                if (d.Size is not null)
                {
                    var lenV = Eval(d.Size, scopes);
                    if (lenV is not int len) throw new InvalidOperationException($"array size of {d.Name}: {lenV} ({lenV.GetType().Name}) from {d.Size}");
                    top[d.Name] = new Arr(Enumerable.Range(0, len).Select(_ => Zero(d.Type)).ToArray());
                }
                else top[d.Name] = d.Init is null ? Zero(d.Type) : Convert(d.Type, Copy(Eval(d.Init, scopes)));
                break;
            case For f:
                scopes.Add(new Dictionary<string, object>());
                try
                {
                    if (f.Init is not null) Exec(f.Init, scopes);
                    while (f.Test is null || (bool)Eval(f.Test, scopes))
                    {
                        try { Exec(f.Body, scopes); }
                        catch (BreakSignal) { break; }
                        if (f.Step is not null) Eval(f.Step, scopes);
                    }
                }
                finally { scopes.RemoveAt(scopes.Count - 1); }
                break;
            case If i:
                if ((bool)Eval(i.C, scopes)) Exec(i.Then, scopes);
                else if (i.Else is not null) Exec(i.Else, scopes);
                break;
            case BreakNode: throw new BreakSignal();
            case Return r: throw new ReturnSignal(r.Value is null ? 0 : Copy(Eval(r.Value, scopes)));
            case ExprStmt e: Eval(e.X, scopes); break;
            default: throw new NotSupportedException(n.GetType().Name);
        }
    }

    private static object Zero(string type) => type switch
    {
        "float" => 0.0, "int" => 0, "bool" => false, "vec3" => new Vec(0, 0, 0), "vec4" => new Vec(0, 0, 0, 0),
        _ => throw new NotSupportedException(type),
    };

    private static object Convert(string type, object v) => type switch
    {
        "float" => v is double ? v : throw new InvalidOperationException($"float from {v.GetType().Name}"),
        "int" => v is int ? v : throw new InvalidOperationException($"int from {v.GetType().Name}"),
        _ => v,
    };

    private static Dictionary<string, object> Owner(string name, List<Dictionary<string, object>> scopes)
    {
        for (int i = scopes.Count - 1; i >= 0; i--) if (scopes[i].ContainsKey(name)) return scopes[i];
        throw new KeyNotFoundException("undeclared " + name);
    }

    private static int Comp(string m) => m switch { "x" => 0, "y" => 1, "z" => 2, "w" => 3, _ => throw new NotSupportedException("." + m) };

    private object Eval(Node n, List<Dictionary<string, object>> scopes)
    {
        switch (n)
        {
            case Num num: return num.V;
            case Id id: return Owner(id.Name, scopes)[id.Name];
            case Index ix: return ((Arr)Eval(ix.Target, scopes)).Items[(int)Eval(ix.At, scopes)];
            case Member m:
                var mv = (Vec)Eval(m.Target, scopes);
                return m.Name.Length == 1 ? mv.C[Comp(m.Name)] : new Vec(m.Name.Select(ch => mv.C[Comp(ch.ToString())]).ToArray());
            case Unary u:
                var x = Eval(u.X, scopes);
                return u.Op == "!" ? !(bool)x : x is int xi ? -xi : -(double)x;
            case Cond c: return (bool)Eval(c.C, scopes) ? Eval(c.A, scopes) : Eval(c.B, scopes);
            case Binary b:
                if (b.Op == "&&") return (bool)Eval(b.L, scopes) && (bool)Eval(b.R, scopes);
                if (b.Op == "||") return (bool)Eval(b.L, scopes) || (bool)Eval(b.R, scopes);
                return Arith(b.Op, Eval(b.L, scopes), Eval(b.R, scopes));
            case Call call:
                var a = call.Args.Select(e => Eval(e, scopes)).ToArray();
                return call.Name switch
                {
                    "clamp" => Math.Min(Math.Max((double)a[0], (double)a[1]), (double)a[2]),
                    "min" => Math.Min((double)a[0], (double)a[1]),
                    "max" => Math.Max((double)a[0], (double)a[1]),
                    "sqrt" => Math.Sqrt((double)a[0]),
                    "abs" => Math.Abs((double)a[0]),
                    // mix(x, y, a) = x · (1 − a) + y · a, per component (the GLSL definition)
                    "mix" when a[0] is Vec mx && a[1] is Vec my =>
                        new Vec(mx.C.Select((c, k) => c * (1 - (double)a[2]) + my.C[k] * (double)a[2]).ToArray()),
                    _ => Invoke(call.Name, a),
                };
            case Assign asg:
                var value = Eval(asg.Value, scopes);
                if (asg.Op != "=") value = Arith(asg.Op[..1], Eval(asg.Target, scopes), value);
                Store(asg.Target, Copy(value), scopes);
                return value;
            case PostInc pi:
                var old = Eval(pi.Target, scopes);
                Store(pi.Target, pi.Op == "++" ? (int)old + 1 : (int)old - 1, scopes);
                return old;
            default: throw new NotSupportedException(n.GetType().Name);
        }
    }

    private void Store(Node target, object value, List<Dictionary<string, object>> scopes)
    {
        switch (target)
        {
            case Id id:
                var owner = Owner(id.Name, scopes);
                if (ReferenceEquals(owner, _globals)) throw new InvalidOperationException("write to uniform " + id.Name);
                var before = owner[id.Name];
                if (before.GetType() != value.GetType()) throw new InvalidOperationException($"{id.Name}: {before.GetType().Name} ← {value.GetType().Name}");
                owner[id.Name] = value;
                break;
            case Index ix:
                var arr = (Arr)Eval(ix.Target, scopes);
                int at = (int)Eval(ix.At, scopes);
                if (arr.Items[at].GetType() != value.GetType()) throw new InvalidOperationException("array element type");
                arr.Items[at] = value;
                break;
            case Member m when m.Target is Id vid:
                var vec = (Vec)Owner(vid.Name, scopes)[vid.Name];
                vec.C[Comp(m.Name)] = (double)value;
                break;
            default: throw new NotSupportedException("store to " + target.GetType().Name);
        }
    }

    private static object Arith(string op, object l, object r)
    {
        if (l is int li && r is int ri)
            return op switch
            {
                "+" => li + ri, "-" => li - ri, "*" => li * ri, "/" => li / ri,
                "<" => li < ri, ">" => li > ri, "<=" => li <= ri, ">=" => li >= ri, "==" => li == ri, "!=" => li != ri,
                _ => throw new NotSupportedException(op),
            };
        if (l is not double ld || r is not double rd) throw new InvalidOperationException($"{l.GetType().Name} {op} {r.GetType().Name}");
        return op switch
        {
            "+" => ld + rd, "-" => ld - rd, "*" => ld * rd, "/" => ld / rd,
            "<" => ld < rd, ">" => ld > rd, "<=" => ld <= rd, ">=" => ld >= rd, "==" => ld == rd, "!=" => ld != rd,
            _ => throw new NotSupportedException(op),
        };
    }
}
