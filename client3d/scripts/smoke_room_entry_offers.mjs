/** Task 85: real room adoption and reconciliation with a delayed old-room response. */
import assert from 'node:assert/strict';
import { mainFunctions } from './mainFunction.mjs';
const map = { avatar: 'avatar', characters: [{ name: 'avatar', location_id: 'house', room_id: 'old' }] };
let finishOld, reads = 0, invalidations = 0;
let room = 'old';
const published = [];
const scope = await mainFunctions(['syncPlaceGlyphs', 'refreshRoomOffers', 'adoptReport', 'preserveOfferRoom'], {
  avatarName: 'avatar', lastMap: map, roomOf: new Map(), propOffersRoomKey: null, ownOfferRoomChangeAt: 0,
  offersGeneration: 0, offersAppliedGeneration: 0, propStateEpoch: 0, ownSeatChangeAt: 0,
  placeOffers: [], placeOffersRoom: '', semanticOffers: [], semanticState: {}, propStateUncertain: false,
  api: {
    invalidatePropActionOffers() { invalidations++; },
    getPropActionState: async () => ({}), getPlaces: async () => ({ places: [], room_id: room }),
    getPropActions: async () => {
      reads++;
      if (reads === 1) return new Promise(resolve => { finishOld = () => resolve([{ label: 'Old' }]); });
      return [{ label: 'New' }];
    }, isAuthError: () => false,
  },
  setGameState: state => published.push(state), getGameState: () => ({}),
  propPreparation: { adoptFreshState() {} }, pollIsStale: (at, changed) => at < changed,
  logPropOffers() {}, adoptPropState() {}, rebuildPlaceGlyphs() {}, figures: { state: 'loading' },
  uiActions: { toast: message => { throw new Error(message); } },
}, ['lastMap', 'semanticOffers']);
const old = scope.syncPlaceGlyphs(map);
await new Promise(resolve => setImmediate(resolve));
room = 'new';
scope.adoptReport({ location_id: 'house', room_id: room });
await new Promise(resolve => setImmediate(resolve));
assert.equal(reads, 2, 'position answer triggers new-room offers without waiting for worldmap');
assert.equal(scope.snapshot().semanticOffers[0].label, 'New', 'new offers publish in the answer batch');
finishOld(); await old;
assert.equal(scope.snapshot().semanticOffers[0].label, 'New', 'late old-room answer never overwrites new offers');
assert.equal(invalidations, 2, 'initial room and new room each invalidate once');
scope.adoptReport({ location_id: 'house', room_id: room });
await new Promise(resolve => setImmediate(resolve));
assert.equal(reads, 2, 'unchanged room has no immediate read');
scope.adoptReport({ location_id: 'elsewhere', room_id: room });
await new Promise(resolve => setImmediate(resolve));
assert.equal(reads, 3, 'location-only answer triggers offers');

const beforeStalePoll = invalidations;
const preserved = scope.preserveOfferRoom(map, 0);
assert.equal(preserved.characters[0].location_id, 'elsewhere', 'stale poll keeps acknowledged location');
assert.equal(preserved.characters[0].room_id, 'new', 'stale poll keeps acknowledged room');
await scope.syncPlaceGlyphs(preserved);
assert.equal(invalidations, beforeStalePoll, 'stale map cannot force another room read');
assert.equal(scope.preserveOfferRoom(map, Infinity), map, 'fresh polls may move the avatar again');
console.log('room entry offers: PASS (position, location, slow source, immediate publication)');
