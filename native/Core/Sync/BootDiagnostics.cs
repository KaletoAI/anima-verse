using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;

namespace AnimaNative.Sync;

/// <summary>Task 91: process CPU consumed during this boot, with Linux pressure sampled at boot end.</summary>
public sealed class BootDiagnostics
{
    private readonly long _started = Stopwatch.GetTimestamp();
    private readonly TimeSpan _cpu = CpuTime();
    private static TimeSpan CpuTime() { using var p = Process.GetCurrentProcess(); return p.TotalProcessorTime; }

    public string Read()
    {
        double wall = Stopwatch.GetElapsedTime(_started).TotalMilliseconds;
        double cpu = (CpuTime() - _cpu).TotalMilliseconds;
        string? ReadProc(string path)
        {
            if (!OperatingSystem.IsLinux()) return null;
            try { return File.ReadAllText(path); }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
        }
        return Describe(Environment.ProcessorCount, ReadProc("/proc/loadavg"), ReadProc("/proc/meminfo"), cpu, wall);
    }

    public static string Describe(int cpus, string? loadavg, string? meminfo, double cpuMs, double wallMs)
    {
        string machine = $"boot machine: cpus={cpus}";
        var loadFields = loadavg?.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        string? first = loadFields is { Length: > 0 } ? loadFields[0] : null;
        if (double.TryParse(first, NumberStyles.Float, CultureInfo.InvariantCulture, out double load) && double.IsFinite(load) && load >= 0)
            machine += FormattableString.Invariant($" load1={load:0.00}");
        long? available = null, total = null;
        foreach (string line in (meminfo ?? "").Split('\n'))
        {
            var parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 3 || parts[2] != "kB" || !long.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out long kb) || kb < 0) continue;
            if (parts[0] == "MemAvailable:") available = kb;
            if (parts[0] == "MemTotal:") total = kb;
        }
        if (available is { } a && total is { } t && a <= t && t > 0)
            machine += FormattableString.Invariant($" mem_available={a / 1024.0:0} MiB mem_total={t / 1024.0:0} MiB");
        return machine + FormattableString.Invariant($" process_cpu={cpuMs:0} ms wall={wallMs:0} ms cpu/wall={(wallMs > 0 ? cpuMs / wallMs : 0):0.00}");
    }
}
