using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;

namespace AnimaNative.Figures;

/// <summary>
/// The bone graph the secondary motion works on (the bone-matrix abstraction of three's <c>Object3D</c> tree):
/// node i has a name, a parent (−1 = it hangs directly in the <see cref="Base"/> frame) and a LOCAL matrix the host
/// writes every frame from its animated pose; <see cref="UpdateWorld"/> composes the world matrices like three's
/// <c>updateMatrixWorld</c>. On Godot a node is a <c>Skeleton3D</c> bone, <see cref="Base"/> the skeleton's global
/// transform; in the vectors it is three's bone list under an identity root group.
/// </summary>
public sealed class MotionRig
{
    public IReadOnlyList<string> Names { get; }
    public IReadOnlyList<int> Parents { get; }
    /// <summary>The world matrix of the frame the parentless nodes hang in (three: the root's ancestors and itself).</summary>
    public Affine Base { get; set; } = Affine.Identity;
    public Affine[] Local { get; }
    public Affine[] World { get; }
    /// <summary>Children of each node in index order; index <see cref="Count"/> = the parentless nodes.</summary>
    public IReadOnlyList<IReadOnlyList<int>> Children { get; }
    public IReadOnlyList<int> PreOrder { get; }
    public int Count => Names.Count;

    public MotionRig(IReadOnlyList<string> names, IReadOnlyList<int> parents)
    {
        if (names.Count != parents.Count) throw new ArgumentException("names and parents differ in length");
        Names = names;
        Parents = parents;
        Local = Enumerable.Repeat(Affine.Identity, names.Count).ToArray();
        World = Enumerable.Repeat(Affine.Identity, names.Count).ToArray();
        var children = Enumerable.Range(0, names.Count + 1).Select(_ => new List<int>()).ToList();
        for (int i = 0; i < names.Count; i++)
        {
            int p = parents[i];
            children[p < 0 || p >= names.Count ? names.Count : p].Add(i);
        }
        Children = children;
        var order = new List<int>();
        void Visit(int i)
        {
            order.Add(i);
            foreach (int c in children[i]) Visit(c);
        }
        foreach (int r in children[names.Count]) Visit(r);
        PreOrder = order;
    }

    public int Parent(int node) => node < 0 ? -1 : Parents[node] is var p && p >= 0 && p < Count ? p : -1;
    public Affine WorldOf(int node) => node < 0 ? Base : World[node];

    /// <summary>three <c>updateMatrixWorld(true)</c>: world = parent world · local, parents first.</summary>
    public void UpdateWorld()
    {
        foreach (int i in PreOrder) World[i] = WorldOf(Parent(i)).Times(Local[i]);
    }

    /// <summary>Depth below the base frame (three counts the root's ancestors too: a constant shift, only order matters).</summary>
    public int Depth(int node)
    {
        int d = 0;
        for (int p = Parent(node); p >= 0; p = Parent(p)) d++;
        return d;
    }
}

/// <summary>
/// One skinned primitive's skin data for the centroid measure: per skin joint its rig node and the matrix taking a raw
/// vertex into that bone's bind frame (three <c>boneInverse · bindMatrix</c>, Godot's <c>Skin</c> bind pose), and the
/// vertex positions, joint indices and weights (4 per vertex, or 8 for Godot's 8-weight surfaces: the stride is
/// the joint count over the vertex count).
/// </summary>
public sealed record MotionSkin(int[] JointNodes, Affine[] ToBone, float[] Positions, int[] Joints, float[] Weights);

/// <summary>
/// THE SECONDARY MOTION — packages/scene-render/src/secondaryMotion.ts, line by line, on a <see cref="MotionRig"/>.
/// Vectors: shared/test-vectors/secondary_{particle,angle,params,chain}.json (hand derivations in
/// client3d/scripts/smoke_secondary_motion.mjs); anchor blend: scripts/smoke_extension_rig_anchor_blend.mjs.
///
/// Built once while the rig is in its BIND pose (<see cref="MotionRig.World"/> = bind world matrices). Then each frame:
/// the host writes the animated local matrices of every node it animates, calls <see cref="Update"/>, and reads back
/// <see cref="MotionRig.Local"/> / <see cref="MotionRig.World"/> of the nodes in <see cref="Owned"/> (driven and
/// rigid-tail links — the solver keeps their local matrices across frames, as three keeps <c>matrixAutoUpdate = false</c>
/// bones) and of their descendants. Units: metres, real seconds, world gravity (0, −9.81, 0).
/// </summary>
public sealed class SecondaryMotion
{
    /// <summary>Maximum transverse compensation: strong flattening must not inflate the mesh.</summary>
    public const double SpreadCap = 1.6;
    private static readonly V3 Gravity = new(0, -9.81, 0);
    private static readonly V3 BindUp = new(0, 1, 0);

    // ---- the pure functions of the vectors -------------------------------------------------------------------------

    /// <summary>
    /// <c>stepSecondaryParticle</c>: exact propagation around a linearly moving static-equilibrium target
    /// (x = p − T', w = v − v_T' gives x'' + 2ζω x' + ω² x = 0), every damping regime.
    /// </summary>
    public static (V3 P, V3 V) StepParticle(V3 p, V3 v, V3 target, V3 targetVelocity, MotionGroup g, double h)
    {
        double zeta = g.Zeta ?? double.NaN;
        double omega = 2 * Math.PI * (g.FreqHz ?? double.NaN);
        var x = p - target;
        var w = v - targetVelocity;
        double alpha = zeta * omega;
        double xx, xw, wx, ww;
        if (omega * omega < 1e-12)
        {
            xx = ww = 1; xw = h; wx = 0;
        }
        else if (zeta > 1)
        {
            double z = zeta + Math.Sqrt(zeta * zeta - 1);
            double slow = -omega / z, fast = -omega * z;
            double eSlow = Math.Exp(slow * h), eFast = Math.Exp(fast * h);
            double den = slow - fast;
            xx = (slow * eFast - fast * eSlow) / den;
            xw = (eSlow - eFast) / den;
            wx = omega * omega * (eFast - eSlow) / den;
            ww = (slow * eSlow - fast * eFast) / den;
        }
        else
        {
            double damped = omega * Math.Sqrt(1 - zeta * zeta);
            double decay = Math.Exp(-alpha * h);
            double c = Math.Cos(damped * h);
            double sh = damped == 0 ? h : Math.Sin(damped * h) / damped;
            xx = decay * (c + alpha * sh);
            xw = decay * sh;
            wx = -omega * omega * xw;
            ww = decay * (c - alpha * sh);
        }
        var rp = target + targetVelocity * h + x * xx + w * xw;
        var rv = targetVelocity + x * wx + w * ww;
        return (rp, rv);
    }

    /// <summary><c>softMotionAngle</c>: linear below half the limit, then C1 tanh saturation; 0 for a limit ≤ 0.</summary>
    public static double SoftMotionAngle(double angle, double limit)
    {
        if (limit <= 0) return 0;
        double knee = limit / 2;
        return angle <= knee ? angle : knee + knee * Math.Tanh((angle - knee) / knee);
    }

    /// <summary><c>blendMotionParams</c>: the blended fields eased by smoothstep over 1.5 s, the rest from <paramref name="to"/>.</summary>
    public static MotionGroup BlendParams(MotionGroup from, MotionGroup to, double elapsed)
    {
        double t = Math.Max(0, Math.Min(1, elapsed / 1.5));
        double weight = t * t * (3 - 2 * t);
        var result = to;
        foreach (var field in MotionGroup.BlendedFields)
        {
            double fallback = field is "head_sag" or "length" or "girth" ? 1 : field == "flatten_floor" ? to.Squash.Min : field == "spread" ? 0.5 : 0;
            double a = from.Get(field) ?? fallback, b = to.Get(field) ?? fallback;
            result = result.With(field, a + (b - a) * weight);
        }
        return result;
    }

    private static double Clamp(double x, double lo, double hi) => Math.Max(lo, Math.Min(hi, x));
    private static double Smooth(double f) => f * f * (3 - 2 * f);

    private static double StraighteningFraction(double rest, double threshold)
    {
        double f = threshold > 0 ? Clamp(Math.Abs(rest) * 180 / Math.PI / threshold, 0, 1) : 0;
        return f * f * (3 - 2 * f);
    }

    private static double RestAngle(MotionGroup g) => Clamp(g.RestDeg, -g.RestMaxDeg, g.RestMaxDeg) * Math.PI / 180;

    // ---- state ----------------------------------------------------------------------------------------------------

    private sealed class Bind
    {
        public required int Node;
        public required Affine Local;
        public V3 Centroid;
        public double Mass;
        public V3 ScaleAxis;
        public V3 CentroidWorld;
        public required V3 GravityRest;
        public double GravityProjection;
        public V3 BodyFront;
        public required V3 Head;
        public required V3 ParentHead;
        public required Quat WorldRotation;
        public Affine PureWorld = Affine.Identity;
        public V3 Lateral, SingleLateral, PairedLateral;
        public Quat CenteringRotation = Quat.Identity;
        public required int Depth;
        public Quat Rotation = Quat.Identity;
        public Quat StraightenRotation = Quat.Identity;
        public required Quat LocalRotation;
        public required Affine BindWorldInverse;
        public List<(Bind Bind, double Share)>? AnchorBlend;
    }

    private sealed class Sag
    {
        public Affine Frame;
        public Quat Rotation, Q;
        public V3 Head, Centre, Force, Torque;
        public double Weight;
    }

    private sealed class Particle
    {
        public required Bind Bind;
        public required List<Bind> Roots;
        public List<Particle>? Chain;
        public double MotionShare;
        public Sag? Sag;
        public required MotionGroup Params, ParamsFrom, ParamsTo;
        public double ParamsBlend;
        public double StaticFrequency, StaticFrequencyFrom, StaticFrequencyTo;
        public double StaticWeight, StaticWeightFrom, StaticWeightTo;
        public V3? P;
        public V3 V;
        public V3? Target;
        public double Rest, RestFrom, RestTo, Blend;
        public double Straighten, StraightenFrom, StraightenRestFrom, StraightenBlend, StraightenThreshold;
        public Quat? AnchorRotation;
    }

    private readonly MotionRig _rig;
    private readonly Dictionary<int, Bind> _binds = new();
    private readonly List<Bind> _bindOrder = new();
    private readonly Dictionary<string, Bind> _byName = new();
    private readonly V3[] _bindHeads;
    private List<Particle> _particles = new();
    private List<Bind> _rigids = new();
    private readonly Dictionary<int, Particle> _driven = new();
    private bool _far;
    private bool _disposed;

    /// <summary>Nodes whose local matrix the solver owns (driven particles and rigid-tail links).</summary>
    public IReadOnlyCollection<int> Owned => _owned;
    private readonly HashSet<int> _owned = new();
    private readonly Dictionary<int, Affine> _ownedLocal = new();
    public int ParticleCount => _particles.Count;
    public int RigidCount => _rigids.Count;
    /// <summary>The driven nodes in solver order (for the check and the log).</summary>
    public IEnumerable<int> DrivenNodes => _particles.Select(p => p.Bind.Node);

    /// <summary>
    /// The per-bind centroid measure (the vertex pass of <c>createSecondaryMotion</c>): ALL positive skin weights,
    /// aggregated over every skin, each vertex taken into the bone's bind frame. Hosts cache it per template (three's
    /// <c>centroidCache</c>). Node → (centroid in the bone's bind frame, summed weight).
    /// </summary>
    public static Dictionary<int, (V3 Centroid, double Mass)> MeasureCentroids(IEnumerable<MotionSkin> skins)
    {
        var sums = new Dictionary<int, (V3 Sum, double Weight)>();
        foreach (var s in skins)
        {
            int n = s.Positions.Length / 3;
            if (n == 0) continue;
            int stride = s.Joints.Length / n;
            for (int i = 0; i < n; i++)
            {
                var raw = new V3(s.Positions[i * 3], s.Positions[i * 3 + 1], s.Positions[i * 3 + 2]);
                for (int j = 0; j < stride; j++)
                {
                    double weight = s.Weights[i * stride + j];
                    int index = s.Joints[i * stride + j];
                    if (weight <= 0 || index < 0 || index >= s.JointNodes.Length) continue;
                    int node = s.JointNodes[index];
                    var vertex = s.ToBone[index].Apply(raw);
                    var acc = sums.TryGetValue(node, out var a) ? a : (V3.Zero, 0);
                    sums[node] = (acc.Item1 + vertex * weight, acc.Item2 + weight);
                }
            }
        }
        return sums.Where(e => e.Value.Weight > 0).ToDictionary(e => e.Key, e => (e.Value.Sum * (1 / e.Value.Weight), e.Value.Weight));
    }

    /// <summary>
    /// <c>createSecondaryMotion</c> with the rig in bind pose (<see cref="MotionRig.UpdateWorld"/> called on the bind
    /// locals). <paramref name="skinJoints"/>: the nodes of every skin's joints, in skin order (the bind set);
    /// <paramref name="centroids"/>: <see cref="MeasureCentroids"/> (node → centroid, mass); <paramref name="anchorBlend"/>:
    /// a node's glTF extras <c>anchor_blend</c> (bone name → share) or null.
    /// </summary>
    public SecondaryMotion(MotionRig rig, IEnumerable<int> skinJoints, IReadOnlyDictionary<int, (V3 Centroid, double Mass)> centroids,
                           Func<int, IReadOnlyDictionary<string, double>?> anchorBlend, MotionPayload? payload)
    {
        _rig = rig;
        foreach (int node in skinJoints)
        {
            if (_binds.ContainsKey(node)) continue;
            var world = rig.World[node];
            var q = RigMath.RotationOf(world).Inverse();
            var (pos, localQ, _) = RigMath.Decompose(rig.Local[node]);
            var b = new Bind
            {
                Node = node, Local = rig.Local[node], GravityRest = q.Rotate(Gravity), Head = world.Position(),
                ParentHead = rig.WorldOf(rig.Parent(node)).Position(), WorldRotation = q.Inverse(), Depth = rig.Depth(node),
                LocalRotation = localQ, BindWorldInverse = world.Inverted(),
            };
            if (centroids.TryGetValue(node, out var c))
            {
                b.Centroid = c.Centroid;
                b.Mass = c.Mass;
            }
            _binds[node] = b;
            _bindOrder.Add(b);
        }
        foreach (var b in _bindOrder)
        {
            b.CentroidWorld = rig.World[b.Node].Apply(b.Centroid);
            // Capture the actual bind lever, including non-uniform model scale.
            b.GravityProjection = Gravity.Dot((b.CentroidWorld - b.Head).Normalized()) / 9.81;
        }
        _bindHeads = Enumerable.Range(0, rig.Count).Select(i => rig.World[i].Position()).ToArray();
        foreach (var b in _bindOrder) _byName[BoneNames.Norm(rig.Names[b.Node])] = b;
        // The rigger spread the tissue a built bone takes over across several bones; the build measures the shares and
        // stores them on the joint (glTF extras anchor_blend). Unknown names and non-positive shares are ignored.
        foreach (var b in _bindOrder)
        {
            if (anchorBlend(b.Node) is not { } raw) continue;
            var entries = raw.Select(e => (Bind: _byName.TryGetValue(BoneNames.Norm(e.Key), out var x) ? x : null, Share: e.Value))
                             .Where(e => e.Bind is not null && e.Bind != b && double.IsFinite(e.Share) && e.Share > 0)
                             .Select(e => (e.Bind!, e.Share)).ToList();
            double total = entries.Sum(e => e.Share);
            if (total > 0) b.AnchorBlend = entries.Select(e => (e.Item1, e.Share / total)).ToList();
        }
        Configure(payload);
    }

    /// <summary>Does any bone of the payload exist in the rig (the TS factory's <c>matching</c>)?</summary>
    public static bool Matches(MotionRig rig, MotionPayload? payload)
    {
        if (payload is null) return false;
        var keys = payload.BoneKeys();
        return keys.Count > 0 && rig.Names.Any(n => keys.Contains(BoneNames.Norm(n)));
    }

    /// <summary><c>configure(payload)</c>: (re)select the chains; a known particle keeps its state and eases to the new values.</summary>
    public void Configure(MotionPayload? next)
    {
        if (_disposed) return;
        var previous = _particles.ToDictionary(p => p.Bind.Node);
        var selected = new HashSet<int>();
        var extensionNames = next?.BoneKeys() ?? new HashSet<string>();
        var nextParticles = new List<Particle>();
        var nextRigids = new List<Bind>();
        foreach (var (_, ps) in next?.Groups ?? Array.Empty<(string, MotionGroup)>())
        {
            var maybe = ps.Bones.Select(n => _byName.TryGetValue(BoneNames.Norm(n), out var b) ? b : null).ToList();
            // Absent/partial groups and vertices without influence are ordinary skips.
            if (maybe.Any(b => b is null || b.Centroid.LengthSq() < 1e-12)) continue;
            var chain = maybe.Select(b => b!).ToList();
            var members = chain.Select(b => b.Node).ToHashSet();
            var roots = chain.Where(b => !members.Contains(_rig.Parent(b.Node))).ToList();
            Bind? ChildOf(Bind b) => chain.FirstOrDefault(c => _rig.Parent(c.Node) == b.Node);
            foreach (var b in chain)
            {
                var child = ChildOf(b);
                if (child is not null) b.ScaleAxis = child.Local.Position();
                else if (ps.ScaleAxis == "bone") b.ScaleAxis = new V3(0, 1, 0);
                else b.ScaleAxis = b.Centroid;
                if (b.ScaleAxis.LengthSq() < 1e-12) b.ScaleAxis = b.Centroid;
                b.ScaleAxis = b.ScaleAxis.Normalized();
            }
            // Derive front once from immutable bind geometry, never a model axis.
            V3 meanRoot = V3.Zero, meanParent = V3.Zero, meanTarget = V3.Zero;
            foreach (var b in roots)
            {
                meanRoot += b.Head;
                meanParent += b.ParentHead;
            }
            meanRoot *= 1.0 / roots.Count;
            meanParent *= 1.0 / roots.Count;
            foreach (var b in chain) meanTarget += b.CentroidWorld;
            meanTarget *= 1.0 / chain.Count;
            static V3 Horizontal(V3 v) => v - BindUp * v.Dot(BindUp);
            var front = Horizontal(meanRoot - meanParent);
            if (front.LengthSq() < 1e-10) front = Horizontal(meanTarget - meanRoot);
            front = front.Normalized();
            if (roots.Count == 1)
            {
                // The root may sit off the midline: front from the widest symmetric pair of the parent's other children.
                int parent = _rig.Parent(roots[0].Node);
                var candidates = _rig.Children[parent < 0 ? _rig.Count : parent]
                    .Where(o => o != roots[0].Node && !extensionNames.Contains(BoneNames.Norm(_rig.Names[o]))).ToList();
                double maxDistance = 0, maxSeparation = 0;
                var widest = V3.Zero;
                for (int i = 0; i < candidates.Count; i++)
                {
                    var head = _bindHeads[candidates[i]];
                    maxDistance = Math.Max(maxDistance, Horizontal(head - roots[0].ParentHead).Length());
                    for (int j = 0; j < i; j++)
                    {
                        var separation = Horizontal(head - _bindHeads[candidates[j]]);
                        double length = separation.Length();
                        if (length > maxSeparation)
                        {
                            maxSeparation = length;
                            widest = separation;
                        }
                    }
                }
                if (maxSeparation > 1e-4 && maxSeparation >= .25 * maxDistance)
                {
                    var corrected = BindUp.Cross(widest.Normalized()).Normalized();
                    var centroidFront = Horizontal(meanTarget - roots[0].ParentHead);
                    var signDirection = centroidFront.Length() < 1e-6 ? front : centroidFront.Normalized();
                    double alignment = corrected.Dot(signDirection);
                    if (Math.Abs(alignment) >= 1e-6) front = alignment > 0 ? corrected : corrected * -1;
                }
            }
            foreach (var b in chain)
            {
                b.BodyFront = front;
                if (b.BodyFront.LengthSq() < 1e-10) b.BodyFront = new V3(0, 0, 1);
                b.BodyFront = b.WorldRotation.Inverse().Rotate(b.BodyFront);
                // Each link uses its chain root's horizontal bind-pose side direction.
                var chainRoot = b;
                for (int n = _rig.Parent(b.Node); n >= 0 && members.Contains(n); n = _rig.Parent(n)) chainRoot = _binds[n];
                b.PairedLateral = V3.Zero;
                if (roots.Count >= 2)
                    b.PairedLateral = b.WorldRotation.Inverse().Rotate(Horizontal(chainRoot.Head - meanRoot).Normalized());
                b.StraightenRotation = Quat.Identity;
                if (!roots.Contains(b))
                {
                    var parentBind = _binds[_rig.Parent(b.Node)];
                    var child = ChildOf(b);
                    var ownLever = child is not null ? child.Head - b.Head : b.CentroidWorld - b.Head;
                    var parentLever = b.Head - parentBind.Head;
                    if (ownLever.LengthSq() > 1e-12 && parentLever.LengthSq() > 1e-12)
                    {
                        var inverseBind = b.WorldRotation.Inverse();
                        b.StraightenRotation = MotionMath.FromUnitVectors(inverseBind.Rotate(ownLever.Normalized()),
                                                                         inverseBind.Rotate(parentLever.Normalized()));
                    }
                }
                b.Lateral = V3.Zero;
                if (!roots.Contains(b)) continue;
                {
                    var child = ChildOf(b);
                    var lever = (child is not null ? child.Head - b.Head : b.CentroidWorld - b.Head).Normalized();
                    var toward = front - lever * front.Dot(lever);
                    if (toward.LengthSq() < 1e-10) toward = BindUp - lever * BindUp.Dot(lever);
                    b.Lateral = b.WorldRotation.Inverse().Rotate(lever.Cross(toward).Normalized());
                    if (roots.Count == 1)
                    {
                        var inverseBind = b.WorldRotation.Inverse();
                        var axis = front.Cross(BindUp).Normalized();
                        // Match the existing positive raise direction in the sagittal plane.
                        if (axis.Dot(lever.Cross(toward)) < 0) axis *= -1;
                        var sagittal = lever - axis * lever.Dot(axis);
                        b.SingleLateral = inverseBind.Rotate(axis);
                        b.CenteringRotation = Quat.Identity;
                        if (sagittal.LengthSq() > 1e-12)
                            b.CenteringRotation = MotionMath.FromUnitVectors(inverseBind.Rotate(lever), inverseBind.Rotate(sagittal.Normalized()));
                    }
                }
            }
            // Links within rigid_tail of a chain end are carried, not simulated.
            int tail = (int)Math.Max(0, Math.Floor(ps.RigidTail ?? 0));
            int FromLeaf(Bind b) => ChildOf(b) is { } c ? 1 + FromLeaf(c) : 0;
            foreach (var bind in chain)
            {
                if (selected.Contains(bind.Node)) continue;
                if (tail > 0 && !roots.Contains(bind) && FromLeaf(bind) < tail)
                {
                    selected.Add(bind.Node);
                    nextRigids.Add(bind);
                    continue;
                }
                selected.Add(bind.Node);
                double to = RestAngle(ps);
                double straightenDeg = ps.StraightenDeg ?? 0;
                bool zeroFreq = Math.Pow(2 * Math.PI * (ps.FreqHz ?? double.NaN), 2) < 1e-12;
                var particle = previous.TryGetValue(bind.Node, out var old) ? old : new Particle
                {
                    Bind = bind, Roots = roots, MotionShare = 1, Params = ps, ParamsFrom = ps, ParamsTo = ps, ParamsBlend = 1.5,
                    P = null, V = V3.Zero, Target = null, AnchorRotation = null, Rest = to, RestFrom = to, RestTo = to, Blend = 1.5,
                    Straighten = StraighteningFraction(to, straightenDeg), StraightenFrom = StraighteningFraction(to, straightenDeg),
                    StraightenRestFrom = Math.Abs(to), StraightenBlend = 1.5, StraightenThreshold = straightenDeg,
                    StaticFrequency = ps.FreqHz ?? double.NaN, StaticFrequencyFrom = ps.FreqHz ?? double.NaN,
                    StaticFrequencyTo = ps.FreqHz ?? double.NaN,
                    StaticWeight = zeroFreq ? 0 : 1, StaticWeightFrom = zeroFreq ? 0 : 1, StaticWeightTo = zeroFreq ? 0 : 1,
                };
                if (particle.RestTo != to)
                {
                    particle.RestFrom = particle.Rest;
                    particle.RestTo = to;
                    particle.Blend = 0;
                }
                if (particle.StraightenThreshold != straightenDeg)
                {
                    particle.StraightenFrom = particle.Straighten;
                    particle.StraightenRestFrom = Math.Abs(particle.Rest);
                    particle.StraightenThreshold = straightenDeg;
                    particle.StraightenBlend = 0;
                }
                particle.Roots = roots;
                if (MotionGroup.BlendedFields.Any(f => particle.ParamsTo.Get(f) != ps.Get(f)))
                {
                    particle.ParamsFrom = particle.Params;
                    // Preserve an interrupted static transition's frequency and weight.
                    particle.StaticFrequencyTo = zeroFreq ? particle.StaticFrequency : ps.FreqHz ?? double.NaN;
                    particle.StaticFrequencyFrom = particle.StaticWeight == 0 ? particle.StaticFrequencyTo : particle.StaticFrequency;
                    particle.StaticWeightFrom = particle.StaticWeight;
                    particle.StaticWeightTo = zeroFreq ? 0 : 1;
                    particle.ParamsBlend = 0;
                }
                particle.ParamsTo = ps;
                particle.Params = BlendParams(particle.ParamsFrom, particle.ParamsTo, particle.ParamsBlend);
                nextParticles.Add(particle);
            }
        }
        foreach (var rootParticle in nextParticles.Where(p => p.Roots.Contains(p.Bind)).ToList())
        {
            var chain = nextParticles.Where(p =>
            {
                if (!ReferenceEquals(p.Roots, rootParticle.Roots)) return false;
                for (int n = p.Bind.Node; n >= 0; n = _rig.Parent(n)) if (n == rootParticle.Bind.Node) return true;
                return false;
            }).OrderBy(p => p.Bind.Depth).ToList();
            // The same span convention as sag: joint-to-joint, twice the centroid lever for the final link.
            var spans = chain.Select((st, j) => j + 1 < chain.Count
                ? st.Bind.Head.DistanceTo(chain[j + 1].Bind.Head)
                : 2 * st.Bind.CentroidWorld.DistanceTo(st.Bind.Head)).ToList();
            double remaining = 0, sum = 0;
            for (int j = chain.Count - 1; j >= 0; j--)
            {
                remaining += spans[j];
                chain[j].MotionShare = remaining * remaining * spans[j];
                sum += chain[j].MotionShare;
            }
            foreach (var st in chain)
            {
                st.Chain = chain;
                st.MotionShare = chain.Count == 1 ? 1 : sum > 0 ? st.MotionShare / sum : 1.0 / chain.Count;
                if (chain.Count >= 2) st.Sag ??= new Sag();
            }
        }
        foreach (var old in _particles.Select(p => p.Bind).Concat(_rigids))
            if (!selected.Contains(old.Node))
            {
                _owned.Remove(old.Node);
                _ownedLocal.Remove(old.Node);
            }
        _rigids = nextRigids.OrderBy(b => b.Depth).ToList();
        var drivenNodes = nextParticles.Select(st => st.Bind.Node).ToHashSet();
        int DrivenDepth(Particle st)
        {
            int depth = 0;
            for (int n = _rig.Parent(st.Bind.Node); n >= 0; n = _rig.Parent(n)) if (drivenNodes.Contains(n)) depth++;
            return depth;
        }
        _particles = nextParticles.OrderBy(DrivenDepth).ToList();
        foreach (var b in _particles.Select(p => p.Bind).Concat(_rigids))
            if (_owned.Add(b.Node)) _ownedLocal[b.Node] = b.Local;   // matrixAutoUpdate = false: the bind local until driven
    }

    /// <summary><c>reset()</c>: every particle starts over at its target, at rest.</summary>
    public void Reset()
    {
        foreach (var st in _particles)
        {
            st.P = null;
            st.Target = null;
            st.AnchorRotation = null;
            st.V = V3.Zero;
        }
    }

    /// <summary><c>dispose()</c>: the solver lets go of every bone (the host's pose rules them again).</summary>
    public void Dispose()
    {
        _particles = new();
        _rigids = new();
        _owned.Clear();
        _ownedLocal.Clear();
        _disposed = true;
    }

    /// <summary>The quaternion of a node as three's <c>n.quaternion</c>: an owned bone keeps its bind rotation.</summary>
    private Quat NodeRotation(int n) => _owned.Contains(n) ? _binds[n].LocalRotation : RigMath.RotationOf(_rig.Local[n]);

    /// <summary><c>pureParent(node)</c>: local rotations multiplied from the leaf to the base, a driven bone's own frame substituted.</summary>
    private Quat PureParent(int node)
    {
        var q = Quat.Identity;
        for (int n = node; n >= 0; n = _rig.Parent(n))
        {
            if (_driven.TryGetValue(n, out var parent)) return parent.Bind.Rotation * q;
            q = NodeRotation(n) * q;
        }
        return RigMath.RotationOf(_rig.Base) * q;
    }

    /// <summary>
    /// <c>update(realDelta, {frozen, far})</c>: real seconds (clamped ≥ 0); <paramref name="far"/> toggling resets and
    /// zeroes the gain; a gap over 0.25 s resets; <paramref name="frozen"/> stops the dynamics (the particle rides along).
    /// The host has written the animated local matrices; the owned ones are the solver's.
    /// </summary>
    public void Update(double realDelta, bool frozen = false, bool far = false)
    {
        if (_disposed || _particles.Count == 0) return;
        double dt = double.IsFinite(realDelta) ? Math.Max(0, realDelta) : 0;
        if (far != _far)
        {
            _far = far;
            Reset();
        }
        foreach (var (n, local) in _ownedLocal) _rig.Local[n] = local;
        _rig.UpdateWorld();
        _driven.Clear();
        foreach (var st in _particles)
        {
            st.ParamsBlend = Math.Min(1.5, st.ParamsBlend + dt);
            st.Params = BlendParams(st.ParamsFrom, st.ParamsTo, st.ParamsBlend);
            // Rest blending is real time, including far LOD. Freeze stops dynamics.
            st.Blend = Math.Min(1.5, st.Blend + dt);
            double fraction = st.Blend / 1.5;
            double limit = st.Params.RestMaxDeg * Math.PI / 180;
            st.Rest = Clamp(st.RestFrom + (st.RestTo - st.RestFrom) * Smooth(fraction), -limit, limit);
            st.StraightenBlend = Math.Min(1.5, st.StraightenBlend + dt);
            double straightWeight = Smooth(st.StraightenBlend / 1.5);
            double straightTarget = StraighteningFraction(st.Rest, st.StraightenThreshold);
            double carried = st.StraightenFrom * StraighteningFraction(st.Rest, st.StraightenRestFrom * 180 / Math.PI);
            st.Straighten = carried + (straightTarget - carried) * straightWeight;
        }
        foreach (var st in _particles) Drive(st, dt, frozen);
        // A rigid tail link takes its parent's frame without the parent's own extension scale, at the parent's fully
        // deformed position — the same rule as a driven child, minus every motion of its own.
        foreach (var b in _rigids)
        {
            int parent = _rig.Parent(b.Node);
            var parentWorld = _rig.WorldOf(parent);
            var anchorFull = parentWorld.Times(b.Local);
            var anchor = (_driven.TryGetValue(parent, out var owner) ? owner.Bind.PureWorld : parentWorld).Times(b.Local)
                .WithPosition(anchorFull.Position());
            _rig.World[b.Node] = anchor;
            b.PureWorld = anchor;
            _rig.Local[b.Node] = _ownedLocal[b.Node] = parentWorld.Inverted().Times(anchor);
        }
        // Publish all non-driven descendants once after the chain is complete.
        _rig.UpdateWorld();
    }

    private void Drive(Particle st, double dt, bool frozen)
    {
        var b = st.Bind;
        var prm = st.Params;
        double motionLimit = prm.MaxDeg * st.MotionShare * Math.PI / 180;
        var anchor = b.Local;
        var anchorFull = b.Local;
        // A driven ancestor contributes its frame WITHOUT its own extension scale, while the position follows the
        // fully deformed ancestor so a lengthened parent still carries its child outward.
        bool drivenAncestor = false;
        for (int n = _rig.Parent(b.Node); n >= 0; n = _rig.Parent(n))
        {
            if (_driven.TryGetValue(n, out var ancestor))
            {
                anchor = ancestor.Bind.PureWorld.Times(anchor);
                anchorFull = _rig.World[n].Times(anchorFull);
                drivenAncestor = true;
                break;
            }
            anchor = _rig.Local[n].Times(anchor);
            anchorFull = _rig.Local[n].Times(anchorFull);
        }
        if (!drivenAncestor)
        {
            anchor = _rig.Base.Times(anchor);
            anchorFull = _rig.Base.Times(anchorFull);
        }
        if (drivenAncestor) anchor = anchor.WithPosition(anchorFull.Position());
        var anchorQ = PureParent(_rig.Parent(b.Node)) * b.LocalRotation;
        bool blended = !drivenAncestor && b.AnchorBlend is not null;
        if (blended)
        {
            // The rest frame at the blend of the anchor bones' motions since bind: the head moved as linear skinning
            // moved the tissue, the rotation is the normalised share-weighted sum of their delta rotations.
            double qx = 0, qy = 0, qz = 0, qw = 0;
            var blendHead = V3.Zero;
            var firstQ = Quat.Identity;
            int i = 0;
            foreach (var (x, share) in b.AnchorBlend!)
            {
                var delta = _rig.World[x.Node].Times(x.BindWorldInverse);
                blendHead += delta.Apply(b.Head) * share;
                var deltaQ = RigMath.Decompose(delta).Rotation;
                if (i == 0) firstQ = deltaQ;
                else if (firstQ.Dot(deltaQ) < 0) deltaQ = new Quat(-deltaQ.X, -deltaQ.Y, -deltaQ.Z, -deltaQ.W);
                qx += share * deltaQ.X; qy += share * deltaQ.Y; qz += share * deltaQ.Z; qw += share * deltaQ.W;
                i++;
            }
            var blendQ = new Quat(qx, qy, qz, qw).ThreeNormalized();
            anchorQ = blendQ * b.WorldRotation;
            var blendScale = RigMath.Decompose(anchor).Scale;
            anchor = RigMath.Compose(blendHead, anchorQ, blendScale);
            anchorFull = anchor;
        }
        Quat restQ;
        if (st.Roots.Count == 1 && st.Roots[0] == b && b.SingleLateral.LengthSq() > 1e-12)
        {
            var centeringQ = Quat.Identity.Slerp(b.CenteringRotation, st.Straighten);
            restQ = Quat.FromAxisAngle(b.SingleLateral, st.Rest) * centeringQ;
        }
        else if (st.Roots.Contains(b) && b.Lateral.LengthSq() > 1e-12) restQ = Quat.FromAxisAngle(b.Lateral, st.Rest);
        else restQ = Quat.Identity.Slerp(b.StraightenRotation, st.Straighten);

        V3 head;
        if (st.Chain is { Count: >= 2 } sagChain && sagChain[0] == st) ChainSag(sagChain, st, anchor, anchorQ, restQ);

        var restVector = restQ.Rotate(b.Centroid);
        var target = anchor.Apply(restVector);
        head = anchor.Position();
        // Static gravity acts against the baked bind gravity, before dynamics.
        var u = (target - head).Normalized();
        var lateral = V3.Zero;
        if (st.Roots.Count >= 2)
        {
            lateral = anchorQ.Rotate(b.PairedLateral);
            lateral = (lateral - u * lateral.Dot(u)).Normalized();
        }
        var deltaG = (Gravity * (prm.GravityScale ?? 1) - anchorQ.Rotate(restQ.Rotate(b.GravityRest))) * (prm.Gravity ?? double.NaN);
        double bindProjection = b.GravityProjection;
        double projection = Gravity.Dot(u) / 9.81;
        double inward = Clamp(-projection - Math.Max(0, -bindProjection), 0, 1);
        double outward = Clamp(projection - Math.Max(0, bindProjection), 0, 1);
        double axial = deltaG.Dot(u);
        if (axial < 0) deltaG -= u * axial;
        // When crossing zero, blend the bounded static result rather than dividing by a frequency approaching zero.
        double staticBlend = Smooth(Clamp(st.ParamsBlend / 1.5, 0, 1));
        st.StaticFrequency = st.StaticFrequencyFrom + (st.StaticFrequencyTo - st.StaticFrequencyFrom) * staticBlend;
        st.StaticWeight = st.StaticWeightFrom + (st.StaticWeightTo - st.StaticWeightFrom) * staticBlend;
        double omegaSquared = Math.Pow(2 * Math.PI * st.StaticFrequency, 2);
        var equilibrium = deltaG * (omegaSquared >= 1e-12 ? 1 / omegaSquared : 0);
        var originalLever = target - head;
        double restLength = originalLever.Length();
        var staticVector = originalLever + equilibrium;
        // Static angle and length have their own limits, independent of swing.
        double sagLimit = (prm.SagMaxDeg ?? prm.MaxDeg) * Math.PI / 180;
        Quat dynamicQ;
        if (st.Chain is { Count: >= 2 }) dynamicQ = st.Sag!.Q;
        else
        {
            dynamicQ = MotionMath.FromUnitVectors(u, staticVector.Normalized());
            double sagAngle = dynamicQ.AngleTo(Quat.Identity);
            if (sagAngle > sagLimit) dynamicQ = dynamicQ.Slerp(Quat.Identity, 1 - sagLimit / sagAngle);
        }
        dynamicQ = dynamicQ.Slerp(Quat.Identity, 1 - st.StaticWeight);
        double staticLength = Math.Max(1e-12, restLength * (1 - (prm.Flatten ?? 0) * (1 - (prm.FlattenFloor ?? prm.Squash.Min)) * inward
                                                           + (prm.Stretch ?? 0) * (prm.Squash.Max - 1) * outward));
        // Scale only the bounded force displacement along bind body up.
        staticVector = dynamicQ.Rotate(u) * restLength - originalLever;
        var bodyVertical = anchorQ.Rotate(b.GravityRest * (-1 / 9.81)).Normalized();
        staticVector += bodyVertical * (((prm.HeadSag ?? 1) - 1) * staticVector.Dot(bodyVertical));
        staticVector += originalLever;
        // Direct paired outward target in radians, independent of force/frequency.
        double spillAngle = (prm.Spill ?? 0) * (prm.SpillMaxDeg ?? prm.SagMaxDeg ?? prm.MaxDeg) * Math.PI / 180 * inward;
        if (lateral.LengthSq() > 1e-12) staticVector = staticVector.ApplyAxisAngle(u.Cross(lateral).Normalized(), spillAngle);
        staticVector *= restLength > 1e-12 ? staticLength / restLength : 1;
        target = head + staticVector;
        bool extremeAnchor = dt > 0 && st.AnchorRotation is { } ar && ar.AngleTo(anchorQ) / dt > 2 * Math.PI;
        if (_far || st.P is null || st.Target is null || (!frozen && dt > 0.25))
        {
            st.P = target;
            st.V = V3.Zero;
        }
        else if (frozen) st.P = st.P.Value + (target - st.Target.Value);
        else if (dt > 0)
        {
            var from = st.Target.Value;
            var vTarget = (target - from) * (1 / dt);
            int steps = (int)Math.Ceiling(dt / (1.0 / 240));
            double h = dt / steps;
            var p = st.P.Value;
            var v = st.V;
            for (int i = 0; i < steps; i++)
            {
                var t = from.Lerp(target, (double)i / steps);
                var previousDeviation = p - t;
                var (rp, rv) = StepParticle(p, v, t, vTarget, prm, h);
                if (extremeAnchor)
                {
                    // Cap each deviation increment and its total displacement during extreme anchor turns; carry the
                    // bounded target velocity on a hit so stored momentum cannot inject another burst.
                    double budget = staticVector.Length() * Math.Sin(Math.Min(Math.PI / 2, motionLimit));
                    var nextDeviation = rp - t - vTarget * h;
                    var inc = (nextDeviation - previousDeviation).ClampLength(0, budget * Math.Min(1, h * 120));
                    nextDeviation = (previousDeviation + inc).ClampLength(0, budget);
                    var capped = t + vTarget * h + nextDeviation;
                    if (capped.DistanceToSquared(rp) > 1e-20) rv = vTarget;
                    rp = capped;
                }
                if (!double.IsFinite(rp.LengthSq()) || !double.IsFinite(rv.LengthSq()))
                {
                    rp = t + vTarget * h;
                    rv = V3.Zero;
                }
                p = rp;
                v = rv;
            }
            st.P = p;
            st.V = v;
        }
        st.AnchorRotation = anchorQ;
        st.Target = target;
        var baseV = target - head;
        // Filter only p − T' in the current rest lever frame. Vertical levers use the projected bind body front.
        u = baseV.Normalized();
        bodyVertical = anchorQ.Rotate(b.GravityRest * (-1 / 9.81));
        bodyVertical -= u * bodyVertical.Dot(u);
        if (bodyVertical.LengthSq() < 1e-10)
        {
            bodyVertical = anchorQ.Rotate(b.BodyFront);
            bodyVertical -= u * bodyVertical.Dot(u);
        }
        bodyVertical = bodyVertical.Normalized();
        var dynamicDelta = st.P!.Value - target;
        var gains = prm.AxisGain ?? (1, 1, 1);
        double longitudinal = dynamicDelta.Dot(u), vertical = dynamicDelta.Dot(bodyVertical);
        dynamicDelta = dynamicDelta * gains.X + bodyVertical * ((gains.Y - gains.X) * vertical) + u * ((gains.Z - gains.X) * longitudinal);
        var rendered = baseV + dynamicDelta;
        // Compression cannot flip the lever and manufacture axial swing.
        rendered += u * Math.Max(0, 1e-12 - baseV.Length() - gains.Z * longitudinal);
        // Saturate the swing angle around the static target, not around bind T.
        dynamicQ = MotionMath.FromUnitVectors(baseV.Normalized(), rendered.Normalized());
        double angle = dynamicQ.AngleTo(Quat.Identity);
        double limited = SoftMotionAngle(angle, motionLimit);
        if (angle > 0) dynamicQ = dynamicQ.Slerp(Quat.Identity, 1 - limited / angle);
        // Only longitudinal dynamics change length; transverse displacement supplies direction.
        double renderedLength = Math.Max(1e-12, baseV.Length() + gains.Z * longitudinal);
        rendered = dynamicQ.Rotate(baseV) * (renderedLength / baseV.Length());
        double gain = _far ? 0 : prm.Gain ?? double.NaN;
        rendered = (rendered - baseV) * gain + baseV;
        rendered = rendered.Normalized() * Math.Max(1e-12, baseV.Length() + gain * gains.Z * longitudinal);
        // Split bounded transverse static and dynamic offsets; axial length is unchanged.
        double translate = prm.Translate ?? 0;
        var leverDir = originalLever.Normalized();
        var headShift = baseV - originalLever;
        headShift -= leverDir * headShift.Dot(leverDir);
        headShift = headShift.ClampLength(0, restLength * Math.Max(0, Math.Sin(sagLimit)));
        var shiftPart = rendered - baseV;
        shiftPart -= leverDir * shiftPart.Dot(leverDir);
        shiftPart = shiftPart.ClampLength(0, baseV.Length() * Math.Max(0, Math.Sin(motionLimit)));
        headShift = (headShift + shiftPart) * translate;
        double totalLength = rendered.Length();
        rendered = (rendered - headShift).Normalized() * totalLength;
        var inverseAnchor = anchor.Inverted();
        var localRendered = inverseAnchor.Apply(rendered + head);
        dynamicQ = MotionMath.FromUnitVectors(restVector.Normalized(), localRendered.Normalized());
        // head_sag acts after force/length limits. Preserve that static target even when it is shorter than squash_min.
        double staticRatio = inverseAnchor.Apply(target).Length() / restVector.Length();
        double s = Clamp(localRendered.Length() / restVector.Length(), Math.Min(prm.Squash.Min, staticRatio), prm.Squash.Max);
        double spread = prm.Spread ?? 0.5;
        double perpendicular = s < 1 ? Math.Min(SpreadCap, 1 + spread * (1 / Math.Sqrt(s) - 1)) : 1 / Math.Sqrt(s);
        var ax = b.ScaleAxis;
        double pairedWidth = Math.Min(SpreadCap, 1 + spread * (1 / s - 1));
        // Paired flattening presses along the BODY FRONT and widens along the body lateral axis; both in the frame the
        // scale acts in (bind bone frame rotated by dynamic·rest); (front, L, front×L) is orthonormal: no shear.
        var frameQ = (dynamicQ * restQ).Inverse();
        var frontLocal = frameQ.Rotate(b.BodyFront).Normalized();
        var localLateral = frameQ.Rotate(lateral.TransformDirection(inverseAnchor));
        localLateral -= frontLocal * localLateral.Dot(frontLocal);
        localLateral = localLateral.LengthSq() > 1e-12 ? localLateral.Normalized() : V3.Zero;
        bool pairedFlatten = s < 1 && st.Roots.Count >= 2 && localLateral.LengthSq() > 1e-12;
        var e = new double[3, 3];
        for (int row = 0; row < 3; row++)
            for (int col = 0; col < 3; col++)
                e[row, col] = pairedFlatten
                    ? (row == col ? 1 : 0) + (s - 1) * frontLocal.Component(row) * frontLocal.Component(col)
                      + (pairedWidth - 1) * localLateral.Component(row) * localLateral.Component(col)
                    : (row == col ? perpendicular : 0) + (s - perpendicular) * ax.Component(row) * ax.Component(col);
        // State extent after static/dynamic scaling, in the same immutable lever frame.
        double stateLength = prm.Length ?? 1, stateGirth = prm.Girth ?? 1;
        for (int row = 0; row < 3; row++)
            for (int col = 0; col < 3; col++)
                e[row, col] = stateGirth * e[row, col] + (stateLength - stateGirth) * s * ax.Component(row) * ax.Component(col);
        var scale = MotionMath.Linear(e);
        var translation = MotionMath.TranslationOf(inverseAnchor.Apply(head + headShift));
        var dq = dynamicQ * restQ;
        var rotation = MotionMath.RotationOf(dq);
        var parentWorld = _rig.WorldOf(_rig.Parent(b.Node));
        var local = (blended ? parentWorld.Inverted().Times(anchor) : b.Local).Times(translation).Times(rotation).Times(scale);
        b.Rotation = anchorQ * dq;
        _driven[b.Node] = st;
        b.PureWorld = anchor.Times(translation).Times(rotation);
        var world = b.PureWorld.Times(scale);
        _rig.World[b.Node] = world;
        // Keep the local matrix consistent with that world matrix: matrix = local · anchorFull⁻¹ · world.
        if (drivenAncestor) local = b.Local.Times(anchorFull.Inverted()).Times(world);
        _rig.Local[b.Node] = _ownedLocal[b.Node] = local;
    }

    /// <summary>The multi-link sag: torques on the unsagged chain, the bounded total angle split by torque·span.</summary>
    private void ChainSag(List<Particle> chain, Particle st, Affine anchor, Quat anchorQ, Quat restQ)
    {
        double mass = 0;
        var centre = V3.Zero;
        var force = V3.Zero;
        foreach (var link in chain)
        {
            var data = link.Sag!;
            var bind = link.Bind;
            var parent = chain.FirstOrDefault(p => p.Bind.Node == _rig.Parent(bind.Node));
            if (parent is not null)
            {
                data.Frame = parent.Sag!.Frame.Times(bind.Local);
                data.Rotation = parent.Sag!.Rotation * bind.LocalRotation;
            }
            else
            {
                data.Frame = anchor;
                data.Rotation = anchorQ;
            }
            data.Q = link == st ? restQ : Quat.Identity.Slerp(bind.StraightenRotation, link.Straighten);
            data.Head = data.Frame.Position();
            data.Centre = data.Frame.Apply(data.Q.Rotate(bind.Centroid));
            var u = (data.Centre - data.Head).Normalized();
            data.Force = (Gravity * (link.Params.GravityScale ?? 1) - data.Rotation.Rotate(data.Q.Rotate(bind.GravityRest)))
                         * (link.Params.Gravity ?? double.NaN);
            double ax = data.Force.Dot(u);
            if (ax < 0) data.Force -= u * ax;
            centre += data.Centre * bind.Mass;
            force += data.Force * bind.Mass;
            mass += bind.Mass;
            data.Frame = data.Frame.Times(MotionMath.RotationOf(data.Q));
            data.Rotation = data.Rotation * data.Q;
        }
        var originalLever = centre * (1 / mass) - anchor.Position();
        double staticBlend = Smooth(Clamp(st.ParamsBlend / 1.5, 0, 1));
        double frequency = st.StaticFrequencyFrom + (st.StaticFrequencyTo - st.StaticFrequencyFrom) * staticBlend;
        double omegaSquared = Math.Pow(2 * Math.PI * frequency, 2);
        var equilibrium = force * (1 / mass) * (omegaSquared >= 1e-12 ? 1 / omegaSquared : 0);
        double total = Math.Min(originalLever.AngleTo(originalLever + equilibrium),
                                (st.Params.SagMaxDeg ?? st.Params.MaxDeg) * Math.PI / 180);
        double sum = 0;
        // Torques on the unsagged configuration (small-angle approximation): total droop independent of link count,
        // the largest bend at the root.
        for (int j = 0; j < chain.Count; j++)
        {
            var data = chain[j].Sag!;
            var torque = V3.Zero;
            for (int i = j; i < chain.Count; i++)
            {
                var distal = chain[i];
                torque += (distal.Sag!.Centre - data.Head).Cross(distal.Sag!.Force) * distal.Bind.Mass;
            }
            data.Torque = torque;
            double span = j + 1 < chain.Count ? data.Head.DistanceTo(chain[j + 1].Sag!.Head) : 2 * data.Centre.DistanceTo(data.Head);
            data.Weight = torque.Length() * span;
            sum += data.Weight;
        }
        foreach (var link in chain)
        {
            var data = link.Sag!;
            data.Q = sum > 1e-12 ? Quat.FromAxisAngle(data.Torque.Normalized(), total * data.Weight / sum) : Quat.Identity;
        }
    }
}
