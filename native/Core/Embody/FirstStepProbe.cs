using System;

namespace AnimaNative.Embody;

/// <summary>A first-step measurement: <c>LatencyMs == null</c> means the avatar did not move within the timeout.</summary>
public sealed record FirstStepResult(string Source, double? LatencyMs, int Frames);

/// <summary>
/// Measures the time from an order (a click walk, a picked prop offer) to the avatar's first centimetre.
/// <c>Arm</c> remembers the source, clock and start point; every <c>Sample</c> while armed counts one frame and
/// reports once: a hit when the horizontal distance from the start exceeds <see cref="MoveThresholdM"/>, a timeout
/// when more than <see cref="TimeoutS"/> seconds passed without one. Either result disarms the probe; re-arming
/// before a result replaces the pending measurement.
/// </summary>
public sealed class FirstStepProbe
{
    public const double MoveThresholdM = 0.01, TimeoutS = 10.0;
    private string _source = "";
    private double _startS, _x, _z;
    private int _frames;

    public bool Armed { get; private set; }

    public void Arm(string source, double clockS, double x, double z)
    {
        _source = source; _startS = clockS; _x = x; _z = z; _frames = 0; Armed = true;
    }

    public FirstStepResult? Sample(double clockS, double x, double z)
    {
        if (!Armed) return null;
        _frames++;
        double elapsed = clockS - _startS;
        if (Math.Sqrt((x - _x) * (x - _x) + (z - _z) * (z - _z)) > MoveThresholdM)
        {
            Armed = false;
            return new FirstStepResult(_source, elapsed * 1000.0, _frames);
        }
        if (elapsed > TimeoutS)
        {
            Armed = false;
            return new FirstStepResult(_source, null, _frames);
        }
        return null;
    }
}
