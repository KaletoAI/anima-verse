#!/usr/bin/env python3
"""Smoke: the image routing reaches every caller (behaviour at the seam).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_callers.py

Spec: development_instructions/plan-image-routing.md § 1 (who uses which
occasion) + review notes. Each part replaces the image service (or the
routing entry point) with a recorder and runs the REAL caller, so the
payload / the occasion the caller hands over is what is checked — the
consumer of the routing. Throwaway storage + world DB, no server.

PART A — messaging frame (occasion "frame", review note: a product shot
without a figure, NOT "photo")
A1 generate_frame("a phone") with no target -> ONE payload with
   occasion "frame" and no "backend" key (routed).
A2 generate_frame("a phone", "Flux2*") -> payload backend "Flux2*" and no
   "occasion" key (an explicit pick: exactly that backend, no fallback).

PART B — location family (occasions "location", "timevariant"), end to end
through the REAL routing on a fake pool: "Gw" (family natural, cost 0)
fails with HTTP 500, "Cloud" (family keywords, cost 5) renders; both have one
reference slot. `run_on_backend_channel` runs the job inline. Gallery file
names are `int(time.time()).png`, so the smoke sleeps 1.1 s before every
render that saves an image — two renders in one second would share a name.
B1 gallery, no backend, rules location ["Gw","Cloud"]: the image is saved;
   its gallery meta has backend "Cloud", routing {"occasion":"location",
   "position":2,"spec":"Cloud"}, fallback_from {"occasion":"location",
   "intended_spec":"Gw","position":1} (Gw failed at runtime and cools down
   -> the intended entry stays Gw, the render is marked).
B2 same render: the prompt Cloud received differs from the one Gw received
   (the second run composed for the keywords family — never the same prompt
   on another backend).
B3 settings_applied + prompt "VERBATIM": the first try (Gw) receives
   exactly "VERBATIM"; after Gw fails, the re-run on Cloud receives a
   composed prompt that is NOT "VERBATIM".
B4 explicit backend "Gw" while Gw cools down -> HTTPException 503, Cloud is
   never asked (an explicit pick is never routed elsewhere).
B5 explicit backend "Cloud" -> rendered on Cloud, meta without "routing".
B6 time variant of a gallery image, no backend, rules timevariant ["Cloud"]
   -> new image, meta routing {"occasion":"timevariant","position":1,
   "spec":"Cloud"}, the reference slot carries the source image.
B7 location background, rules location ["Cloud"] -> exactly one new
   gallery image; its meta has backend "Cloud" and routing
   {"occasion":"location","position":1,"spec":"Cloud"} (checked on the NEW
   file — B1's meta alone would satisfy an "any image" check).
B8 room image of describe_room, rules location ["Cloud"], a room with a
   description -> one image assigned to that room, meta backend "Cloud" and
   routing {"occasion":"location","position":1,"spec":"Cloud"} (the old
   lookup went through the skill manager, found the TakePhoto verb without
   a pool and the room image never rendered).
B9 explicit backend "Gw" that is available but fails at runtime (a fresh Gw,
   not cooled yet) -> HTTPException 500; Gw was asked once, Cloud never (an
   explicit pick is not re-run elsewhere, not even after a failure).
B10 no backend, model_override "m-dialog", rules location ["Gw","Cloud"]:
   the first try (Gw) carries params model "m-dialog"; the re-run on Cloud
   carries no "model" (a dialog's model name belongs to the backend the
   dialog showed). An explicit "Cloud" pick with the same override carries
   it (explicit = the dialog's own backend).
B11 explicit "Cloud" with LoRA "foreign.safetensors" (the library is empty,
   so nothing is associated with Cloud) -> HTTPException 400 whose detail
   says the library "does not associate" it; Cloud is never asked; the
   tracked task finishes with that detail as its error, not a bare
   "refused".
B12 no backend, rules location ["Cloud"], a third backend "Spare" outside
   the chain -> Spare is never probed (check_availability count 0): the
   routing probes only its intended entry. An explicit "Cloud" pick does not
   probe Spare either (only the backends matching the pick are probed).
   The B8 room image is named "<unix seconds>_<6 hex>.png" (a suffix, so
   two room images in one second cannot overwrite each other).

PART C — when describe_room renders a room image (coordinator ruling on the
12b review). The render prompt of a room is its image_prompt_day, else its
description. describe_room renders only when the room has no gallery image
yet OR that render prompt changed; the reply says "Bildgenerierung
gestartet." exactly when it renders. `_trigger_room_image` is replaced by a
recorder. Room "Millroom" holds the B8 image; image_prompt_day empty.
C1 same description again -> render prompt unchanged, image present
   -> no render, no "gestartet" in the reply.
C2 new description -> render prompt changed -> one render.
C3 image_prompt "A mill interior, warm light" -> render prompt becomes that
   (was the description) -> one render.
C4 another new description while the image prompt stays -> the render
   prompt is still the image prompt, image present -> no render.
C5 room "Loft" (added with a description, no image) described with the SAME
   description -> no image yet -> one render.
C6 new room "Cellar" -> created, no image yet -> one render.

PART P — prop source + item image (occasions "prop", "item"; plan Task 13,
whose smoke cases the plan numbers C1-C6 — renamed P here because C is the
describe_room gate above). Same fake pool as part B (Gw dead, family
natural; Cloud ok, family keywords). A new prop's variant None is its
primary variant, whose front image is recorded on the MASTER record
(backend_image / image_routing / image_fallback_from).
P1 prop source, no glob, rules prop ["Gw","Cloud"] -> True. Gw is the
   intended entry (ok until it fails), fails at runtime, the re-run lands on
   Cloud at position 2 -> master record backend_image "Cloud",
   image_routing {"occasion":"prop","position":2,"spec":"Cloud"},
   image_fallback_from {"occasion":"prop","intended_spec":"Gw","position":1};
   the prompt Cloud got differs from Gw's (the "prop" style differs per
   family: natural prose vs keywords -> recomposed for the new backend).
P2 prop source with a dialog prompt "DIALOG" (no key areas on the prop, so
   nothing is appended) -> Gw (first try) receives exactly "DIALOG"; the
   re-run on Cloud receives a composed prompt, not "DIALOG" (decision 1:
   a dialog-final prompt is verbatim on the FIRST attempt only).
P3 prop source, explicit glob "Gw" while Gw cools down since P2 -> False;
   Cloud not asked (still its one P2 call) — an explicit pick is never
   routed elsewhere.
P4 an explicit re-render on Cloud after P1/P2 -> master record backend_image
   "Cloud" and NO image_routing / image_fallback_from (an explicit pick writes
   neither, and a new write of the front replaces the old marks).
P5 item image, no backend, rules item ["Cloud"] -> True; item meta
   backend "Cloud", routing {"occasion":"item","position":1,"spec":"Cloud"},
   no fallback_from (position 1 is the intended entry).
P6 item image, explicit backend "Gw" (cooling via mark_unhealthy) -> False,
   Cloud not asked. BEHAVIOUR CHANGE: the old path soft-warned and fell back
   to the automatic pick; an explicit pick now renders there or nowhere.
P7 item image, explicit "Cloud" with LoRA "foreign.safetensors" (the LoRA
   library is empty, nothing is associated with Cloud) -> False, Cloud not
   asked (the hard LoRA gate of an explicit dialog pick, CLAUDE.md).
P8 item image, no backend, rules item ["Gw","Cloud"], dialog prompt "DIALOG"
   + model_override "m-dialog" -> True. Gw (first try) receives exactly
   "DIALOG" with params model "m-dialog"; the re-run on Cloud receives the
   item's OWN subject composed for Cloud (it names "Lantern" — the item has
   no image_prompt / prompt_fragment, so its name is the subject — and is
   not "DIALOG") and no "model"; item meta routing position 2 and
   fallback_from {"occasion":"item","intended_spec":"Gw","position":1}.
P9 (fix round 1) POST /inventory/items/{id}/generate-image with explicit
   backend "Gw" while Gw cools down -> HTTPException 503 whose detail names
   'Gw' and "no automatic fallback"; no background thread is started and no
   backend is asked (the fire-and-forget thread could only log it).
P10 (fix round 1) the prop chain `_generate(image_only)` with explicit glob
   "Gw" while Gw cools down -> {"ok": False, "error": "source render failed:
   backend 'Gw' is not available — no automatic fallback"}, and the tracked
   task finishes with that same text (not a bare "source render failed").
P11 (fix round 1) the prop chain with explicit glob "Busy" whose render
   raises BackendBusyError("gpu busy") -> the exception propagates out of
   `_generate`, and the tracked task finishes with error
   "BackendBusyError: gpu busy" (it used to finish with "" = success).
P12 (fix round 1) back view of a prop WITHOUT a front image, front_reference
   on, rules prop ["Q*"] matching "Q-txt" (txt2img, cost 0) and "Q-ref"
   (img2img, cost 5): there is no picture to slot, so the routing is asked
   without a reference -> the cheaper Q-txt renders, Q-ref is never asked,
   and Q-txt gets no reference_images. (With has_ref=True — the old
   bool(front_reference) — the img2img preference would have picked Q-ref.)

PART D — scene view + event image (occasions "scene_view", "event"; plan
Task 14 + binding review note B2). Same fake pool as part B.
D1 the scene-view cache key is sha1("<state sig>|scene_view|<intended
   spec>")[:16], the intended spec being `routing.intended_spec_for` — the
   first chain entry that passes the CONFIGURATION filters (matched, fits,
   enabled, allowed); availability is ignored. Rules scene_view
   ["Gw","Cloud"] with both backends present -> key of "abc|scene_view|Gw".
   Gw put into a cooldown -> the intended entry is still Gw (a cooldown is a
   runtime state, not configuration) -> the key does NOT change (a fallback
   render is served until the chain changes). Rules ["Nope","Cloud"]: "Nope"
   matches no backend (no_match = configuration skip) -> intended "Cloud"
   -> key of "abc|scene_view|Cloud". Rules ["Cloud"] -> the same key as
   ["Nope","Cloud"], and a different one from the Gw key (another chain,
   another render).
D2 event image: a location with a background image, rules event
   ["Gw","Cloud"], Gw fails at runtime -> _do_generate returns a path; its
   sidecar "<image>.json" has backend "Cloud", backend_type "fake",
   routing {"occasion":"event","position":2,"spec":"Cloud"}, fallback_from
   {"occasion":"event","intended_spec":"Gw","position":1}; Cloud got the
   background in reference slot 1.
D3 scene render (build_scene_state replaced by a fixed state, mode
   "only_background", no persons): rules scene_view ["Gw","Cloud"], Gw fails
   at runtime -> {"ok": True, "cached": False} with sig ==
   _scene_sig(<state sig>) (computed while Gw was still the intended entry);
   the scene sidecar has location + room + backend "Cloud", routing position
   2 and fallback_from intended_spec "Gw"; Cloud got the background in
   reference slot 1 and a prompt recomposed for its family (differs from
   Gw's). A second render_scene of the same state (no force) is served from
   the cache: {"cached": True} with the same sig, nobody asked again.
D4 event image, rules event ["Gw"] with Gw cooling -> None, Gw never asked
   (a chain with nothing usable does not fall back to another backend).

PART E — gallery regenerate (occasion "regenerate") and scene photo
("photo"; plan Task 15 + the Task 14 carry-over: the one-click scene photo
must not pre-resolve a backend and pass it as an explicit pick). Same fake
pool as part B (Gw dead, family natural; Cloud ok, family keywords).
Character "Mara" has one gallery image and NO profile image (so the render
slots no identity reference: has_ref False).
E1 regenerate_image("Mara", <img>, "a portrait", create_new=True), rules
   regenerate ["Gw","Cloud"] -> ok and a NEW file (create_new); Gw is the
   intended entry, fails at runtime, the re-run lands on Cloud at position 2
   -> the new file's meta: backend "Cloud", routing position 2,
   fallback_from.intended_spec "Gw".
E2 explicit backend_name "Gw" (cooling since E1) -> RuntimeError, Cloud not
   asked again (still its one E1 call) — an explicit pick is never routed.
E3 explicit backend_name "Cloud" -> the new file's meta routing None and
   fallback_from None (an explicit render writes neither; stored as None so
   an overwritten file loses an old marker too).
E4 occasion="photo", rules photo ["Cloud"] and NO regenerate rules ->
   routing {"occasion":"photo","position":1,"spec":"Cloud"} (the occasion
   parameter is what gets routed, not a fixed "regenerate").
E5 take_scene_photo("Mara") with no dialog backend, prepare_scene_photo
   replaced by a stub whose dialog preselection default_backend is "Cloud",
   regenerate_image replaced by a recorder -> the recorder got
   backend_name "" and occasion "photo" (the preselection is NOT handed over
   as an explicit pick — the one-click photo keeps its fallback).
E6 take_scene_photo("Mara", backend_name="Gw") -> backend_name "Gw",
   occasion "photo" (a backend the user picked stays explicit).
E7 (fix round 1) explicit "Cloud" with LoRA "foreign.safetensors" (the LoRA
   library of the throwaway world is empty, so nothing is associated with
   Cloud) -> LoraNotAllowedError (the hard gate of an explicit pick,
   CLAUDE.md), raised before any render: Cloud's call count unchanged.
E8 (fix round 1) the source image's meta carries source_file "older.png"
   (it was itself a re-render); an explicit create_new regenerate on Cloud
   -> the NEW file's meta has no "source_file" (the marker belongs to the
   image it was written for, not to a variant copied from it), and
   variant_of names the source.
E9 (fix round 1) take_scene_photo whose regenerate raises
   LoraNotAllowedError -> the error propagates (a refusal, like the media
   master switch; /play/scene-photo maps it to 400), it is NOT folded into
   {"ok": False}.

PART F — video (occasion "video"; plan Task 16a). Labels F-V<n>; the mesh
half (Task 16b) adds its own F cases. Fake pool of video backends: "VDead"
(cost 0, fails with HTTP 500) and "VOk" (cost 3, renders b"mp4-or-glb");
`run_on_backend_channel` runs the job inline.
F-V1 generate_video, no glob, rules video ["VDead","VOk"] -> True; the file
   holds VOk's bytes; route_out == {"backend": "VOk", "routing":
   {"occasion": "video", "position": 2, "spec": "VOk"}, "fallback_from":
   {"occasion": "video", "intended_spec": "VDead", "position": 1}} (VDead
   is the intended entry, fails at RUNTIME and cools down -> marked,
   coordinator decision 2).
F-V2 generate_video, explicit "VDead" (cooling since F-V1) -> False; VOk is
   not asked again (still its one F-V1 call) — an explicit pick is never
   routed elsewhere.
F-V3 explicit "VOk" with route_out -> True, route_out == {"backend": "VOk"}
   (an explicit render writes neither "routing" nor "fallback_from").
F-V4 LoRA "foreign.safetensors" (the throwaway LoRA library is empty, so no
   backend has it): routed (rules video ["VOk"]) -> True, VOk's params carry
   no "lora_inputs" (soft half of the gate on a routed render); explicit
   "VOk" -> LoraNotAllowedError before any render (VOk's call count
   unchanged) — the hard half for a dialog pick.
F-V5 the video skill: declares no config fields (get_config_fields() == {},
   `animate_service` gone, not in _defaults). A stale stored skill value
   {"animate_service": "VDead"} (fresh pool: VDead fresh and dead), rules
   video ["VOk"]; the still render is replaced by a stub that saves one
   gallery image -> the skill answers with the video link, VDead is NEVER
   asked (the stored value is ignored, not migrated — the named feature
   loss) and the image's meta has animate_backend "VOk", animate_routing
   {"occasion": "video", "position": 1, "spec": "VOk"},
   animate_fallback_from None, and no "animate_service" key.
F-V6 get_character_image_metadata exposes animate_backend /
   animate_routing / animate_fallback_from for that image (whitelist), and
   the IMAGE's own "routing" is not the video's (the stub's still carries
   no routing -> absent).
F-V7 Instagram animate (the background thread runs inline): no service,
   rules video ["VDead","VOk"] (fresh pool) -> the post gets its video; the
   image meta: animate_backend "VOk", animate_routing position 2,
   animate_fallback_from.intended_spec "VDead". Then explicit service "VOk"
   -> animate_backend "VOk", animate_routing None, animate_fallback_from
   None (a re-animation drops the old marks). Explicit "VDead" (cooling)
   -> HTTPException 503 before anything starts, VOk's calls unchanged.
   Explicit "VOk" with LoRA "foreign.safetensors" -> HTTPException 400.
F-V8 deleting the animation scrubs the three keys: the Instagram route
   (delete_instagram_animation) and the gallery's remove_image_animation.
Fails on commit 462007bc (before Task 16a): F-V1 aborts with
   "generate_video() got an unexpected keyword argument 'route_out'".

PART F (mesh) — the mesh occasions (plan Task 16b; mesh_humanoid = rig
mixamo, mesh_creature = generic, mesh_object / mesh_building = none). Labels
F-M<n>. Every mesh chain entry resolves only to backends of the occasion's
rig (`backend_fits`: a wrong-rig backend is `wrong_kind`, a CONFIGURATION
skip — it never marks and is never asked). `_store_mesh_files` is replaced
by a recorder that writes the delivered bytes to "<output>.glb" and hands
back ONE LOD stage (faces 500), so the callers' sidecars can be read.
Pool 1: "MHum" (cost 0, rig mixamo), "MDead" (cost 0, rig none, fails with
HTTP 500), "MOk" (cost 2, rig none).
F-M1 generate_mesh(rig "none", occasion "mesh_object"), rules mesh_object
   ["MHum","MDead","MOk"]: MHum is wrong_kind (config skip), so the intended
   entry is MDead at position 2 (binding review note B1); MDead fails at
   runtime and cools down, the re-run skips it (cooldown) and lands on MOk
   at position 3 -> (ok, backend, routing.position,
   fallback_from.intended_spec) == (True, "MOk", 3, "MDead"),
   fallback_from.position == 2 (the INTENDED position, not the used one),
   routing {"occasion": "mesh_object", "position": 3, "spec": "MOk"};
   MHum asked 0 times, MDead 1, MOk 1.
F-M2 explicit "MHum" with rig "none" -> ok False, the error names the rig
   ("'mixamo', 'none' is needed"); nothing rendered (MHum 0 calls).
   BEHAVIOUR CHANGE: the old code silently re-picked the cheapest rig-none
   backend — an explicit pick is now never re-picked.
F-M3 explicit "MOk", rig "none" -> ok, backend "MOk", and neither "routing"
   nor "fallback_from" in the result (an explicit pick writes neither).
F-M4 explicit "MDead" (cooling since F-M1) -> ok False, error "mesh backend
   'MDead' unavailable"; MOk's calls unchanged (never routed elsewhere).
F-M5 no occasion: rig "none", rules mesh_object ["MOk"] -> routing occasion
   "mesh_object" (mesh_occasion_for_rig("none")); rig "" (= mixamo), rules
   mesh_humanoid ["MHum"] -> backend "MHum", routing occasion
   "mesh_humanoid".
F-M6 the dialogs' default (plan F5), pool 1 with MDead still cooling:
   rules mesh_object ["MOk"] -> model3d.list_mesh_backends("none")
   ["default"] == "MOk"; with occasion "mesh_building" and NO building chain
   -> the empty chain's pick, the cheapest AVAILABLE rig-none mesh backend:
   "MOk" (MDead, cost 0, cools). subjects.default_mesh_backend of both
   occasions says the same ("MOk"). A rig-less call has no occasion ->
   default "". Rules mesh_object ["MHum"] (wrong kind only) -> nothing
   resolves -> default "" and subjects.default_mesh_backend("mesh_object")
   == "".
F-M7 a re-run stays in the rig. Pool 2: "HDead" (cost 0, mixamo, dead),
   "MOk" (cost 2, none). Rules mesh_humanoid ["HDead","MOk"], rig "mixamo":
   HDead fails, MOk is wrong_kind -> nothing usable -> ok False with the
   NoRouteError text ("no backend available for mesh_humanoid"); MOk asked
   0 times.
F-M8 the character mesh (model3d.generate_for_current_outfit, signature
   "sig1", rig patched to mixamo, the post-processing steps stubbed). Pool
   3: "HDead" (cost 0, mixamo, dead), "HOk" (cost 1, mixamo). Rules
   mesh_humanoid ["HDead","HOk"].
   a) no glob -> ok; the sidecar: backend "HOk", routing {"occasion":
      "mesh_humanoid", "position": 2, "spec": "HOk"}, fallback_from
      {"occasion": "mesh_humanoid", "intended_spec": "HDead", "position": 1}.
   b) the auto-mesh hook (prefer_cheapest, coordinator decision 3), fresh
      pool 3: the cheapest AVAILABLE mixamo backend is HDead (cost 0) — an
      explicit pick, no chain: it fails -> ok False, HOk NOT asked (0 calls).
      Again (HDead now cools) -> the cheapest available is HOk -> ok, the
      sidecar has backend "HOk" and NO "routing" / "fallback_from".
F-M9 the building mesh (location_model3d._generate, backend "", the local
   low-tier build stubbed). Pool 4: "BDead" (cost 0, none, dead), "BOk"
   (cost 1, none); rules mesh_building ["BDead","BOk"] -> ok; the model's
   sidecar: backend "BOk", routing {"occasion": "mesh_building",
   "position": 2, "spec": "BOk"}, fallback_from.intended_spec "BDead"; the
   LOD stage of the same job (tier low) carries the same routing /
   fallback_from. get_building_info's "default" is "BOk" (the
   mesh_building chain resolves it; BDead cools).
F-M10 the prop mesh (props._generate mesh_only, glob "", the landing hooks
   stubbed), fresh pool 4, rules mesh_object ["BDead","BOk"] -> ok; the new
   gallery file's sidecar: backend "BOk", routing {"occasion":
   "mesh_object", "position": 2, "spec": "BOk"}, fallback_from.intended_spec
   "BDead"; its LOD stage the same.
Fails on commit 4893221f (before Task 16b): F-M1 aborts with
   "generate_mesh() got an unexpected keyword argument 'occasion'".

PART G — dialog options (plan Task 18a). Pool 1: "Gw" (cost 0, family
natural) cooling via mark_unhealthy, "Cloud" (cost 5, family keywords).
G1 build_imagegen_options("location") with rules location ["Gw","Cloud"]
   and Gw cooling -> resolved "Cloud", via "chain", chain statuses
   ["cooldown","ok"]; no "default_location" / "outfit_imagegen_default" key
   (the env bridge of the old default fields is gone, R2b).
G2 build_imagegen_options() without occasion -> no "resolved" key.
G3 the route answers 400 for occasion "mesh_low" (not in the catalog).
G4 get_outfit_lora_options("", "render") scopes on the expression chain's
   resolved backend: with rules expression ["Cloud"] the answer lists the
   LoRA library entries of "Cloud" (checked via a patched get_lora_options
   that records its backend argument).
G5 neither build_imagegen_options nor get_outfit_lora_options reads
   os.environ (source check: the configuration is not an environment
   variable, CLAUDE.md).
G6-G9 the character LoRA list resolves the backend EXACTLY like the routed
   variant render (Task 11 review): the same occasion (expression, or tpose
   for target "tpose"), the character's own match as position 0, the
   character's backend switches, and the img2img preference of a render
   that slots the profile image. The render side is the REAL string façade
   (generate_from_input with the payload keys the variant render sends:
   agent_name, occasion, profile_only, skip_gallery) whose
   generate_on_backend is replaced by a recorder of the backend name.
   Pool 2: "Rule" (cost 1, img2img), "Own-txt" (cost 0, txt2img), "Own-ref"
   (cost 5, img2img). Character "Vela": outfit_imagegen {"workflow":
   "Own*"}; rules expression ["Rule"], tpose ["Rule"].
G6 Vela without a profile image: no reference -> "Own*" is position 0,
   both Own backends are live, the cheaper Own-txt wins -> LoRA scope
   ["Own-txt"], the render ran on "Own-txt".
G7 Vela WITH a profile image: the render slots it (has_ref) -> inside the
   glob the img2img backend is preferred -> LoRA scope ["Own-ref"], the
   render ran on "Own-ref" (without has_ref the list would say Own-txt).
G8 Own-txt and Own-ref switched off for Vela (per-character backend
   switches, skill config image_generation.instances) -> position 0 is
   disabled_for_character, position 1 "Rule" resolves -> LoRA scope
   ["Rule"], the render ran on "Rule"; /world/imagegen-options?occasion=
   expression&character=Vela asked by an ADMIN says resolved "Rule" and its
   chain[0] is the character's own entry (source "character", status
   "disabled_for_character").
G9 switches back on; target "tpose" with tpose_workflow "Rule" -> LoRA
   scope ["Rule"], the tpose render ran on "Rule"; with tpose_workflow ""
   the tpose chain falls back to the workflow match -> ["Own-ref"] and the
   render on "Own-ref".
G10 (fix round 1) the dialog preselection names the backend the façade
   renders on: switches on, tpose_workflow "", Vela has her profile image.
   build_imagegen_options("expression", "Vela") -> resolved "Own-ref" (a
   character render slots the portrait -> img2img preferred) and the façade
   render of occasion "expression" ran on "Own-ref"; a "profile" render
   CREATES the portrait (set_profile) and slots none ->
   build_imagegen_options("profile", "Vela") resolved "Own-txt" and the
   façade render with set_profile True ran on "Own-txt".
G11 (fix round 1) ?character= on the open route is honoured only for an
   admin or a user with the character in allowed_characters; anyone else
   gets the chain WITHOUT the character (no position 0 — its own match and
   switches are per-character config). Route
   get_imagegen_options("expression", "Vela"), chain[0].source:
   no user -> "rule"; user role "user" with allowed [] -> "rule";
   user with allowed ["Vela"] -> "character"; admin -> "character".
Fails on commit 4eb1856e (before Task 18a): G1 aborts with
   "build_imagegen_options() takes 0 positional arguments but 1 was given".
Fails on commit d0452bc6 (before fix round 1): G10 expression (options say
   "Own-txt", the render runs on "Own-ref") and G11 (every caller sees the
   character's chain).

PART H — an explicit pick is checked BEFORE a route answers "started"
(R2b review blocker + ruling N3: one helper,
app.core.explicit_backend.require_explicit_backend[_async]). Fake pool as in
part B: "Gw" (dead, cooled via mark_unhealthy), "Cloud" (ok). track_start is
recorded; a track's row is read back from the throwaway task queue.
H1 POST /world/locations/{id}/gallery (single mode) with backend "Gw" while
   Gw cools down -> HTTPException 503 whose detail names 'Gw' and says "no
   automatic fallback"; NO track was started (the old route created a
   pending track and answered "started" — the background core refused the
   pick only then, and the track stayed pending forever); nobody asked.
H2 the same route, backend "Cloud" (available at the check), while the core
   is replaced by one that raises HTTPException(503, "backend 'Cloud' went
   away") before it adopts the track (the race the up-front check cannot
   close) -> the route answers "started" with a track_id; once the
   background task has run, that track is "failed" with error
   "backend 'Cloud' went away" (not pending).
H3 the REAL core, explicit "Cloud" with LoRA "foreign.safetensors" (the
   throwaway LoRA library associates nothing with Cloud): the core refuses
   inside _render with a 400 and finishes the track itself -> the track is
   "failed" with an error that says "does not associate", and it was
   finished exactly ONCE (the route's safety net leaves a finished track
   alone — a second finish would overwrite its duration with 0).
Fails on commit 3177ddd4 (before this fix): H1 answers {"status":
   "started"} and records one track_start; H2's track stays "pending".
H4 the character gallery regenerate (its sync body) with backend "Gw"
   (cooling) -> 503, no track_start, no thread; with "Cloud" (available) ->
   {"status": "started"} and one track_start (the worker is replaced by a
   recorder that got backend_name "Cloud").
H5 prop re-render POST /world/props/{id}/generate (trigger_generation
   replaced by a recorder): image_backend "Gw" (cooling) -> 503, nothing
   triggered; the SAME body with mesh_only true -> triggered (the image pick
   is not used by a mesh-only run, so it is not checked); mesh_backend
   "MDead" (a cooling mesh backend) -> 503 before anything is triggered;
   image_backend "Cloud" -> triggered with image_backend_glob "Cloud".
H6 prop generate (its sync body) with mesh_backend "MDead" (cooling) -> 503
   and NO prop record was created (the check runs before create_prop).
H7 the character mesh route with backend "Cloud" — an IMAGE backend,
   available, but not a mesh backend -> 503 (the pick is resolved within
   media "mesh"); trigger_generation not called.
H8 static: every thread-spawning route with an explicit pick calls the ONE
   helper (require_explicit_backend or its async twin; the prop routes
   through _require_prop_picks, which calls the async twin) in its body:
   world.py generate_gallery_image, _location_model3d_generate_sync,
   _room_model3d_generate_sync, _prop_generate_sync, prop_regenerate,
   _require_prop_picks; prop_variants.py prop_variant_generate;
   characters.py _regenerate_character_image_sync,
   generate_character_model3d; instagram.py _regenerate_post_image_sync,
   _animate_instagram_post_sync; inventory.py generate_item_image_route —
   and none of those routes calls _wait_for_explicit_backend itself any
   more (no per-route copy of the check).
H9 the profile-image dialog (character_ops.generate_profile_image_core,
   R2b review F-R3-2 — it used to turn every "Error: …" answer of the
   façade into a 500 "Kein Bild im Ergebnis: Error: …"). Character "Nell"
   from H4, pool Gw (cooling) + Cloud:
   a) backend "Gw" -> 503, detail names 'Gw' and "no automatic fallback";
   b) no backend, rules profile ["Gw"] (only a cooling entry) -> the façade
      answers "Error: no backend available for profile: …" -> 503 with the
      detail "no backend available for profile: …" (no "Error:" prefix);
   c) the façade replaced by one answering "Error: Cloud: HTTP 500: gone"
      -> 500, detail "Cloud: HTTP 500: gone";
   d) the façade answering "Error: Media generation is disabled for this
      world" -> 409;
   and no detail of a)-d) is German ("Kein", "fehlgeschlagen").
   Fails on commit dafc7747 (before this fix): a)-d) all answer 500
   "Kein Bild im Ergebnis: Error: …".

DEFERRED: the surface-texture case of the plan (its C4, occasion
"surface_texture") waits until app/core/surface_textures.py — which carries
another session's uncommitted change — is routed.
Item renders pass through postprocess_outfit_image (rembg); the smoke
replaces it with the identity so no model is loaded or downloaded.
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_TMP = tempfile.mkdtemp(prefix="routing-callers-")
os.environ["STORAGE_DIR"] = _TMP
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="routing-callers-clips-")
from app.core import paths  # noqa: E402
paths.init(_TMP)
from app.core import config, db  # noqa: E402
config.load(Path(_TMP) / "config.json")
db.init_schema()
from app.imagegen import service as service_mod  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class _B:
    def __init__(self, name):
        self.name = name
        self.instance_enabled = True
        self.MEDIA_TYPE = "image"
        self.category = "img2img"


class RecordingService:
    """Records every string payload; answers with an Error so the caller
    stops right after handing it over."""
    enabled = True

    def __init__(self):
        self.payloads = []
        self.backends = [_B("Flux2 A")]

    def generate_from_input(self, raw):
        self.payloads.append(json.loads(raw))
        return "Error: recorded"


from app.imagegen.base import ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (90, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


class FakeBackend(ImageBackend):
    """Records what it is asked to render; fails with HTTP 500 when `dead`."""

    def __init__(self, name, cost, family, dead=False, ref_slots=1):
        super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_CALLERS_")
        self.image_family = family
        self.category = "img2img"
        self.ref_slot_count = ref_slots
        self.instance_enabled = True
        self._available = True
        self.dead = dead
        self.calls = []
        self.probes = 0

    def check_availability(self):
        self.probes += 1
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        raise AssertionError("generate() is overridden")

    def generate(self, prompt, negative_prompt, params, log_meta=None):
        self.calls.append({"prompt": prompt, "negative": negative_prompt,
                           "params": dict(params)})
        if self.dead:
            raise RuntimeError(f"{self.name}: HTTP 500: gone")
        return [png_bytes()]


def install_pool(*backends):
    """A real ImageService whose pool holds the fakes; jobs run inline."""
    svc = service_mod.ImageService()
    svc.enabled = True
    svc._pool = BackendPool(list(backends), agent_instances_provider=lambda n: {})
    service_mod._service = svc
    service_mod.get_image_service = lambda: svc
    return svc


service_mod.ImageService.run_on_backend_channel = staticmethod(
    lambda backend, gen_fn, **kw: gen_fn())
# No configured instances: the constructor would otherwise probe the default
# backends of the throwaway config over the network.
service_mod.ImageService._load_instances = lambda self: []


def set_routing(rules):
    cfg = config.get_all()
    ig = dict(cfg.get("image_generation") or {})
    ig["routing"] = rules
    cfg["image_generation"] = ig
    config.save(cfg)


def part_a():
    print("A) messaging frame")
    from app.core import messaging_frame
    rec = RecordingService()
    service_mod.get_image_service = lambda: rec
    messaging_frame.generate_frame("a phone")
    check("A1 routed", [(p.get("occasion"), "backend" in p) for p in rec.payloads],
          [("frame", False)])
    rec.payloads.clear()
    messaging_frame.generate_frame("a phone", "Flux2*")
    check("A2 explicit", [(p.get("backend"), "occasion" in p) for p in rec.payloads],
          [("Flux2*", False)])


def part_b():
    print("B) location family")
    from fastapi import HTTPException
    from app.core import world_ops
    from app.core.task_queue import get_task_queue
    from app.models import world
    loc = world.add_location("Mill", "A mill by the river.")["id"]

    track_errors = []
    _tq = get_task_queue()
    _orig_finish = _tq.track_finish

    def _record_finish(task_id, error=""):
        track_errors.append(error)
        return _orig_finish(task_id, error=error)
    _tq.track_finish = _record_finish

    def gallery(data):
        time.sleep(1.1)          # a fresh int(time.time()) file name per render
        return asyncio.run(world_ops.generate_gallery_image_core(loc, dict(data)))

    def meta_of(name):
        return (world.get_gallery_image_metas(loc) or {}).get(name) or {}

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"location": ["Gw", "Cloud"]})
    res = gallery({"prompt": "a mill by the river"})
    m = meta_of(res["image"])
    check("B1 backend", m.get("backend"), "Cloud")
    check("B1 routing", m.get("routing"), {"occasion": "location", "position": 2, "spec": "Cloud"})
    check("B1 fallback_from", m.get("fallback_from"),
          {"occasion": "location", "intended_spec": "Gw", "position": 1})
    check("B2 recomposed for the second backend",
          gw.calls[0]["prompt"] != cloud.calls[0]["prompt"], True)

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    gallery({"prompt": "VERBATIM", "settings_applied": True})
    check("B3 verbatim on its own backend", gw.calls[0]["prompt"], "VERBATIM")
    check("B3 not verbatim elsewhere", cloud.calls[0]["prompt"] != "VERBATIM", True)

    try:
        gallery({"prompt": "x", "backend": "Gw"})       # Gw cools down since B3
        check("B4 explicit dead", "no exception", "HTTPException 503")
    except HTTPException as e:
        check("B4 explicit dead", e.status_code, 503)
    check("B4 Cloud never asked", len(cloud.calls), 1)   # only the B3 call

    res = gallery({"prompt": "x", "backend": "Cloud"})
    check("B5 explicit renders", meta_of(res["image"]).get("backend"), "Cloud")
    check("B5 no routing meta", "routing" in meta_of(res["image"]), False)

    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(cloud)
    set_routing({"timevariant": ["Cloud"]})
    src = world.get_gallery_dir(loc) / "src.png"
    src.write_bytes(png_bytes())
    time.sleep(1.1)
    res = asyncio.run(world_ops.generate_time_variant_core(
        loc, "src.png", "night", "", ""))
    check("B6 routing", meta_of(res["image"]).get("routing"),
          {"occasion": "timevariant", "position": 1, "spec": "Cloud"})
    check("B6 source in the reference slot",
          cloud.calls[0]["params"].get("reference_images"),
          {"input_reference_image_1": str(src)})

    set_routing({"location": ["Cloud"]})
    before = {p.name for p in world.get_gallery_dir(loc).glob("*.png")}
    time.sleep(1.1)
    asyncio.run(world_ops.generate_location_background(loc, "a mill"))
    new = sorted({p.name for p in world.get_gallery_dir(loc).glob("*.png")} - before)
    check("B7 one background image", len(new), 1)
    bm = meta_of(new[0]) if new else {}
    check("B7 background routed", (bm.get("backend"), bm.get("routing")),
          ("Cloud", {"occasion": "location", "position": 1, "spec": "Cloud"}))

    from app.skills.describe_room_skill import DescribeRoomSkill
    room = world.add_room(loc, "Millroom", "Grinding stones under a timber roof.")
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(cloud)
    before = set(threading.enumerate())
    time.sleep(1.1)
    DescribeRoomSkill._trigger_room_image(loc, room["id"])
    for t in set(threading.enumerate()) - before:
        t.join(timeout=30)
    rooms = world.get_gallery_image_rooms(loc) or {}
    room_images = [n for n, r in rooms.items() if r == room["id"]]
    check("B8 one room image", len(room_images), 1)
    rm = meta_of(room_images[0]) if room_images else {}
    check("B8 room image backend", rm.get("backend"), "Cloud")
    check("B8 room image routing", rm.get("routing"),
          {"occasion": "location", "position": 1, "spec": "Cloud"})
    import re
    check("B8 room image name has a suffix",
          bool(room_images) and bool(re.fullmatch(r"\d+_[0-9a-f]{6}\.png", room_images[0])),
          True)

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"location": ["Gw", "Cloud"]})
    try:
        gallery({"prompt": "x", "backend": "Gw"})       # fresh Gw: available, then fails
        check("B9 explicit fails at runtime", "no exception", "HTTPException 500")
    except HTTPException as e:
        check("B9 explicit fails at runtime", e.status_code, 500)
    check("B9 asked Gw once, Cloud never", (len(gw.calls), len(cloud.calls)), (1, 0))

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    gallery({"prompt": "x", "model_override": "m-dialog"})
    check("B10 first try carries the dialog model", gw.calls[0]["params"].get("model"), "m-dialog")
    check("B10 re-run without it", "model" in cloud.calls[0]["params"], False)
    gallery({"prompt": "x", "backend": "Cloud", "model_override": "m-dialog"})
    check("B10 explicit carries it", cloud.calls[1]["params"].get("model"), "m-dialog")

    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(cloud)
    track_errors.clear()
    try:
        gallery({"prompt": "x", "backend": "Cloud",
                 "loras": [{"name": "foreign.safetensors", "strength": 1.0}]})
        check("B11 explicit foreign LoRA", "no exception", "HTTPException 400")
    except HTTPException as e:
        check("B11 explicit foreign LoRA", (e.status_code, "does not associate" in str(e.detail)),
              (400, True))
    check("B11 Cloud never asked", len(cloud.calls), 0)
    check("B11 track error is the real reason",
          [("does not associate" in (e or "")) for e in track_errors], [True])

    cloud, spare = FakeBackend("Cloud", 5, "keywords"), FakeBackend("Spare", 1, "natural")
    install_pool(cloud, spare)
    set_routing({"location": ["Cloud"]})
    res = gallery({"prompt": "x"})
    check("B12 rendered on the chain", meta_of(res["image"]).get("backend"), "Cloud")
    check("B12 Spare never probed", spare.probes, 0)
    gallery({"prompt": "x", "backend": "Cloud"})
    check("B12 explicit pick does not probe Spare", spare.probes, 0)
    return loc, room["id"]


def part_c(loc, millroom_id):
    print("C) describe_room renders only on a change or a missing image")
    from app.models import world
    from app.skills.describe_room_skill import DescribeRoomSkill
    triggered = []
    DescribeRoomSkill._trigger_room_image = staticmethod(
        lambda location_id, room_id: triggered.append(room_id))
    skill = DescribeRoomSkill({})
    skill._get_allowed_location_ids = lambda character: [loc]

    def describe(room, **fields):
        triggered.clear()
        reply = skill.execute(json.dumps(dict(agent_name="demo", location_id=loc,
                                              room=room, **fields)))
        return list(triggered), "Bildgenerierung gestartet." in reply

    check("C1 unchanged description", describe(
        "Millroom", description="Grinding stones under a timber roof."), ([], False))
    check("C2 changed description", describe(
        "Millroom", description="Flour sacks by the grinding stones."), ([millroom_id], True))
    check("C3 new image prompt", describe(
        "Millroom", image_prompt="A mill interior, warm light"), ([millroom_id], True))
    check("C4 description changed, image prompt kept", describe(
        "Millroom", description="An empty millroom."), ([], False))
    loft = world.add_room(loc, "Loft", "Beams and dusty grain sacks.")
    check("C5 room without an image", describe(
        "Loft", description="Beams and dusty grain sacks."), ([loft["id"]], True))
    rendered, said = describe("Cellar", description="A cool stone cellar.")
    cellar = world.get_room_by_name(world.get_location_by_id(loc), "Cellar") or {}
    check("C6 new room", (rendered, said), ([cellar.get("id")], True))


def part_p():
    print("P) prop source / item image")
    from app.core import props
    from app.models import character as character_mod
    from app.models import inventory
    from app.routes import inventory as inventory_routes

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"prop": ["Gw", "Cloud"], "item": ["Cloud"]})
    pid = props.create_prop(name="Crate", description="a wooden crate")["id"]
    ok = props._render_source(pid, "", "", "")
    rec = props.read_sidecar(pid)
    check("P1 rendered", ok, True)
    check("P1 master record", (rec.get("backend_image"), rec.get("image_routing"),
                               rec.get("image_fallback_from")),
          ("Cloud", {"occasion": "prop", "position": 2, "spec": "Cloud"},
           {"occasion": "prop", "intended_spec": "Gw", "position": 1}))
    check("P1 recomposed", bool(gw.calls) and bool(cloud.calls)
          and gw.calls[0]["prompt"] != cloud.calls[0]["prompt"], True)

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    props._render_source(pid, "", "DIALOG", "")
    check("P2 first try verbatim", gw.calls[0]["prompt"] if gw.calls else None, "DIALOG")
    check("P2 re-run composed", bool(cloud.calls) and cloud.calls[0]["prompt"] != "DIALOG",
          True)
    check("P3 explicit dead", props._render_source(pid, "Gw", "", ""), False)
    check("P3 Cloud not asked", len(cloud.calls), 1)

    check("P4 explicit renders", props._render_source(pid, "Cloud", "", ""), True)
    rec = props.read_sidecar(pid)
    check("P4 explicit clears the marks", (rec.get("backend_image"),
                                           "image_routing" in rec,
                                           "image_fallback_from" in rec),
          ("Cloud", False, False))

    character_mod.postprocess_outfit_image = lambda p: p   # no rembg model
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(cloud)
    item = inventory.add_item("Lantern", description="a brass lantern")
    iid = item["id"] if isinstance(item, dict) else item
    check("P5 rendered", inventory_routes.generate_item_image_sync(iid, {}), True)
    im = (inventory.get_item(iid) or {}).get("image_meta") or {}
    check("P5 item meta", (im.get("backend"), im.get("routing"), "fallback_from" in im),
          ("Cloud", {"occasion": "item", "position": 1, "spec": "Cloud"}, False))

    gw = FakeBackend("Gw", 0, "natural", dead=True)
    gw.mark_unhealthy("smoke", 300)
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    check("P6 explicit dead", inventory_routes.generate_item_image_sync(iid, {"backend": "Gw"}),
          False)
    check("P6 nobody asked", (len(gw.calls), len(cloud.calls)), (0, 0))

    check("P7 explicit foreign LoRA", inventory_routes.generate_item_image_sync(
        iid, {"backend": "Cloud",
              "loras": [{"name": "foreign.safetensors", "strength": 1.0}]}), False)
    check("P7 Cloud not asked", len(cloud.calls), 0)

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"prop": ["Gw", "Cloud"], "item": ["Gw", "Cloud"]})
    check("P8 rendered", inventory_routes.generate_item_image_sync(
        iid, {"prompt": "DIALOG", "model_override": "m-dialog"}), True)
    check("P8 first try verbatim", [(c["prompt"], c["params"].get("model")) for c in gw.calls],
          [("DIALOG", "m-dialog")])
    cp = cloud.calls[0] if cloud.calls else {"prompt": "", "params": {}}
    check("P8 re-run own subject", ("Lantern" in cp["prompt"], "DIALOG" in cp["prompt"],
                                    "model" in cp["params"]), (True, False, False))
    im = (inventory.get_item(iid) or {}).get("image_meta") or {}
    check("P8 item meta", ((im.get("routing") or {}).get("position"), im.get("fallback_from")),
          (2, {"occasion": "item", "intended_spec": "Gw", "position": 1}))

    from fastapi import HTTPException
    gw = FakeBackend("Gw", 0, "natural", dead=True)
    gw.mark_unhealthy("smoke", 300)
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)

    class _Req:
        async def json(self):
            return {"backend": "Gw", "prompt": "x"}
    # The background thread's target is the module-level function, looked up
    # when the route starts it: a recorder there sees every started render.
    # (threading.Thread itself must stay real — asyncio.to_thread needs it.)
    started = []
    _real_sync = inventory_routes.generate_item_image_sync
    inventory_routes.generate_item_image_sync = lambda *a, **kw: started.append(a)
    try:
        asyncio.run(inventory_routes.generate_item_image_route(iid, _Req()))
        check("P9 explicit dead -> 503", "no exception", "HTTPException 503")
    except HTTPException as e:
        check("P9 explicit dead -> 503", (e.status_code, "'Gw'" in str(e.detail),
                                          "no automatic fallback" in str(e.detail)),
              (503, True, True))
    finally:
        time.sleep(0.2)          # a wrongly started thread would have run by now
        inventory_routes.generate_item_image_sync = _real_sync
    check("P9 no thread, nobody asked", (started, len(gw.calls), len(cloud.calls)),
          ([], 0, 0))

    from app.core.task_queue import get_task_queue
    from app.imagegen.base import BackendBusyError
    track_errors = []
    _tq = get_task_queue()
    _orig_finish = _tq.track_finish

    def _record_finish(task_id, error=""):
        track_errors.append(error)
        return _orig_finish(task_id, error=error)
    _tq.track_finish = _record_finish
    try:
        res = props._generate(pid, "", "", "Gw", "", image_only=True)
        why = ("source render failed: backend 'Gw' is not available"
               " — no automatic fallback")
        check("P10 chain error names the reason", res, {"ok": False, "error": why})
        check("P10 track error", track_errors, [why])

        class _BusyBackend(FakeBackend):
            def generate(self, prompt, negative_prompt, params, log_meta=None):
                self.calls.append({"prompt": prompt})
                raise BackendBusyError("gpu busy")
        install_pool(_BusyBackend("Busy", 0, "natural"))
        track_errors.clear()
        try:
            props._generate(pid, "", "", "Busy", "", image_only=True)
            check("P11 busy propagates", "no exception", "BackendBusyError")
        except BackendBusyError:
            check("P11 busy propagates", True, True)
        check("P11 track error", track_errors, ["BackendBusyError: gpu busy"])
    finally:
        _tq.track_finish = _orig_finish

    q_txt, q_ref = FakeBackend("Q-txt", 0, "keywords"), FakeBackend("Q-ref", 5, "keywords")
    q_txt.category = "txt2img"
    install_pool(q_txt, q_ref)
    set_routing({"prop": ["Q*"]})
    bare = props.create_prop(name="Stool", description="a three-legged stool")["id"]
    check("P12 rendered", props._render_source(bare, "", "", "", view="back",
                                               front_reference=True), True)
    check("P12 no reference -> cheapest, no slot",
          (len(q_txt.calls), len(q_ref.calls),
           "reference_images" in (q_txt.calls[0]["params"] if q_txt.calls else {})),
          (1, 0, False))


def part_d():
    import hashlib
    print("D) scene view + event image")
    from app.core import event_images, scene_render
    from app.imagegen import routing
    from app.models import world

    def key(spec):
        return hashlib.sha1(f"abc|scene_view|{spec}".encode("utf-8")).hexdigest()[:16]

    gw, cloud = FakeBackend("Gw", 0, "natural"), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"scene_view": ["Gw", "Cloud"]})
    check("D1 sig from the intended entry", scene_render._scene_sig("abc"), key("Gw"))
    gw.mark_unhealthy("smoke", 300)
    check("D1 cooldown keeps the intended entry",
          routing.intended_spec_for("scene_view"), "Gw")
    check("D1 cooldown keeps the sig", scene_render._scene_sig("abc"), key("Gw"))
    set_routing({"scene_view": ["Nope", "Cloud"]})
    check("D1 no_match is not intended", routing.intended_spec_for("scene_view"), "Cloud")
    check("D1 sig of the configured entry", scene_render._scene_sig("abc"), key("Cloud"))
    set_routing({"scene_view": ["Cloud"]})
    check("D1 another chain, another sig",
          (scene_render._scene_sig("abc"), scene_render._scene_sig("abc") != key("Gw")),
          (key("Cloud"), True))

    loc = world.add_location("Harbour", "A small harbour.")["id"]
    gdir = world.get_gallery_dir(loc)
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "bg.png").write_bytes(png_bytes())
    world.toggle_background_image(loc, "bg.png")
    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"event": ["Gw", "Cloud"]})
    out = event_images._do_generate("ev-smoke", loc, "a storm rolls in", False)
    side = json.loads(Path(out).with_suffix(".json").read_text(encoding="utf-8")) if out else {}
    check("D2 sidecar", side,
          {"backend": "Cloud", "backend_type": "fake",
           "routing": {"occasion": "event", "position": 2, "spec": "Cloud"},
           "fallback_from": {"occasion": "event", "intended_spec": "Gw", "position": 1}})
    check("D2 background slotted",
          cloud.calls[0]["params"].get("reference_images", {})
          .get("input_reference_image_1", "").endswith("bg.png") if cloud.calls else False,
          True)

    bg = gdir / "bg.png"
    state = {"location": loc, "room": "", "label": "Harbour", "mode": "only_background",
             "setting": "harbour", "conditions": "", "bg_path": bg, "chars": [],
             "event_text": "", "sig": "state-d3"}
    scene_render.build_scene_state = lambda avatar: dict(state)
    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"scene_view": ["Gw", "Cloud"]})
    want_sig = scene_render._scene_sig("state-d3")
    res = scene_render.render_scene("demo", force=True)
    check("D3 rendered", (res.get("ok"), res.get("cached"), res.get("sig")),
          (True, False, want_sig))
    try:
        meta = json.loads(scene_render._scene_meta_path(want_sig).read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    check("D3 scene sidecar", (meta.get("location"), meta.get("room"), meta.get("backend"),
                               (meta.get("routing") or {}).get("position"),
                               (meta.get("fallback_from") or {}).get("intended_spec")),
          (loc, "", "Cloud", 2, "Gw"))
    check("D3 background slotted on Cloud",
          cloud.calls[0]["params"].get("reference_images") if cloud.calls else None,
          {"input_reference_image_1": str(bg)})
    check("D3 recomposed for Cloud", bool(gw.calls) and bool(cloud.calls)
          and gw.calls[0]["prompt"] != cloud.calls[0]["prompt"], True)
    res = scene_render.render_scene("demo")
    check("D3 cached under the same sig", (res.get("cached"), res.get("sig")),
          (True, want_sig))
    check("D3 nobody asked again", (len(gw.calls), len(cloud.calls)), (1, 1))

    gw = FakeBackend("Gw", 0, "natural")
    gw.mark_unhealthy("smoke", 300)
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"event": ["Gw"]})
    check("D4 nothing usable -> None",
          event_images._do_generate("ev-smoke-2", loc, "fog", False), None)
    check("D4 nobody asked", (len(gw.calls), len(cloud.calls)), (0, 0))


def part_e():
    print("E) regenerate + scene photo")
    from app.models.character import (get_character_images_dir, get_single_image_meta,
                                      save_character_profile)
    from app.skills import image_regenerate
    from app.skills.image_regenerate import regenerate_image
    save_character_profile("Mara", {"name": "Mara", "appearance": "a tall woman"},
                           create_new=True)
    img_dir = get_character_images_dir("Mara")
    img_dir.mkdir(parents=True, exist_ok=True)
    src = img_dir / "Mara_1_a.png"
    src.write_bytes(png_bytes())

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    svc = install_pool(gw, cloud)
    svc._generate_image_analysis = lambda *a, **k: None
    set_routing({"regenerate": ["Gw", "Cloud"], "photo": ["Cloud"]})
    ok, _p, new_path = regenerate_image("Mara", str(src), "a portrait", create_new=True)
    meta = get_single_image_meta("Mara", Path(new_path).name)
    check("E1 new file", (ok, Path(new_path).name != src.name), (True, True))
    check("E1 meta", (meta.get("backend"), (meta.get("routing") or {}).get("position"),
                      (meta.get("fallback_from") or {}).get("intended_spec")),
          ("Cloud", 2, "Gw"))
    try:
        regenerate_image("Mara", str(src), "a portrait", backend_name="Gw", create_new=True)
        check("E2 explicit dead", "no exception", "RuntimeError")
    except RuntimeError:
        check("E2 explicit dead", True, True)
    check("E2 Cloud not asked again", len(cloud.calls), 1)
    ok, _p, p3 = regenerate_image("Mara", str(src), "a portrait", backend_name="Cloud",
                                  create_new=True)
    m3 = get_single_image_meta("Mara", Path(p3).name)
    check("E3 explicit: no marker",
          (ok, m3.get("backend"), m3.get("routing"), m3.get("fallback_from")),
          (True, "Cloud", None, None))
    set_routing({"photo": ["Cloud"]})
    ok, _p, p4 = regenerate_image("Mara", str(src), "a photo", create_new=True,
                                  occasion="photo")
    check("E4 occasion photo", get_single_image_meta("Mara", Path(p4).name).get("routing"),
          {"occasion": "photo", "position": 1, "spec": "Cloud"})

    from app.core.lora_library import LoraNotAllowedError
    n_cloud = len(cloud.calls)
    try:
        regenerate_image("Mara", str(src), "a portrait", backend_name="Cloud",
                         loras=[{"name": "foreign.safetensors", "strength": 1.0}],
                         create_new=True)
        check("E7 foreign LoRA refused", "no exception", "LoraNotAllowedError")
    except LoraNotAllowedError:
        check("E7 foreign LoRA refused", True, True)
    check("E7 no backend called", len(cloud.calls) - n_cloud, 0)

    from app.models.character import add_character_image_metadata
    add_character_image_metadata("Mara", src.name, {"source_file": "older.png"})
    ok, _p, p8 = regenerate_image("Mara", str(src), "a portrait", backend_name="Cloud",
                                  create_new=True)
    m8 = get_single_image_meta("Mara", Path(p8).name)
    check("E8 no inherited source_file", (ok, "source_file" in m8, m8.get("variant_of")),
          (True, False, src.name))

    from app.core import scene_photo
    calls = []

    def _recorder(**kw):
        calls.append((kw.get("backend_name"), kw.get("occasion")))
        return (False, "", "")
    _orig_prep, _orig_regen = scene_photo.prepare_scene_photo, image_regenerate.regenerate_image
    scene_photo.prepare_scene_photo = lambda avatar: {
        "ok": True, "prompt": "Candid photograph", "subjects": ["Mara"],
        "present": ["Mara"], "location": "", "room": "", "default_backend": "Cloud"}
    image_regenerate.regenerate_image = _recorder
    try:
        scene_photo.take_scene_photo("Mara")
        check("E5 one-click photo is routed", calls, [("", "photo")])
        calls.clear()
        scene_photo.take_scene_photo("Mara", backend_name="Gw")
        check("E6 a picked backend stays explicit", calls, [("Gw", "photo")])

        def _refuse(**kw):
            raise LoraNotAllowedError("Cloud", ["foreign.safetensors"])
        image_regenerate.regenerate_image = _refuse
        try:
            got = scene_photo.take_scene_photo("Mara", backend_name="Cloud")
            check("E9 LoRA refusal propagates", got, "LoraNotAllowedError")
        except LoraNotAllowedError:
            check("E9 LoRA refusal propagates", True, True)
    finally:
        scene_photo.prepare_scene_photo = _orig_prep
        image_regenerate.regenerate_image = _orig_regen


class FakeMedia(FakeBackend):
    """A video / mesh backend of the fake pool (plan Task 16): MEDIA_TYPE
    and category set, ``mesh_rig`` for a mesh backend."""

    def __init__(self, name, cost, media, rig="", dead=False):
        super().__init__(name, cost, "", dead=dead)
        self.MEDIA_TYPE = media
        self.category = "img2mesh" if media == "mesh" else "txt2img"
        if rig:
            self.mesh_rig = rig

    def generate(self, prompt, negative_prompt, params, log_meta=None):
        self.calls.append({"params": dict(params)})
        if self.dead:
            raise RuntimeError(f"{self.name}: HTTP 500: gone")
        self.last_result_files = [{"name": f"{self.name}.glb"}]
        return [b"mp4-or-glb"]


class _InlineThread:
    """Stands in for threading.Thread: start() runs the target right away."""

    def __init__(self, target=None, daemon=None, args=(), kwargs=None, **_kw):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


def part_f_video():
    print("F) video")
    from fastapi import HTTPException
    from app.core.lora_library import LoraNotAllowedError
    tmp = Path(_TMP)
    (tmp / "still.png").write_bytes(png_bytes())

    vd, vo = FakeMedia("VDead", 0, "video", dead=True), FakeMedia("VOk", 3, "video")
    svc = install_pool(vd, vo)
    set_routing({"video": ["VDead", "VOk"]})
    ro = {}
    ok = svc.generate_video(str(tmp / "still.png"), "wave", str(tmp / "v.mp4"), route_out=ro)
    check("F-V1 routed video", (ok, ro), (True, {
        "backend": "VOk",
        "routing": {"occasion": "video", "position": 2, "spec": "VOk"},
        "fallback_from": {"occasion": "video", "intended_spec": "VDead", "position": 1}}))
    check("F-V1 file written", (tmp / "v.mp4").read_bytes(), b"mp4-or-glb")
    check("F-V2 explicit dead", svc.generate_video(str(tmp / "still.png"), "wave",
                                                   str(tmp / "v2.mp4"), backend_glob="VDead"),
          False)
    check("F-V2 VOk not asked again", len(vo.calls), 1)
    ro = {}
    ok = svc.generate_video(str(tmp / "still.png"), "wave", str(tmp / "v3.mp4"),
                            backend_glob="VOk", route_out=ro)
    check("F-V3 explicit: no routing meta", (ok, ro), (True, {"backend": "VOk"}))

    foreign = [{"name": "foreign.safetensors", "strength": 1.0}]
    set_routing({"video": ["VOk"]})
    ok = svc.generate_video(str(tmp / "still.png"), "wave", str(tmp / "v4.mp4"),
                            loras=foreign)
    check("F-V4 routed: LoRA filtered", (ok, "lora_inputs" in vo.calls[-1]["params"]),
          (True, False))
    n = len(vo.calls)
    try:
        svc.generate_video(str(tmp / "still.png"), "wave", str(tmp / "v5.mp4"),
                           backend_glob="VOk", loras=foreign)
        check("F-V4 explicit: LoRA refused", "no exception", "LoraNotAllowedError")
    except LoraNotAllowedError:
        check("F-V4 explicit: LoRA refused", True, True)
    check("F-V4 explicit: nothing rendered", len(vo.calls) - n, 0)

    # -- F-V5/F-V6: the video skill -------------------------------------
    from app.models.character import (get_character_image_metadata,
                                      get_character_images_dir, get_single_image_meta,
                                      remove_image_animation, save_character_profile,
                                      save_character_skill_config)
    from app.skills.video_generation_skill import VideoGenerationSkill
    save_character_profile("Mara", {"name": "Mara", "appearance": "a tall woman"},
                           create_new=True)
    skill = VideoGenerationSkill({})
    check("F-V5 no config fields", (skill.get_config_fields(),
                                    "animate_service" in skill._defaults), ({}, False))
    save_character_skill_config("Mara", "video_generation", {"animate_service": "VDead"})
    vd, vo = FakeMedia("VDead", 0, "video", dead=True), FakeMedia("VOk", 3, "video")
    svc = install_pool(vd, vo)
    set_routing({"video": ["VOk"]})
    img_dir = get_character_images_dir("Mara")
    img_dir.mkdir(parents=True, exist_ok=True)
    still = "Mara_2_still.png"
    (img_dir / still).write_bytes(png_bytes())
    svc.generate_from_input = lambda raw: (
        f"![Generated Image 1](/characters/Mara/images/{still}?user_id=u)")
    reply = skill.execute(json.dumps({"prompt": "a portrait", "action_prompt": "she waves",
                                      "agent_name": "Mara", "user_id": "u"}))
    meta = get_single_image_meta("Mara", still)
    check("F-V5 video link", "Mara_2_still.mp4" in reply, True)
    check("F-V5 stored animate_service ignored", len(vd.calls), 0)
    check("F-V5 image meta", (meta.get("animate_backend"), meta.get("animate_routing"),
                              meta.get("animate_fallback_from"), "animate_service" in meta),
          ("VOk", {"occasion": "video", "position": 1, "spec": "VOk"}, None, False))
    listed = get_character_image_metadata("Mara").get(still, {})
    check("F-V6 whitelist", (listed.get("animate_backend"),
                             (listed.get("animate_routing") or {}).get("occasion"),
                             "animate_fallback_from" in listed, "routing" in listed),
          ("VOk", "video", True, False))

    # -- F-V7/F-V8: Instagram animate -----------------------------------
    import threading as _threading
    from app.models.instagram import create_post, get_instagram_dir, load_image_meta
    from app.routes import instagram as ig_routes
    ig_dir = get_instagram_dir()
    ig_dir.mkdir(parents=True, exist_ok=True)
    (ig_dir / "ig_1.png").write_bytes(png_bytes())
    post = create_post("Mara", "ig_1.png", "a caption", image_prompt="a beach")
    vd, vo = FakeMedia("VDead", 0, "video", dead=True), FakeMedia("VOk", 3, "video")
    svc = install_pool(vd, vo)
    set_routing({"video": ["VDead", "VOk"]})
    _orig_thread = _threading.Thread
    _threading.Thread = _InlineThread
    try:
        ig_routes._animate_instagram_post_sync(post["id"], {"prompt": "waves"})
        m = load_image_meta("ig_1.png") or {}
        check("F-V7 routed", ((ig_dir / "ig_1.mp4").exists(), m.get("animate_backend"),
                              (m.get("animate_routing") or {}).get("position"),
                              (m.get("animate_fallback_from") or {}).get("intended_spec")),
              (True, "VOk", 2, "VDead"))
        ig_routes._animate_instagram_post_sync(post["id"], {"prompt": "waves",
                                                            "service": "VOk"})
        m = load_image_meta("ig_1.png") or {}
        check("F-V7 explicit: old marks dropped",
              (m.get("animate_backend"), m.get("animate_routing"),
               m.get("animate_fallback_from")), ("VOk", None, None))
        n = len(vo.calls)
        try:
            ig_routes._animate_instagram_post_sync(post["id"], {"prompt": "waves",
                                                                "service": "VDead"})
            check("F-V7 explicit dead", "no exception", 503)
        except HTTPException as e:
            check("F-V7 explicit dead", e.status_code, 503)
        try:
            ig_routes._animate_instagram_post_sync(post["id"], {
                "prompt": "waves", "service": "VOk",
                "loras": [{"name": "foreign.safetensors", "strength": 1.0}]})
            check("F-V7 explicit foreign LoRA", "no exception", 400)
        except HTTPException as e:
            check("F-V7 explicit foreign LoRA", e.status_code, 400)
        check("F-V7 nothing rendered by the refusals", len(vo.calls) - n, 0)
    finally:
        _threading.Thread = _orig_thread

    ig_routes.delete_instagram_animation(post["id"])
    m = load_image_meta("ig_1.png") or {}
    check("F-V8 instagram scrub", sorted(k for k in m if k.startswith("animate_")), [])
    remove_image_animation("Mara", still)
    m = get_single_image_meta("Mara", still)
    check("F-V8 gallery scrub", sorted(k for k in m if k.startswith("animate_")), [])


def _fake_store_mesh(files, used_rig, output_path, backend_name):
    """Stand-in for ImageService._store_mesh_files: writes the delivered
    bytes as "<output>.glb" and hands back one LOD stage."""
    out = Path(output_path).with_suffix(".glb")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(files[0]["blob"] if files else b"glb")
    return {"ok": True, "path": str(out), "texture_path": "", "format": "glb",
            "rig": used_rig, "filename": out.name, "backend": backend_name,
            "stages": [{"faces": 500, "blob": b"glb-low",
                        "filename": "x_500.glb", "format": "glb"}]}


def part_f_mesh():
    print("F) mesh")
    from app.core import location_model3d, model3d, model_refs, props
    from app.core.improvements.types import subjects
    from app.core.model_store import read_sidecar as read_model_sidecar
    from app.models import world
    tmp = Path(_TMP)
    (tmp / "src.png").write_bytes(png_bytes())
    service_mod.ImageService._store_mesh_files = staticmethod(_fake_store_mesh)

    mh = FakeMedia("MHum", 0, "mesh", rig="mixamo")
    md = FakeMedia("MDead", 0, "mesh", rig="none", dead=True)
    mo = FakeMedia("MOk", 2, "mesh", rig="none")
    svc = install_pool(mh, md, mo)
    set_routing({"mesh_object": ["MHum", "MDead", "MOk"]})
    res = svc.generate_mesh(str(tmp / "src.png"), str(tmp / "m.glb"), rig="none",
                            occasion="mesh_object")
    check("F-M1 routed mesh", (res.get("ok"), res.get("backend"),
                               (res.get("routing") or {}).get("position"),
                               (res.get("fallback_from") or {}).get("intended_spec")),
          (True, "MOk", 3, "MDead"))
    check("F-M1 meta", (res.get("routing"), res.get("fallback_from")),
          ({"occasion": "mesh_object", "position": 3, "spec": "MOk"},
           {"occasion": "mesh_object", "intended_spec": "MDead", "position": 2}))
    check("F-M1 calls (MHum, MDead, MOk)", (len(mh.calls), len(md.calls), len(mo.calls)),
          (0, 1, 1))

    res = svc.generate_mesh(str(tmp / "src.png"), str(tmp / "m2.glb"),
                            backend_glob="MHum", rig="none")
    check("F-M2 explicit wrong rig", (res.get("ok"), "'mixamo', 'none' is needed"
                                      in str(res.get("error"))), (False, True))
    check("F-M2 nothing rendered", len(mh.calls), 0)

    res = svc.generate_mesh(str(tmp / "src.png"), str(tmp / "m3.glb"),
                            backend_glob="MOk", rig="none")
    check("F-M3 explicit: no routing meta", (res.get("ok"), res.get("backend"),
                                             "routing" in res, "fallback_from" in res),
          (True, "MOk", False, False))

    n = len(mo.calls)
    res = svc.generate_mesh(str(tmp / "src.png"), str(tmp / "m4.glb"),
                            backend_glob="MDead", rig="none")
    check("F-M4 explicit cooling", (res.get("ok"), res.get("error")),
          (False, "mesh backend 'MDead' unavailable"))
    check("F-M4 MOk not asked", len(mo.calls) - n, 0)

    set_routing({"mesh_object": ["MOk"], "mesh_humanoid": ["MHum"]})
    res = svc.generate_mesh(str(tmp / "src.png"), str(tmp / "m5.glb"), rig="none")
    check("F-M5 rig none -> mesh_object", (res.get("routing") or {}).get("occasion"),
          "mesh_object")
    res = svc.generate_mesh(str(tmp / "src.png"), str(tmp / "m6.glb"))
    check("F-M5 no rig -> mesh_humanoid", (res.get("backend"),
                                           (res.get("routing") or {}).get("occasion")),
          ("MHum", "mesh_humanoid"))

    set_routing({"mesh_object": ["MOk"]})
    check("F-M6 object default", model3d.list_mesh_backends("none")["default"], "MOk")
    check("F-M6 building default (empty chain = cheapest available)",
          model3d.list_mesh_backends("none", occasion="mesh_building")["default"], "MOk")
    check("F-M6 subjects agree", (subjects.default_mesh_backend("mesh_object"),
                                  subjects.default_mesh_backend("mesh_building")),
          ("MOk", "MOk"))
    check("F-M6 rig-less: no default", model3d.list_mesh_backends()["default"], "")
    set_routing({"mesh_object": ["MHum"]})
    check("F-M6 nothing resolves", (model3d.list_mesh_backends("none")["default"],
                                    subjects.default_mesh_backend("mesh_object")),
          ("", ""))

    hd, mo = FakeMedia("HDead", 0, "mesh", rig="mixamo", dead=True), FakeMedia("MOk", 2, "mesh", rig="none")
    svc = install_pool(hd, mo)
    set_routing({"mesh_humanoid": ["HDead", "MOk"]})
    res = svc.generate_mesh(str(tmp / "src.png"), str(tmp / "m7.glb"), rig="mixamo")
    check("F-M7 stays in the rig", (res.get("ok"),
                                    "no backend available for mesh_humanoid" in str(res.get("error")),
                                    len(mo.calls)), (False, True, 0))

    # -- F-M8: the character mesh ----------------------------------------
    patched = {}

    def patch(mod, name, value):
        patched[(mod, name)] = getattr(mod, name)
        setattr(mod, name, value)
    char_dir = tmp / "m3d-char"
    patch(model3d, "required_rig", lambda name: "mixamo")
    patch(model3d, "find_ref_image", lambda name, kind, sig=None: tmp / "src.png")
    patch(model3d, "get_model3d_dir", lambda name: char_dir)
    patch(model3d, "get_model3d_options", lambda name: {})
    patch(model3d, "_ref_manifest", lambda src: {})
    for fn in ("_auto_retexture", "_auto_normalize"):
        patch(model3d, fn, lambda *a, **k: None)
    patch(model3d, "_attach_measurement", lambda meta, path: None)
    patch(model3d, "request_lod", lambda *a, **k: False)
    patch(model_refs, "enabled_tpose_views", lambda name: [])
    try:
        hd, ho = FakeMedia("HDead", 0, "mesh", rig="mixamo", dead=True), FakeMedia("HOk", 1, "mesh", rig="mixamo")
        install_pool(hd, ho)
        set_routing({"mesh_humanoid": ["HDead", "HOk"]})
        r = model3d.generate_for_current_outfit("Mara", force=True, signature="sig1")
        meta = read_model_sidecar(Path(r.get("path") or tmp / "none.glb"))
        check("F-M8a routed character mesh", (r.get("ok"), meta.get("backend"),
                                              meta.get("routing"), meta.get("fallback_from")),
              (True, "HOk", {"occasion": "mesh_humanoid", "position": 2, "spec": "HOk"},
               {"occasion": "mesh_humanoid", "intended_spec": "HDead", "position": 1}))

        hd, ho = FakeMedia("HDead", 0, "mesh", rig="mixamo", dead=True), FakeMedia("HOk", 1, "mesh", rig="mixamo")
        install_pool(hd, ho)
        r = model3d.generate_for_current_outfit("Mara", force=True, signature="sig1",
                                                prefer_cheapest=True)
        check("F-M8b auto hook: cheapest, explicit, no chain",
              (r.get("ok"), len(hd.calls), len(ho.calls)), (False, 1, 0))
        r = model3d.generate_for_current_outfit("Mara", force=True, signature="sig1",
                                                prefer_cheapest=True)
        meta = read_model_sidecar(Path(r.get("path") or tmp / "none.glb"))
        check("F-M8b auto hook on the next cheapest: no routing meta",
              (r.get("ok"), meta.get("backend"), "routing" in meta, "fallback_from" in meta),
              (True, "HOk", False, False))
    finally:
        for (mod, name), orig in patched.items():
            setattr(mod, name, orig)
        patched.clear()

    # -- F-M9: the building mesh -----------------------------------------
    loc = world.add_location("Tower", "A lone tower.")["id"]
    gal = world.get_gallery_dir(loc)
    gal.mkdir(parents=True, exist_ok=True)
    (gal / "front.png").write_bytes(png_bytes())
    patch(location_model3d, "request_low_tier", lambda *a, **k: None)
    try:
        bd, bo = FakeMedia("BDead", 0, "mesh", rig="none", dead=True), FakeMedia("BOk", 1, "mesh", rig="none")
        install_pool(bd, bo)
        set_routing({"mesh_building": ["BDead", "BOk"]})
        r = location_model3d._generate(loc, "front.png", "")
        full = location_model3d.find_building_model(loc)
        low = location_model3d.find_building_model(loc, tier=location_model3d.LOW_TIER)
        m_full = read_model_sidecar(full) if full else {}
        m_low = read_model_sidecar(low) if low else {}
        check("F-M9 routed building mesh", (r.get("ok"), m_full.get("backend"),
                                            m_full.get("routing"),
                                            (m_full.get("fallback_from") or {}).get("intended_spec")),
              (True, "BOk", {"occasion": "mesh_building", "position": 2, "spec": "BOk"},
               "BDead"))
        check("F-M9 the LOD stage is marked alike",
              (low != full, m_low.get("tier"), m_low.get("routing"), m_low.get("fallback_from")),
              (True, location_model3d.LOW_TIER, m_full.get("routing"), m_full.get("fallback_from")))
        check("F-M9 status default", location_model3d.get_building_info(loc).get("default"), "BOk")
    finally:
        for (mod, name), orig in patched.items():
            setattr(mod, name, orig)
        patched.clear()

    # -- F-M10: the prop mesh --------------------------------------------
    pid = props.create_prop(name="Barrel", description="an oak barrel")["id"]
    (props.prop_dir(pid, create=True) / props.SOURCE_NAME).write_bytes(png_bytes())
    for fn in ("_retexture_file", "_areas_after_landing", "_autofill_slots",
               "bake_surfaces"):
        patch(props, fn, lambda *a, **k: None)
    patch(props, "_extract_bbox", lambda *a, **k: None)
    try:
        bd, bo = FakeMedia("BDead", 0, "mesh", rig="none", dead=True), FakeMedia("BOk", 1, "mesh", rig="none")
        install_pool(bd, bo)
        set_routing({"mesh_object": ["BDead", "BOk"]})
        r = props._generate(pid, "", "", "", "", mesh_only=True)
        g = props.model_gallery(pid)
        full = g.find(props.DEFAULT_TIER) if g else None
        low = g.find(props.LOW_TIER, fallback=False) if g else None
        m_full = read_model_sidecar(full) if full else {}
        m_low = read_model_sidecar(low) if low else {}
        check("F-M10 routed prop mesh", (r.get("ok"), m_full.get("backend"),
                                         m_full.get("routing"),
                                         (m_full.get("fallback_from") or {}).get("intended_spec")),
              (True, "BOk", {"occasion": "mesh_object", "position": 2, "spec": "BOk"},
               "BDead"))
        check("F-M10 the LOD stage is marked alike",
              (low is not None and low != full, m_low.get("routing"), m_low.get("fallback_from")),
              (True, m_full.get("routing"), m_full.get("fallback_from")))
    finally:
        for (mod, name), orig in patched.items():
            setattr(mod, name, orig)
        patched.clear()


def part_g():
    print("G) dialog options")
    import inspect
    from fastapi import HTTPException
    from app.core import world_ops
    from app.routes import characters as characters_routes
    from app.routes import world as world_routes
    import app.core.config as cfg_mod
    gw = FakeBackend("Gw", 0, "natural")
    gw.mark_unhealthy("smoke", 300)
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"location": ["Gw", "Cloud"], "expression": ["Cloud"]})
    d = world_ops.build_imagegen_options("location")
    check("G1 resolved", (d.get("resolved"), d.get("via"),
                          [r["status"] for r in d.get("chain", [])]),
          ("Cloud", "chain", ["cooldown", "ok"]))
    check("G1 old keys gone", ("default_location" in d, "outfit_imagegen_default" in d),
          (False, False))
    check("G2 no occasion", "resolved" in world_ops.build_imagegen_options(), False)
    try:
        world_routes.get_imagegen_options(occasion="mesh_low", character="")
        check("G3 unknown occasion", "no exception", 400)
    except HTTPException as e:
        check("G3 unknown occasion", e.status_code, 400)

    def lora_scope(character, target):
        seen = []
        _real = cfg_mod.get_lora_options
        cfg_mod.get_lora_options = lambda name, lora_filter="": seen.append(name) or []
        try:
            characters_routes.get_outfit_lora_options(character_name=character,
                                                      target=target)
        finally:
            cfg_mod.get_lora_options = _real
        return seen[-1:] if seen else []

    check("G4 LoRA scope", lora_scope("", "render"), ["Cloud"])
    check("G5 no environment reads",
          ["os.environ" in inspect.getsource(f)
           for f in (world_ops.build_imagegen_options,
                     characters_routes.get_outfit_lora_options)],
          [False, False])

    from app.models.character import (get_character_images_dir, save_character_profile,
                                      save_character_skill_config,
                                      set_character_profile_image)
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile
    rule = FakeBackend("Rule", 1, "natural")
    own_txt = FakeBackend("Own-txt", 0, "natural")
    own_txt.category = "txt2img"
    own_ref = FakeBackend("Own-ref", 5, "natural")
    svc = install_pool(rule, own_txt, own_ref)
    rendered = []

    def _record(b, data, explicit):
        rendered.append(b.name)
        return service_mod.GenerationResult(text="ok", meta={}, gallery_character="Vela",
                                             files=[], skip_gallery=True)
    svc.generate_on_backend = _record
    set_routing({"expression": ["Rule"], "tpose": ["Rule"]})
    save_character_profile("Vela", {"name": "Vela", "appearance": "a short woman",
                                    "outfit_imagegen": {"workflow": "Own*"}},
                           create_new=True)

    def set_override(**fields):
        with keyed_lock("character_profile", "Vela"):
            prof = get_character_profile("Vela")
            prof["outfit_imagegen"] = {**(prof.get("outfit_imagegen") or {}), **fields}
            save_character_profile("Vela", prof)

    def render(occasion):
        rendered.clear()
        svc.generate_from_input(json.dumps({
            "prompt": "a variant", "input": "a variant", "agent_name": "Vela",
            "user_id": "", "set_profile": False, "skip_gallery": True,
            "auto_enhance": False, "occasion": occasion, "profile_only": True}))
        return rendered[-1:]

    check("G6 no reference: LoRA scope / render",
          (lora_scope("Vela", "render"), render("expression")),
          (["Own-txt"], ["Own-txt"]))
    img_dir = get_character_images_dir("Vela")
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "Vela_profile.png").write_bytes(png_bytes())
    check("G7 profile image set", set_character_profile_image("Vela", "Vela_profile.png"),
          True)
    check("G7 reference: LoRA scope / render",
          (lora_scope("Vela", "render"), render("expression")),
          (["Own-ref"], ["Own-ref"]))
    save_character_skill_config("Vela", "image_generation", {"instances": {
        "Own-txt": {"enabled": False}, "Own-ref": {"enabled": False}}})
    check("G8 switched off: LoRA scope / render",
          (lora_scope("Vela", "render"), render("expression")),
          (["Rule"], ["Rule"]))
    from app.core.auth_dependency import current_user_ctx

    def as_user(user, fn):
        tok = current_user_ctx.set(user)
        try:
            return fn()
        finally:
            current_user_ctx.reset(tok)
    admin = {"id": 1, "username": "demo", "role": "admin", "allowed_characters": []}
    d = as_user(admin, lambda: world_routes.get_imagegen_options(
        occasion="expression", character="Vela"))
    first = (d.get("chain") or [{}])[0]
    check("G8 options with character",
          (d.get("resolved"), first.get("source"), first.get("status")),
          ("Rule", "character", "disabled_for_character"))
    save_character_skill_config("Vela", "image_generation", {"instances": {}})
    set_override(tpose_workflow="Rule")
    check("G9 tpose match: LoRA scope / render",
          (lora_scope("Vela", "tpose"), render("tpose")), (["Rule"], ["Rule"]))
    set_override(tpose_workflow="")
    check("G9 tpose falls back to the workflow match: LoRA scope / render",
          (lora_scope("Vela", "tpose"), render("tpose")), (["Own-ref"], ["Own-ref"]))

    def render_profile():
        rendered.clear()
        svc.generate_from_input(json.dumps({
            "prompt": "a portrait", "input": "a portrait", "agent_name": "Vela",
            "user_id": "", "set_profile": True, "skip_gallery": True,
            "auto_enhance": False, "occasion": "profile"}))
        return rendered[-1:]
    check("G10 expression: options resolved / façade render",
          ([world_ops.build_imagegen_options("expression", "Vela").get("resolved")],
           render("expression")), (["Own-ref"], ["Own-ref"]))
    check("G10 profile: options resolved / façade render",
          ([world_ops.build_imagegen_options("profile", "Vela").get("resolved")],
           render_profile()), (["Own-txt"], ["Own-txt"]))

    def source_for(user):
        d = as_user(user, lambda: world_routes.get_imagegen_options(
            occasion="expression", character="Vela"))
        return (d.get("chain") or [{}])[0].get("source")
    check("G11 who may see the character's routing",
          [source_for(None),
           source_for({"id": 2, "username": "demo", "role": "user",
                       "allowed_characters": []}),
           source_for({"id": 2, "username": "demo", "role": "user",
                       "allowed_characters": ["Vela"]}),
           source_for(admin)],
          ["rule", "rule", "character", "character"])


def _track_row(task_id):
    from app.core.task_queue import get_task_queue
    conn = get_task_queue()._connect()
    try:
        row = conn.execute("SELECT status, error FROM tasks WHERE task_id=?",
                           (task_id,)).fetchone()
        return (row[0], row[1]) if row else None
    finally:
        conn.close()


def part_h():
    print("H) explicit pick checked before 'started'")
    from fastapi import HTTPException
    from app.core import world_ops
    from app.core.task_queue import get_task_queue
    from app.models import world
    from app.routes import world as world_routes
    loc = world.add_location("Quay", "A stone quay.")["id"]
    _tq = get_task_queue()
    starts, finishes = [], []
    _orig_start, _orig_finish = _tq.track_start, _tq.track_finish

    def _rec_start(*a, **kw):
        tid = _orig_start(*a, **kw)
        starts.append(tid)
        return tid

    def _rec_finish(task_id, error=""):
        finishes.append((task_id, error))
        return _orig_finish(task_id, error=error)
    _tq.track_start, _tq.track_finish = _rec_start, _rec_finish

    class _Req:
        def __init__(self, body):
            self._body = body

        async def json(self):
            return dict(self._body)

    async def _route(body):
        res = await world_routes.generate_gallery_image(loc, _Req(body))
        # The route fires the render as a task; let it run before the loop
        # closes (asyncio.run would cancel it).
        others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*others, return_exceptions=True)
        return res

    try:
        gw = FakeBackend("Gw", 0, "natural", dead=True)
        gw.mark_unhealthy("smoke", 300)
        cloud = FakeBackend("Cloud", 5, "keywords")
        install_pool(gw, cloud)
        set_routing({"location": ["Gw", "Cloud"]})
        try:
            res = asyncio.run(_route({"prompt": "x", "backend": "Gw"}))
            check("H1 gallery explicit dead -> 503", res, "HTTPException 503")
        except HTTPException as e:
            check("H1 gallery explicit dead -> 503",
                  (e.status_code, "'Gw'" in str(e.detail),
                   "no automatic fallback" in str(e.detail)), (503, True, True))
        check("H1 no track, nobody asked", (starts, len(gw.calls), len(cloud.calls)),
              ([], 0, 0))

        _real_core = world_ops.generate_gallery_image_core

        async def _gone(location_name, data):
            raise HTTPException(status_code=503, detail="backend 'Cloud' went away")
        world_ops.generate_gallery_image_core = _gone
        try:
            res = asyncio.run(_route({"prompt": "x", "backend": "Cloud"}))
        finally:
            world_ops.generate_gallery_image_core = _real_core
        tid = res.get("track_id") if isinstance(res, dict) else None
        check("H2 answered started", (res.get("status"), tid in starts), ("started", True))
        check("H2 track finished with the refusal", _track_row(tid),
              ("failed", "backend 'Cloud' went away"))

        starts.clear()
        finishes.clear()
        res = asyncio.run(_route({"prompt": "x", "backend": "Cloud",
                                  "loras": [{"name": "foreign.safetensors",
                                             "strength": 1.0}]}))
        tid = res.get("track_id")
        row = _track_row(tid) or ("", "")
        check("H3 core refusal on the track", (row[0], "does not associate" in (row[1] or "")),
              ("failed", True))
        check("H3 finished exactly once", [f[0] for f in finishes].count(tid), 1)

        # -- H4 character gallery regenerate ------------------------------
        from app.models.character import (add_character_image_prompt,
                                          get_character_images_dir,
                                          save_character_profile)
        from app.core import character_ops
        from app.routes import characters as characters_routes
        save_character_profile("Nell", {"name": "Nell", "appearance": "a tall woman"},
                               create_new=True)
        nd = get_character_images_dir("Nell")
        nd.mkdir(parents=True, exist_ok=True)
        (nd / "n1.png").write_bytes(png_bytes())
        add_character_image_prompt("Nell", "n1.png", "a portrait")
        gw = FakeBackend("Gw", 0, "natural", dead=True)
        gw.mark_unhealthy("smoke", 300)
        cloud = FakeBackend("Cloud", 5, "keywords")
        install_pool(gw, cloud)
        workers = []
        _real_worker = character_ops.regenerate_image_worker
        character_ops.regenerate_image_worker = lambda *a, **k: workers.append(a[4])
        starts.clear()
        try:
            try:
                characters_routes._regenerate_character_image_sync(
                    "Nell", "n1.png", {"backend": "Gw"})
                check("H4 regenerate explicit dead -> 503", "no exception", 503)
            except HTTPException as e:
                check("H4 regenerate explicit dead -> 503", e.status_code, 503)
            time.sleep(0.2)
            check("H4 no track, no worker", (starts, workers), ([], []))
            res = characters_routes._regenerate_character_image_sync(
                "Nell", "n1.png", {"backend": "Cloud"})
            time.sleep(0.2)
            check("H4 available pick starts", (res.get("status"), len(starts), workers),
                  ("started", 1, ["Cloud"]))
        finally:
            character_ops.regenerate_image_worker = _real_worker

        # -- H5/H6 prop routes --------------------------------------------
        from app.core import props
        mdead = FakeMedia("MDead", 0, "mesh", rig="none", dead=True)
        mdead.mark_unhealthy("smoke", 300)
        install_pool(gw, cloud, mdead)
        pid = props.create_prop(name="Barrel", description="an oak barrel")["id"]
        triggered = []
        _real_trigger = props.trigger_generation
        props.trigger_generation = lambda prop_id, **kw: triggered.append(kw) or True

        class _PropReq:
            def __init__(self, body):
                self._body = body
                self.headers = {"content-length": "1"}

            async def json(self):
                return dict(self._body)

        def regen(body):
            try:
                asyncio.run(world_routes.prop_regenerate(pid, _PropReq(body)))
                return "ok"
            except HTTPException as e:
                return e.status_code
        try:
            check("H5 dead image pick", (regen({"image_backend": "Gw"}), len(triggered)),
                  (503, 0))
            check("H5 mesh_only ignores the image pick",
                  (regen({"image_backend": "Gw", "mesh_only": True}), len(triggered)),
                  ("ok", 1))
            check("H5 dead mesh pick", (regen({"mesh_backend": "MDead"}), len(triggered)),
                  (503, 1))
            check("H5 available image pick",
                  (regen({"image_backend": "Cloud"}),
                   triggered[-1].get("image_backend_glob") if triggered else None),
                  ("ok", "Cloud"))
            n_before = len(props.list_props())
            try:
                world_routes._prop_generate_sync({"name": "Keg", "mesh_backend": "MDead"})
                check("H6 prop generate dead mesh pick", "no exception", 503)
            except HTTPException as e:
                check("H6 prop generate dead mesh pick", e.status_code, 503)
            check("H6 no prop record", len(props.list_props()) - n_before, 0)
        finally:
            props.trigger_generation = _real_trigger

        # -- H7 character mesh --------------------------------------------
        from app.core import model3d, model_refs
        mesh_calls = []
        _real_ref, _real_mtrig = model_refs.find_ref_image, model3d.trigger_generation
        model_refs.find_ref_image = lambda *a, **k: "tpose.png"
        model3d.trigger_generation = lambda *a, **k: mesh_calls.append(k) or True
        try:
            try:
                characters_routes.generate_character_model3d("Nell", backend="Cloud")
                check("H7 image backend as mesh pick", "no exception", 503)
            except HTTPException as e:
                check("H7 image backend as mesh pick", e.status_code, 503)
            check("H7 nothing triggered", mesh_calls, [])
        finally:
            model_refs.find_ref_image, model3d.trigger_generation = _real_ref, _real_mtrig

        # -- H9 profile-image dialog --------------------------------------
        def profile(body):
            try:
                asyncio.run(character_ops.generate_profile_image_core("Nell", _Req(body)))
                return ("no exception", "")
            except HTTPException as e:
                return (e.status_code, str(e.detail))
        gw = FakeBackend("Gw", 0, "natural", dead=True)
        gw.mark_unhealthy("smoke", 300)
        svc = install_pool(gw, FakeBackend("Cloud", 5, "keywords"))
        a = profile({"prompt": "a face", "backend": "Gw"})
        check("H9a explicit dead", (a[0], "'Gw'" in a[1], "no automatic fallback" in a[1]),
              (503, True, True))
        set_routing({"profile": ["Gw"]})
        b = profile({"prompt": "a face"})
        check("H9b chain dead", (b[0], b[1].startswith("no backend available for profile")),
              (503, True))
        answers = {}
        svc.generate_from_input = lambda raw: answers["next"]
        answers["next"] = "Error: Cloud: HTTP 500: gone"
        c = profile({"prompt": "a face"})
        check("H9c render failed", c, (500, "Cloud: HTTP 500: gone"))
        answers["next"] = "Error: Media generation is disabled for this world"
        d = profile({"prompt": "a face"})
        check("H9d media switch", d[0], 409)
        check("H9 English details", [("Kein" in x[1] or "fehlgeschlagen" in x[1])
                                     for x in (a, b, c, d)], [False] * 4)
    finally:
        _tq.track_start, _tq.track_finish = _orig_start, _orig_finish

    # -- H8 static: every route goes through the one helper ---------------
    import ast
    root = Path(__file__).resolve().parents[1]
    want = {
        "app/routes/world.py": ["generate_gallery_image", "_location_model3d_generate_sync",
                                "_room_model3d_generate_sync", "_prop_generate_sync",
                                "prop_regenerate", "_require_prop_picks"],
        "app/routes/prop_variants.py": ["prop_variant_generate"],
        "app/routes/characters.py": ["_regenerate_character_image_sync",
                                     "generate_character_model3d"],
        "app/routes/instagram.py": ["_regenerate_post_image_sync",
                                    "_animate_instagram_post_sync"],
        "app/routes/inventory.py": ["generate_item_image_route"],
    }
    helpers = {"require_explicit_backend", "require_explicit_backend_async",
               "_require_prop_picks"}
    missing, copies = [], []
    for rel, funcs in want.items():
        tree = ast.parse((root / rel).read_text())
        defs = {n.name: n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for fn in funcs:
            node = defs.get(fn)
            if node is None:
                missing.append(f"{rel}:{fn} (not found)")
                continue
            called = {(c.func.id if isinstance(c.func, ast.Name) else
                       c.func.attr if isinstance(c.func, ast.Attribute) else "")
                      for c in ast.walk(node) if isinstance(c, ast.Call)}
            own = helpers - ({"_require_prop_picks"} if fn == "_require_prop_picks" else set())
            if not called & own:
                missing.append(f"{rel}:{fn}")
            if "_wait_for_explicit_backend" in called:
                copies.append(f"{rel}:{fn}")
    check("H8 every listed route calls the helper", missing, [])
    check("H8 no per-route copy of the check", copies, [])


if __name__ == "__main__":
    part_a()
    part_c(*part_b())
    part_p()
    part_d()
    part_e()
    part_f_video()
    part_f_mesh()
    part_g()
    part_h()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
