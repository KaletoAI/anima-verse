using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Embody;

/// <summary>Task 47 (E7-T2): the sole port of locks.ts; map membership, never reason truthiness, decides a lock.</summary>
public static class Locks
{
    public static bool IsLocked(IReadOnlyDictionary<string, string>? locks, string id)
        => locks is not null && id.Length > 0 && locks.ContainsKey(id);
    public static string LockReason(IReadOnlyDictionary<string, string>? locks, string id)
        => IsLocked(locks, id) ? locks![id] : "";

    /// <summary>The first locked far-side room supplies the reason; null means open, empty means locked without words.</summary>
    public static string? DoorwayLock(IEnumerable<string>? roomIds, IReadOnlyDictionary<string, string>? locks, string currentRoom = "")
    {
        foreach (var id in roomIds ?? Array.Empty<string>())
            if (id != currentRoom && IsLocked(locks, id)) return LockReason(locks, id);
        return null;
    }

    /// <summary>The occupied room survives even if locked; retain caller objects and payload order.</summary>
    public static List<T> UnlockedRooms<T>(IEnumerable<T> rooms, IReadOnlyDictionary<string, string>? locks,
                                          Func<T, string> idOf, string currentRoom = "")
        => rooms.Where(r => idOf(r) == currentRoom || !IsLocked(locks, idOf(r))).ToList();
}
