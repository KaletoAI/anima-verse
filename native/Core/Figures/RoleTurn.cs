using System;
using System.Text.Json;

namespace AnimaNative.Figures;

/// <summary>
/// One role's renderer-only turn of a pair/group clip, degrees: the listing's <c>orientation.role_turn_deg[role]</c>
/// = [tilt, roll, yaw] (the server wraps each to (-180, 180]). Zero = no turn (an absent or malformed role).
/// </summary>
public readonly record struct RoleTurnDeg(double Tilt, double Roll, double Yaw)
{
    public static readonly RoleTurnDeg None = new(0, 0, 0);
    public bool IsZero => Tilt == 0 && Roll == 0 && Yaw == 0;

    /// <summary>
    /// The turn of <paramref name="role"/> out of the clip row's <c>orientation.role_turn_deg</c> map
    /// (<c>{"&lt;role a..e&gt;": [tilt, roll, yaw]}</c>, the same map on every role file of the clip). Anything but an object
    /// holding, under that role, an array of exactly three finite JSON numbers → <see cref="None"/>; an empty role (a solo
    /// clip) too.
    /// </summary>
    public static RoleTurnDeg Parse(JsonElement map, string? role)
    {
        if (string.IsNullOrEmpty(role) || map.ValueKind != JsonValueKind.Object
            || !map.TryGetProperty(role, out var turn) || turn.ValueKind != JsonValueKind.Array || turn.GetArrayLength() != 3)
            return None;
        var v = new double[3];
        for (int i = 0; i < 3; i++)
            if (turn[i].ValueKind != JsonValueKind.Number || !turn[i].TryGetDouble(out v[i]) || !double.IsFinite(v[i])) return None;
        return new RoleTurnDeg(v[0], v[1], v[2]);
    }
}

/// <summary>A rigid fix about a pivot p (pairFit.ts <c>PairFix</c>): X ↦ R(X − p) + p + Δ, R = exp([θ]×) for the rotation vector θ.</summary>
public readonly record struct PairFix(V3 Shift, V3 Turn)
{
    public static readonly PairFix Identity = new(V3.Zero, V3.Zero);
    public bool IsIdentity => Shift == V3.Zero && Turn == V3.Zero;
}

/// <summary>
/// ROLE TURN — the math of packages/scene-render/src/pairFit.ts a role's stored turn runs through (owner decision
/// 2026-11-23, formerly partner B's A129/A165 turn): <c>roleTurnFix</c> (the yaw about the frame's up FIRST,
/// <c>roleYawFix</c>, then ONE rotation by the rotation vector tilt·side + roll·forward, composed with <c>composeFix</c>),
/// <c>turnAxes</c>, <c>fixPivot</c>, <c>fixPoint</c>, <c>fixRoot</c>, <c>turnMatrix</c>, <c>matrixTurn</c> — double
/// precision, the same operations in the same order. A frame is a row-major 3×3 (the figure root's rotation; at pair
/// placement <see cref="YawFrame"/>, the browser 3D scene's <c>eulerYXZ(0, yaw, 0)</c>). Vectors shared/test-vectors/role_turn.json
/// (hand derivations: scripts/smoke_role_turn_vectors.mjs).
/// </summary>
public static class RoleTurn
{
    private static readonly double[] Eye = { 1, 0, 0, 0, 1, 0, 0, 0, 1 };

    private static double Len(V3 p) => Math.Sqrt(p.X * p.X + p.Y * p.Y + p.Z * p.Z);
    private static V3 Mul(double[] m, V3 v) => new(m[0] * v.X + m[1] * v.Y + m[2] * v.Z,
        m[3] * v.X + m[4] * v.Y + m[5] * v.Z, m[6] * v.X + m[7] * v.Y + m[8] * v.Z);

    /// <summary>scene-render <c>eulerYXZ(0, yaw, 0)</c>: the row-major frame of a root turned by <paramref name="yaw"/> (radians) about +Y.</summary>
    public static double[] YawFrame(double yaw)
    {
        double c = Math.Cos(yaw), s = Math.Sin(yaw);
        return new[] { c, 0, s, 0, 1, 0, -s, 0, c };
    }

    /// <summary><c>turnMatrix</c>: the row-major 3×3 of the rotation vector <paramref name="w"/> (Rodrigues); identity below 1e-12.</summary>
    public static double[] TurnMatrix(V3 w)
    {
        double a = Len(w);
        if (a < 1e-12) return (double[])Eye.Clone();
        double x = w.X * (1 / a), y = w.Y * (1 / a), z = w.Z * (1 / a);
        double c = Math.Cos(a), s = Math.Sin(a), k = 1 - c;
        return new[] { c + x * x * k, x * y * k - z * s, x * z * k + y * s,
            y * x * k + z * s, c + y * y * k, y * z * k - x * s,
            z * x * k - y * s, z * y * k + x * s, c + z * z * k };
    }

    /// <summary>
    /// <c>matrixTurn</c>: the rotation vector of a row-major rotation matrix (zero below an angle of 1e-9). Within 1e-3 rad
    /// of a half turn the antisymmetric part vanishes, so the axis comes from the symmetric part S = (R + Rᵀ)/4 + I/2
    /// (= n nᵀ at π): its row of the largest diagonal (the first one on a tie), normalised, its sign from what is left of
    /// the antisymmetric part — a yaw of exactly 180° stays a half turn instead of collapsing to none.
    /// </summary>
    public static V3 MatrixTurn(double[] m)
    {
        double c = Math.Max(-1, Math.Min(1, (m[0] + m[4] + m[8] - 1) / 2));
        double a = Math.Acos(c);
        if (a < 1e-9) return V3.Zero;
        var v = new V3(m[7] - m[5], m[2] - m[6], m[3] - m[1]);
        if (a > Math.PI - 1e-3)
        {
            double S(int i, int j) => (m[i * 3 + j] + m[j * 3 + i]) / 4 + (i == j ? 0.5 : 0);
            int b = 0;
            for (int k = 1; k < 3; k++) if (S(k, k) > S(b, b)) b = k;
            var col = new V3(S(b, 0), S(b, 1), S(b, 2));
            double l = Len(col);
            var n = col * (1 / (l != 0 ? l : 1));
            double sgn = n.X * v.X + n.Y * v.Y + n.Z * v.Z < 0 ? -1 : 1;
            return n * (sgn * a);
        }
        double s = Len(v);
        return s < 1e-12 ? V3.Zero : v * (a / s);
    }

    /// <summary><c>fixPoint</c>: X ↦ R(X − p) + p + Δ.</summary>
    public static V3 FixPoint(PairFix fix, V3 pivot, V3 x) => Mul(TurnMatrix(fix.Turn), x - pivot) + pivot + fix.Shift;

    /// <summary><c>composeFix(a, b)</c>: two fixes about the same pivot, first <paramref name="a"/>, then <paramref name="b"/>.</summary>
    public static PairFix ComposeFix(PairFix a, PairFix b)
    {
        double[] ra = TurnMatrix(a.Turn), rb = TurnMatrix(b.Turn), r = new double[9];
        for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) for (int k = 0; k < 3; k++) r[i * 3 + j] += rb[i * 3 + k] * ra[k * 3 + j];
        return new PairFix(Mul(rb, a.Shift) + b.Shift, MatrixTurn(r));
    }

    /// <summary><c>turnAxes</c>: the frame's side axis (+X, column 0) and forward axis (+Z, column 2), world.</summary>
    public static (V3 Side, V3 Forward) TurnAxes(double[] frame)
        => (new V3(frame[0], frame[3], frame[6]), new V3(frame[2], frame[5], frame[8]));

    /// <summary><c>roleYawFix</c>: a yaw about the frame's own up (+Y, column 1); positive turns forward towards +X.</summary>
    public static PairFix RoleYawFix(double yawDeg, double[] frame)
    {
        double c = yawDeg * Math.PI / 180;
        return new PairFix(V3.Zero, new V3(frame[1] * c, frame[4] * c, frame[7] * c));
    }

    /// <summary>
    /// <c>roleTurnFix(tilt, roll, frame, yaw)</c>: the yaw first (<see cref="RoleYawFix"/>), then ONE rotation by the vector
    /// tilt·side + roll·forward; a zero yaw is the plain tilt/roll fix (no composition).
    /// </summary>
    public static PairFix RoleTurnFix(double tiltDeg, double rollDeg, double[] frame, double yawDeg = 0)
    {
        var (side, fwd) = TurnAxes(frame);
        double a = tiltDeg * Math.PI / 180, b = rollDeg * Math.PI / 180;
        var tr = new PairFix(V3.Zero, new V3(side.X * a + fwd.X * b, side.Y * a + fwd.Y * b, side.Z * a + fwd.Z * b));
        return yawDeg != 0 ? ComposeFix(RoleYawFix(yawDeg, frame), tr) : tr;
    }

    /// <summary><see cref="RoleTurnFix"/> of a stored <see cref="RoleTurnDeg"/>.</summary>
    public static PairFix Fix(RoleTurnDeg turn, double[] frame) => RoleTurnFix(turn.Tilt, turn.Roll, frame, turn.Yaw);

    /// <summary><c>fixPivot</c>: the root (before any fix) plus its bind hips turned by the frame — the point the turn is about.</summary>
    public static V3 FixPivot(V3 rootPosition, double[] frame, V3 hipsBind) => rootPosition + Mul(frame, hipsBind);

    /// <summary>
    /// <c>fixRoot</c>: the root at <paramref name="position"/> moved by <paramref name="fix"/> about <paramref name="pivot"/> — the
    /// new position and the rotation to PREMULTIPLY onto the root's own, as a quaternion (x, y, z, w).
    /// </summary>
    public static (V3 Position, Quat Rotation) FixRoot(PairFix fix, V3 pivot, V3 position)
    {
        double a = Len(fix.Turn);
        double h = a / 2, s = a > 1e-12 ? Math.Sin(h) / a : 0.5;
        return (FixPoint(fix, pivot, position), new Quat(fix.Turn.X * s, fix.Turn.Y * s, fix.Turn.Z * s, Math.Cos(h)));
    }
}
