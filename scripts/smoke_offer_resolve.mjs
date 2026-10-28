/**
 * Smoke: WHICH standing offer the F key answers — `game/offers.nearestOffer`.
 *
 * Usage: direct node call (pure modules bundled by the shared test adapter):
 *     node scripts/smoke_offer_resolve.mjs
 *
 * WHY THIS CHECK EXISTS. Four rules offer the avatar something at the same
 * moment, with reaches of DIFFERENT size: talking reaches TALK_RANGE 2.5 m, a
 * stair landing STAIR_RANGE 1.5 m, a lift pad ELEVATOR_RANGE 1.5 m, a location
 * entry ENTER_RADIUS 3 m. F used to walk a fixed chain (talk → lift → stairs →
 * entry) and stop at the first offer standing, so anybody in the same room
 * within 2.5 m took the key away from a staircase the avatar was standing
 * right at — the reported bug. The rule is the MEASURED DISTANCE now, and this
 * file pins it with numbers derived by hand from that geometry, never from the
 * function's own output.
 *
 * The candidates of cases (1), (2) and (7) are produced by the REAL rules
 * (`talkTargetNear`, `stairsAt`, `elevatorAt`), not written down: whether an
 * offer stands at all is their business, and case (7) is precisely the
 * statement that an out-of-reach candidate never reaches the resolution.
 *
 * THE LAYOUT, once, in world metres (scale 1 throughout, i.e. one world metre
 * is one figure metre — § B, k = 1):
 *
 *   - the avatar stands at the ORIGIN (0, 0), location 'L', outdoors (no room)
 *   - NPC "Ayla" at (2.4, 0) → 2.4 m away, inside TALK_RANGE 2.5
 *   - NPC "Bea"  at (0.5, 0) → 0.5 m
 *   - NPC "Cara" at (2.6, 0) → 2.6 m, OUTSIDE the talk range
 *   - flight FA: foot landing (1, 0, 0) on level 0, head landing (5, 3, 0) on
 *     level 1 → the foot landing is 1.0 m away, inside STAIR_RANGE 1.5
 *   - flight FB: foot landing (1.4, 0, 0) → 1.4 m away
 *   - flight FC: foot landing (1.6, 0, 0) → 1.6 m, OUTSIDE the stair range
 *   - lift stops at (1.2, 0) on both storeys, rooms 'hall' (level 0) and
 *     'attic' (level 1) → the pad is 1.2 m away, inside ELEVATOR_RANGE 1.5
 *   - lift stops at (1.5, 0) → EXACTLY the range, and the comparison is
 *     strict, so no offer
 *
 * All distances are plain hypotenuses along +x, so every expected number below
 * is the x coordinate itself.
 */
import { embodyDispatch as m, vectorChecks } from '../client3d/scripts/embodyVectorDispatch.mjs';
async function main() {
  const {nearestOffer, OFFER_TIEBREAK, talkTargetNear, TALK_RANGE, stairsAt, STAIR_RANGE, elevatorAt, ELEVATOR_RANGE} = m;
  const failures = []
  const check = (label, actual, expected) => {
    const ok = actual === expected
    console.log(`  ${ok ? '✓' : '✗'} ${label} — ${JSON.stringify(actual)}`)
    if (!ok) {
      failures.push(label)
      console.log(`      expected ${JSON.stringify(expected)}`)
    }
  }
  const vectorCase = vectorChecks(check, ['embody']);
  /** A state as the game bus publishes it; anything unnamed is "no offer". */
  const state = (o = {}) => ({
    talkTarget: null, elevator: null, stairs: null, enterOffer: null, ...o,
  })

  // ── The layout, built through the REAL rules ──────────────────────────
  const ME = { name: 'Me', pos: { x: 0, z: 0 }, locId: 'L', room: null }
  const npc = (name, x) =>
    ({ name, pos: { x, z: 0 }, locId: 'L', room: null, scale: 1 })
  const flight = (footX) => ({
    foot: { level: 0, x: footX, y: 0, z: 0 },
    head: { level: 1, x: footX + 4, y: 3, z: 0 },
    run: { at: { x: footX, z: 0 }, dir: { x: 1, z: 0 }, runM: 4, widthM: 1.2 },
  })
  const ROOMS = [
    { id: 'hall', level: 0, center: { x: 5, z: 0 } },
    { id: 'attic', level: 1, center: { x: 5, z: 0 } },
  ]
  const stops = (x) => [{ level: 0, pos: { x, z: 0 } }, { level: 1, pos: { x, z: 0 } }]
  const HERE = { x: 0, z: 0 }

  console.log('\n[0] the ranges the layout is derived from')
  check('TALK_RANGE is 2.5 figure metres', TALK_RANGE, 2.5)
  check('STAIR_RANGE is 1.5', STAIR_RANGE, 1.5)
  check('ELEVATOR_RANGE is 1.5', ELEVATOR_RANGE, 1.5)
  check('the tie-break order is talk, elevator, stairs, enter',
        OFFER_TIEBREAK.join(','), 'talk,elevator,stairs,enter')

  console.log('\n[1] THE BUG: an NPC at 2.4 m must not take the key away from'
    + ' a landing at 1.0 m')
  const ayla = talkTargetNear(ME, [npc('Ayla', 2.4)])
  const stairNear = stairsAt(HERE, 0, [flight(1)], 1)
  check('the talk rule measures 2.4 m', ayla?.dist, 2.4)
  check('the stair rule measures 1.0 m', stairNear?.dist, 1)
  vectorCase('[30] ' + ('the NEARER offer wins: the stairs'))

  console.log('\n[2] …and the other way round: an NPC at 0.5 m beats a landing'
    + ' at 1.4 m')
  const bea = talkTargetNear(ME, [npc('Bea', 0.5)])
  const stairFar = stairsAt(HERE, 0, [flight(1.4)], 1)
  check('the talk rule measures 0.5 m', bea?.dist, 0.5)
  check('the stair rule measures 1.4 m', stairFar?.dist, 1.4)
  vectorCase('[30] ' + ('the NEARER offer wins: the conversation'))

  console.log('\n[3] a single offer wins whatever its distance')
  vectorCase('[30] ' + ('talk alone'))
  vectorCase('[30] ' + ('lift alone'))
  vectorCase('[30] ' + ('stairs alone'))
  vectorCase('[30] ' + ('entry alone'))
  vectorCase('[30] ' + ('…even at zero distance'))

  console.log('\n[4] no offer at all')
  vectorCase('[30] ' + ('nothing stands'))

  console.log('\n[5] lift and stairs at once — the nearer one')
  const lift = elevatorAt(HERE, 0, stops(1.2), ROOMS, 1)
  check('the lift rule measures 1.2 m', lift?.dist, 1.2)
  vectorCase('[30] ' + ('lift 1.2 m vs stairs 0.4 m → stairs'))
  vectorCase('[30] ' + ('lift 1.2 m vs stairs 1.4 m → lift'))

  console.log('\n[6] an exact tie falls to the documented order')
  vectorCase('[30] ' + ('talk vs lift at 1.0 m → talk'))
  vectorCase('[30] ' + ('lift vs stairs at 1.0 m → lift'))
  vectorCase('[30] ' + ('stairs vs entry at 1.0 m → stairs'))
  vectorCase('[30] ' + ('all four at 1.0 m → talk'))
  vectorCase('[30] ' + ('…and a hair of difference beats the order: stairs at 0.999'))

  console.log('\n[7] out of its own reach is NO offer — not even as the only one')
  const cara = talkTargetNear(ME, [npc('Cara', 2.6)])
  const stairOut = stairsAt(HERE, 0, [flight(1.6)], 1)
  const liftOut = elevatorAt(HERE, 0, stops(1.5), ROOMS, 1)
  check('an NPC at 2.6 m (> 2.5) is no talk offer', cara, null)
  check('a landing at 1.6 m (> 1.5) is no stair offer', stairOut, null)
  check('a pad at exactly 1.5 m is no lift offer (strict)', liftOut, null)
  vectorCase('[30] ' + ('so nothing wins, though each would have been alone'))
  vectorCase('[30] ' + ('…and a landing at 1.6 m does not win over an NPC at 2.4 m either'))

  console.log('\n[8] RED PROBES: a distance that is not a distance never wins')
  vectorCase('[30] ' + ('NaN loses to a real offer'))
  vectorCase('[30] ' + ('NaN alone wins nothing'))
  vectorCase('[30] ' + ('a negative distance wins nothing'))
  vectorCase('[30] ' + ('Infinity wins nothing'))

  console.log(`\n${failures.length
    ? 'FAILED: ' + failures.join(', ') : 'all checks passed'}`)
  process.exit(failures.length ? 1 : 0)
}

void main()
