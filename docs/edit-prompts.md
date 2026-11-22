# Edit prompts — one pass-through for every render with reference images

Status (2026-11-21, branch `eprompt`, base `7fc7c386d`): **Phase 1 and Phase 2 implemented** — C1–C9, C11 (only
`gate_attempts` itself and the cut texture use it) and the dialect column of the routing overview's DATA
(`_explain_one`). Live E2E on copies of Kai and Dario passed (§10). Open: C10 (the dialog's attempts list — needs a
frontend build), the overview's dialect column in `static/admin/settings.js`, C11's nine other loops, C12, C13 (an admin
action), Phases 3–4 (C14–C26). Phase 3 C14–C16 + C20 (the generate_on_backend path) landed on branch `chatimg` (§4).
Sources: `~/claude-out/prompt-syntax-research.md` (model conventions, §5 templates),
`~/claude-out/prompt-test-minimax/summary.md` + `prompts.json` (A/B, candidate N),
`~/claude-out/prompt-test/` (the short P-H3 winners now on `main`).

## 0. Decisions in one list

| # | Decision |
|---|---|
| D1 | One new module `app/imagegen/edit_prompt.py` owns everything about reference wording: the dialect table, the structured `EditPrompt`, one renderer per dialect, the pass-through normaliser. `prompt_adapters.reference_wording` / `PICTURE_REFERENCE_MODELS` / `uses_picture_references` are **deleted** (no shim). |
| D2 | The dialect is a **backend config field** `prompt_dialect` (`auto` / `picture_edit` / `picture_subject` / `image_tag` / `ordinal`), `auto` resolved from the model id through ONE table `edit_prompt.DIALECT_BY_MODEL`. |
| D3 | Producers write ONE canonical reference token `<ref N>` (N = slot number). No engine ever sees it: the normaliser converts it at `ImageBackend.generate`. Old spellings ("the first image", "image 2", `<Picture 2>`, `<image2>`, `@image2`) are recognised too, so the whole program works on day one. |
| D4 | Every producer that slots references also hands a **slot manifest** `params["reference_roles"]`. The slot ORDER stays where it is decided today (`PromptBuilder` slot plan, `scene_render`, `secret_diary`, `image_regenerate`, the fixed 1/2 of the cut texture); the manifest only reports it. |
| D5 | Request parameters (Qwen 2048 / cfg 1, the P-H3 upsampler off) stay on the **backend entry** (`width`/`height`, `extra_params`). The dialect only owns text, plus a lint (`edit_prompt.lint_backend`) that reports a deviating entry in the log and the routing overview. |
| D6 | Hand-tuned texts per dialect live in **sectioned Jinja files** (`## picture_edit` / `## picture_subject` / `## image_tag` / `## ordinal`), like the LLM task templates. The cut texture gets three of them (front plain, front decorated, back). A missing section falls back to `## ordinal`, rendered with the dialect's tokens. |
| D7 | Attempt 1 = chain entry 1, attempt 2 = chain entry 2 through the EXISTING `routing.retry_attempt` (A167). The cut texture and `footwear_source` join it; a small `routing.gate_attempts(n)` iterator replaces the nine hand-written loops. |
| D8 | Routing: `garment_cut_texture` → `['MiniMax-H3-Image', 'P-H3-Image']`, **only after** D6 has landed. Qwen2.1 stays out of that chain. Everything else unchanged until its own A/B (§9). |

## 1. Dialects (D2)

| Dialect | Token, N ≥ 2 refs | Token, 1 ref | Form the renderer writes | Auto for model id containing |
|---|---|---|---|---|
| `picture_edit` | `<Picture N>` | `<Picture 1>` | `Edit <Picture 1>. <result>. Keep <list> exactly as it is.` — the prompt always starts `Edit <Picture N>` so the node prepends nothing | `p-h3` |
| `picture_subject` | `<Picture N>` | `<Picture 1>` | one paragraph: `X in <Picture N> is <Subject K>` definitions → `The target image shows …` → one relation per subject (`partially/fully preserved`, `supplies the exact … transferred to`) → changed details | `minimax-h3` |
| `image_tag` | `<imageN>` | *the image* (no tag) | instruction first, each image's role named (canvas / material source), what stays as a positive `keep … unchanged` | `qwen2.1`, `qwen-image-2.1` |
| `ordinal` | `the first image`, `the second image` … | `the image` | plain prose (today's wording) — Flux, Z-Image, SD, every unknown backend | (default) |

- `DIALECT_BY_MODEL: tuple[tuple[str, str], ...]` in `edit_prompt.py` is the ONLY place a model name appears. Lower-case substring of `backend.model`, first hit wins.
- `edit_prompt.dialect_of(backend) -> str`: configured value if not `auto`, else the table, else `ordinal`.
- Config: `config_schema.py` backend entry gets `"prompt_dialect": {"type": "select", "choices": ["auto", "picture_edit", "picture_subject", "image_tag", "ordinal"], "default": "auto", "applicable_for": [<every type with ref_slot_count>]}`. It is read in `ImageBackend.__init__` as `self.prompt_dialect_setting` (env bridge `…PROMPT_DIALECT`), like `negative_prompt_setting`.
- Why a config field and not the model name alone: hub aliases are free names (`Qwen2.1-Turbo-View-Change`, the next fine-tune). The table covers every alias in the current instance, and the field lets the admin fix a new alias without a code change. Same pattern as `supports_negative_prompt=auto`.
- UI: the field renders in `/admin/settings` → Media Generation → backend editor (schema-driven). The **Routing overview** (`explain_image_routing`) shows the resolved dialect and the `lint_backend` notes per chain entry.

## 2. The structured object (D1, D6)

```python
# app/imagegen/edit_prompt.py
@dataclass(frozen=True)
class Ref:
    slot: int                 # 1-based = input_reference_image_N
    role: str                 # canvas | identity | room | item | material | composition | view_source
    label: str = ""           # "the flat sewing pattern of a T-shirt", "Kai"

@dataclass(frozen=True)
class Transfer:
    source: int               # slot
    prop: str                 # "the exact colour and fine weave"
    target: int               # slot (usually the canvas)

@dataclass
class EditPrompt:
    refs: list[Ref]
    result: str               # the finished result, never the action
    keep: list[str]           # what stays, by type/place ("every outline", "the white background")
    transfers: list[Transfer] = ()
    details: list[str] = ()   # extra sentences, may contain <ref N>
    sections: dict[str, str] | None = None   # hand-tuned texts per dialect (from a sectioned template)

    def render(self, dialect: str) -> str: ...

def from_template(path: Path, refs: list[Ref], **variables) -> EditPrompt
def render_ref(n: int, dialect: str, total: int) -> str        # the token table above
def dialect_of(backend) -> str
def lint_backend(backend) -> list[str]
def normalise(prompt: str, params: dict, backend) -> tuple[str, dict]   # §3
```

- **Renderers**: `_render_picture_edit`, `_render_picture_subject`, `_render_image_tag`, `_render_ordinal`. Each builds its form from `refs/result/keep/transfers/details`. When `sections` holds the dialect, that text wins (the tuned texts must reach the engine byte-identical). Otherwise the section `ordinal` is used, and otherwise the generic renderer.
- **Sectioned template** (`from_template`): a Jinja file under `shared/templates/image/` with `## <dialect>` headers, rendered in the existing `SandboxedEnvironment` + `StrictUndefined`. Each section gets a global `ref(n)` = `render_ref(n, <that section's dialect>, len(refs))`. A tuned text therefore never contains a foreign token.
- **Negation guard**: a tuned text says `without folds, …` on purpose (MiniMax N). `prompt_compose.compose` gets `keep_negations: bool = False`. Every `EditPrompt` producer passes `True`, so `split_negations` does not cut its subject. Edit occasions already have no negative fold (`occasions.folds_negative`).

## 3. The pass-through normaliser (D3) — the choke point

Hook: `app/imagegen/base.py` `ImageBackend.generate`. It replaces the `reference_wording` call (today :676-677) with `final_prompt, ep_meta = edit_prompt.normalise(final_prompt, params, self)`. It stays before the negative fold and before `prompt_limit.fit_prompt`, so shortening protects the new tokens.

`normalise` does, in order:
1. `slots` = the sorted N of `params["reference_images"]` keys `input_reference_image_N` (`input_mask` is not counted). **No slot → nothing to do**: the prompt comes back byte-identical, meta `{"refs": 0}`. Txt2img, mesh and video therefore stay untouched.
2. **Recognise mentions** with ONE regex table `_MENTIONS`, all mapped to a slot number:
   `<ref N>` · `<Picture N>` · `Picture N` · `<imageN>` · `@imageN` · `image N` / `picture N` / `reference image N` · `the (first|second|third|fourth|fifth) (image|picture|reference image|reference picture)` · `the reference image` / `the reference picture` (→ 1, only when exactly one slot). Vague phrases ("as the reference", "the person in the picture") are NOT guessed. Their producers are fixed instead (§8, rows P5/P6).
3. **Render** each mention with `render_ref(n, dialect, len(slots))`. Capitalisation follows the sentence start. With `image_tag` and one slot, "the first image" becomes "the image".
4. **Never invent**: a mention of N not in `slots` is never turned into a token, in any wording. The SENTENCE that holds it is dropped when the prompt still has at least one other sentence (this closes gap G3, `base_body.picture_edit_prompt` on a 1-slot backend); with `picture_edit` the prefix of step 5 counts as that other sentence, so the first pass already gives what a second pass would. A lone sentence loses only the clause (`,` / `;`) holding the mention, else only the mention with its leading preposition (`"Put the hat from <ref 3> on the first image."` → `"Put the hat on <image1>."`). The meta records each removed piece in `dropped`, note `unresolved`. Nothing else is ever added except the P-H3 prefix (step 5).
5. **Dialect checks**:
   - `picture_edit`: a prompt that does not start with `Edit <Picture \d+>` gets `Edit <Picture 1>. ` in front. That is exactly what the node would add, so the logged `final_prompt` is what the engine encodes. An `Edit the image.` lead-in, as a separate sentence, is removed first. A missing `Keep` sentence is only a note.
   - `picture_subject`: free text is not turned into subject form (that needs the structured object). Note `form: free_text`.
   - `image_tag`: note `role_missing` when ≥2 slots and no sentence names the canvas.
6. **Slot check**: `unused` = slots that are sent but never mentioned. This is a note only, because a person's slot often goes unnamed today.
7. **Idempotent**: running it on its own output changes nothing. That matters because a `PromptOverLimit` bounce runs `generate()` twice (`service.py:690-704`).
8. **Log**: `ep_meta = {"dialect", "dialect_source": "config|auto|default", "refs": [N…], "rewrites": k, "dropped": [...], "notes": [...], "roles": manifest}` is written to `log_meta["edit_prompt"]`, then into `logs/image_prompts.jsonl` (new key `edit_prompt` in `_log_generation`) and the image meta (`final_prompt` sits beside it already). `logger.info` gets one line per render with corrections.

Adjacent changes:
- `prompt_limit.REFERENCE_TOKEN` (`app/imagegen/prompt_limit.py:94`) becomes `edit_prompt.TOKEN_RE` (covers `<Picture N>`, `<imageN>`, `<Subject N>`, `<ref N>`, ordinals). The LLM shortening template `shared/templates/llm/tasks/image_prompt_shorten.md` names `<imageN>` and `<Subject N>` as tokens to keep.
- Backends keep the dict order for the request; `localai._collect_ref_images` and `openai_diffusion._collect_ref_bytes` sort by N (gap A4) so that `<ref N>` = position N.
- `garment_cut_texture._upsampler_on` moves into `lint_backend` (`picture_edit` + `use_prompt_upsampler` not `False`).

## 4. Persons → slot numbers in chat, photo and scene prompts (D4)

The order is already decided in ONE place per path. Only its result has to reach the text:

| Path | Who knows slot → who | Change |
|---|---|---|
| `service.generate_on_backend` (photo, instagram, story, video start frame, frame, profile; Agent > extra edit pictures > Room > others > Items) | `PromptBuilder._plan_qwen_slots` (`prompt_builder.py:1297`) | Rename it to the public `plan_reference_slots`. Call it BEFORE the prompt is rendered (today the render is at `service.py:2794`/`2882`, the slots at `:2977`), with `max_slots=backend.ref_slot_count`. Store `pv.slot_of = {name: N}`, `pv.room_slot`, `pv.item_slot_of`. `_resolve_qwen_slots` reuses that plan instead of planning again. |
| `image_regenerate.regenerate_image` (screenshot photo = slot 1, persons from 2, self-ref into the first free slot) | its own code `:471-501` | Fill the same `slot_of` from what it slotted. The stored original prompt gets `<ref N>` after the names through `edit_prompt.mark_persons(prompt, slot_of)` (whole word, first mention only). |
| `scene_render` (:480-543) / `secret_diary/presentation.py` | `ref_slot_of` | Write `<ref N>` instead of "reference image N" / "the first reference image". This touches the config defaults `scene_prompt_multi_ref` / `scene_prompt_only_background` (`config_schema.py:45-50`, `:942`) too. |

**Landed (change plan point 1, generate_on_backend path).** `PromptBuilder.plan_reference_slots` is the public
plan; `apply_slot_plan(pv, max_slots)` runs it BEFORE the render (right after `apply_exclusion_rules` with
auto_enhance, after the location on the caller-built path) and stores `reference_plan`, `person_slot` (person position
→ slot), `room_slot` and `item_slot_of` on `PromptVariables`; `resolve_reference_slots` sends that stored plan when its
slot count matches, and also returns the slot manifest `reference_roles`, which goes into `params["reference_roles"]`.
What the renderers write (only for what really sits in a slot of THIS backend):
- `_render_labeled_sections` (natural family): `- Kai (the person in <ref 3>), appearance, wearing …` — only the label
  at the start of the person's line is marked, never a later mention of the name; `Setting: the place shown in
  <ref 2>.` when the room is slotted (its location text is dropped then, as before); `Objects: the lamp from <ref 4>.`
  for slotted items; `Each person appears once.` as the last line of `Characters:` with two or more people, unless the
  style or the scene already says it.
- `render_z_image` (keywords): the same person marker, `the place in <ref N>`, `the lamp from <ref N>`, `each person
  appears once`.
- The portrait (`set_profile` with its current portrait as reference): the character block of the profile style starts
  `the same person as in <ref 1>, …` (`service._portrait_character`).
- The LLM enhancer (`image_prompt_enhance.md`) is told to keep every marker; an answer that lost one is replaced by the
  template prompt (`service._keep_reference_tokens`, logged).
- Every STORED prompt is token-free (`edit_prompt.strip_refs`): the gallery prompt, `last_enhanced_prompt` (Instagram's
  post prompt) and `template_prompt`, so a re-render plans its own slots. Only `final_prompt` keeps the engine's
  tokens.
- The normaliser notes `role_missing` only for an edit (no manifest, or a `canvas` / `view_source` / `material` role in it), not for
  a new composition.
Guard: `scripts/smoke_chat_photo_slots.py`. A/B on the local hub: `~/claude-out/chat-bilder/stufe1/`.
`pose_check.apply` (LLM rewrite of scene/event/photo) has to keep `<ref N>`, so its prompt template names the token. If a token is lost anyway, step 6 reports it as `unused`.

## 5. Request parameters per dialect (D5)

They stay on the backend entry, never in the dialect, because they are properties of the alias:
- `Qwen2.1` for textures: a SEPARATE entry (e.g. `Qwen2.1 2K`: `width`/`height` 2048, `extra_params {"cfg": 1}`). The chat entries keep 1024: 2048 costs about 4× (340-880 s), and that is not worth it for chat photos.
- `P-H3-Image`: `extra_params {"use_prompt_upsampler": false}` (it invented content when on).
- `MiniMax-H3-Image`: nothing (6 steps / cfg 1 fixed in the hub workflow; 2048² output).
- `lint_backend(b)` notes: `image_tag` with width < 2048 or cfg ≠ 1 ("info", not an error); `picture_edit` with the upsampler on ("warning"); `picture_subject` with an `extra_params` steps/cfg key ("warning: fixed by the model").

## 6. Cut texture (D6, D8) — three variants × four dialects

Files (replace `garment_cut_texture.md` / `_back.md`):
`shared/templates/image/garment_cut_texture_front_plain.md`, `…_front_decorated.md`, `…_back.md`, each with sections `## picture_edit`, `## picture_subject`, `## image_tag`, `## ordinal`.

| Variant / dialect | Text source | Tested |
|---|---|---|
| front_plain · picture_edit | current `main` plain prompt (F1 short), tokens via `ref()` | yes, P-H3 Kai/Dario/Tilda |
| front_decorated · picture_edit | current `main` decorated prompt (`front_place`) | yes, P-H3 Dario |
| back · picture_edit | current `main` back prompt on the zoomed template | yes, P-H3 |
| front_plain + front_decorated · picture_subject | candidate **N** front from `prompts.json` (`MiniMax:dario_front:N` / `kai_front:N`), the SAME text for both (N passed Kai plain and Dario decorated) | yes, MiniMax 2/2 |
| back · picture_subject | candidate **N** back (`MiniMax:dario_back:N`) | yes, but only on the UN-zoomed template, so the E2E (§10) must show it on the zoomed one |
| all three · image_tag | research §5e/§5f. The decoration clauses are dropped in front_plain, and front_decorated places the front print at `{{ front_place }}` | no (Qwen is not in the chain) |
| all three · ordinal | = the picture_edit text without the `Edit …` frame, with `ref()` → "the first image" | as today on other backends |

**The fitted family (group A, 2026-11-21).** Briefs, bra, gloves, tights and trousers use their own three files,
`garment_cut_texture_fitted_{front_plain,front_decorated,back}.md`, with the same four sections
(`garment_cut_texture.PROMPT_SETS["fitted"]`, picked by `prompt_family(kind)`). The text is the top's tested wording.
The decorated front names the MAIN pieces (`main`, `main_count`, `main_names` from `main_words`: "the two largest
shapes are the right front leg panel and the left front leg panel") instead of `front_place`. It also uses
`a_piece` ("a pair of gloves") and lists the small pieces as plain fabric. Their sha keys the fitted atlases only;
the top's `PROMPT_SHA` is unchanged.

- Variables: `piece`, `front_place` (exists), plus the restored `pieces` / `layout` / `sleeves` that N needs. `prompt_pieces` / `layout_words` / `_pattern_order` come back from `3a6718c78^:app/core/garment_cut_texture.py:256-310` (only the subject sections use them).
- `garment_cut_texture.render_prompt(*, side, decorated, front_place, piece, pieces, layout, dialect)` returns `EditPrompt.from_template(...).render(dialect)` with `refs=[Ref(1,"canvas",…), Ref(2,"material",…)]`.
- The call moves INTO `_routed_render._render(b)`: `dialect = edit_prompt.dialect_of(b)`. Attempt 2 on another backend thus gets its own dialect. `compose(..., keep_negations=True)`.
- `PROMPT_SHA` = md5 over the three files (all sections), so a changed section re-runs the job. `record.jobs[job]` gets `dialect`.
- Fully generic: any other producer uses `EditPrompt` the same way (a sectioned file, or `refs/result/keep/transfers` for the generic renderer).

## 7. Attempt 2 on chain entry 2 (D7)

Mechanism (exists): `routing.retry_attempt(n)` aims `run_routed` at the n-th USABLE entry (clamped to the last). `route_meta` writes `attempt_entry {attempt, aimed_position, position}`. Landing on the aimed entry is not `fallback_from`; landing behind it is. An explicit pick ignores the attempt.

- New `routing.gate_attempts(n: int) -> Iterator[int]`. It yields 1..n, each inside `retry_attempt`, and stops at the caller's `break`. It replaces the loops in `garment_images.py:987-992`/`:1905-1917`, `garment_beard.py:256`, `garment_template_views.py:301`, `shell_base_views.py:233`, and `base_body.py:1450`/`:3401`/`:4538`/`:4547`, with the same behaviour.
- **Cut texture** (`garment_cut_texture.generate`, the job loop): `for attempt in gate_attempts(CUT_ATTEMPTS=2)`:
  - `_routed_render` → `post_job`; break on `"ready"`.
  - A gate rejection → attempt 2. Failures without attempt 2: `BackendBusyError`, `MediaGenerationDisabled`, `NoRouteError`, and a `BackendFailedError` after `run_routed`'s own re-runs.
  - Seed: `seed + 1000 * (attempt - 1)`, because a single-entry chain clamps attempt 2 onto the same backend and the same seed would give the same answer.
  - Each attempt is recorded in `record.jobs[job]["attempts"] = [{attempt, backend, dialect, routing: route_meta(route), state, reason, metrics}]`, and the job's top-level fields are those of the last attempt. The raw answer goes to `.raw_{job}.a{n}.png`, so "Use this answer" can choose either attempt (`use_answer(…, attempt=n)`).
  - `_plan_one` / `job_plan` count `max` = 2 × jobs, so the Build button count stays honest. A manual re-run starts at attempt 1 again.
  - The module doc ("ONE attempt per click") is updated.
- **footwear_source** `_edit` (:408-431): today the attempt number only changes the seed. It switches to `gate_attempts(EMPTY_ATTEMPTS)`, the same rule.
- Improvements `fallback_rerender` reads only gallery/profile metas. Cut records keep `route_meta` as information (no change).

## 8. Change plan — every place the new prompts touch

Phases; each one ends with its smokes green.

**Phase 1 — core (no visible change except Qwen tokens)**
| ID | File / function | Change |
|---|---|---|
| C1 | new `app/imagegen/edit_prompt.py` | table, `Ref/Transfer/EditPrompt`, renderers, `normalise`, `lint_backend`, `TOKEN_RE`, `mark_persons` |
| C2 | `app/imagegen/base.py:676` `generate` | `normalise` instead of `reference_wording`; `edit_prompt` into `log_meta` / `_log_generation` |
| C3 | `app/core/prompt_adapters.py:30-62` | delete `PICTURE_REFERENCE_MODELS`, `_PICTURE_WORDING`, `uses_picture_references`, `reference_wording` |
| C4 | `app/imagegen/prompt_limit.py:94` + `llm/tasks/image_prompt_shorten.md` | `TOKEN_RE` |
| C5 | `app/core/config_schema.py` backend entry; `base.py __init__`; `routing._explain_one` | `prompt_dialect` field, overview shows dialect + lint |
| C6 | `backends/localai.py:146`, `backends/openai_diffusion.py:214` | sort refs by N |
| C7 | `app/core/prompt_compose.py:301` | `keep_negations` |

**Phase 2 — cut texture + attempts**
| C8 | `shared/templates/image/garment_cut_texture_{front_plain,front_decorated,back}.md` | 3 × 4 sections (§6) |
| C9 | `app/core/garment_cut_texture.py` | `render_prompt(dialect)`, restored `prompt_pieces`/`layout_words`, prompt inside `_render(b)`, `PROMPT_SHA`, attempts, `.raw_{job}.a{n}.png`, `_plan_one` ×2, `_upsampler_on` → lint |
| C10 | `frontend` cut-texture dialog (Figure tab) | per job: attempts list (backend, dialect, gates), "Use this answer" per attempt; `npm run build` |
| C11 | `app/imagegen/routing.py` | `gate_attempts`; the 9 callers of §7 switch to it |
| C12 | `app/core/footwear_source.py:408` | `gate_attempts` |
| C13 | instance config (admin UI, not code) | chain `garment_cut_texture` = `MiniMax-H3-Image, P-H3-Image` after C8/C9 |

**Phase 3 — persons get slot numbers**
| C14 | `app/core/prompt_builder.py:1297` | `plan_reference_slots` public, `slot_of` on `PromptVariables` |
| C15 | `app/imagegen/service.py:2758-2980` `generate_on_backend` | plan slots before render; `reference_roles`; `_with_extra_reference_prompt` stays (the normaliser covers the rest) |
| C16 | `app/core/prompt_adapters.py:189`/`:262` renderers | `(<ref N>)` after names, room/item slots |
| C17 | `app/skills/image_regenerate.py:440-536`, `app/core/scene_photo.py:46-88` | `slot_of`, `mark_persons`; `_SCREENSHOT_SENTENCE` → `<ref 1>` |
| C18 | `app/core/scene_render.py:51/59/493`, `config_schema.py:45-50/:942`, `plugins/secret_diary/presentation.py:139` (pack, private repo) | `<ref N>` |
| C19 | `app/imagegen/pose_check.py` template | keep `<ref N>` |
| C20 | `plugins/take_photo/skill.py:99`, `plugins/instagram/skill_post.py:451`, `story_engine.py:401`, `routes/story.py:580`, `video_generation_skill.py:140` | nothing, they inherit C15/C16 (a smoke checks them) |

**Phase 4 — the remaining edit producers say `<ref N>` (wording only)**
| C21 | `app/core/base_body.py:160-181` (DRAFT/BASE_VIEW_PROMPTS), `:226/:228` "as the reference", `:238-241` "the person in the picture", `:3809/:3815` EDIT_SECOND_PICTURE / EDIT_FROM_SECOND_PICTURE, `:2122/:2126` DRESS_KEEP | `<ref 1>`/`<ref 2>`. `picture_edit_prompt` relies on normaliser step 4 on 1-slot backends |
| C22 | `app/core/model_refs.py:105/:225`, `:139-193` (views) | "as <ref 1>", "the same figure in <ref 1> …" |
| C23 | `garment_beard.py:46`, `garment_template_views.py:44/50/160`, `shell_base_views.py:50-53`, `base_skin.py:102/104`, `footwear_source.py:96`, `expression_regen` member prompts, `full_body_reference.py` | `<ref 1>` where the image is meant; texts that do not name it stay |
| C24 | `config.py:642/647/657/662/1032` use-case styles "the reference image" | `<ref 1>` |
| C25 | `props.py:6644`, `world_ops.py:3911-3944/:4204`, `event_images.py:309` | a short role sentence through `EditPrompt` (back/side view of `<ref 1>`; time variant of `<ref 1>`; event in the place of `<ref 1>`) — each needs its own A/B before it goes live |
| C26 | the anatomy pack's base-front cleanup text (private repo) | wording check only there |

Not affected (no prompt or no reference): `generate_video`, `upscale_image`, `generate_face_retexture`, `generate_hair`, `generate_mesh*`, `generate_rig`, `openai_motion_transition`, every txt2img path.

## 9. Routing recommendation (D8)

| Occasion | Today | Recommendation | Why |
|---|---|---|---|
| `garment_cut_texture` | `P-H3-Image` | **`MiniMax-H3-Image`, `P-H3-Image`** (after Phase 2) | Only N passed 4/4 with fabric structure and no invented motifs; P-H3 invented content in 3 of 4 production answers, but it is the most exact in colour and placement, which makes it the right attempt 2. ~70 s vs 43-102 s. |
| `garment_view`, `timevariant` | P-H3 first | unchanged | not tested with MiniMax; already 2 entries |
| `footwear_empty` | `Qwen2.1 Turbo` | add `P-H3-Image` as entry 2 | attempt 2 needs a second entry (C12); 1 slot |
| `photo`, `instagram`, `scene_view`, `profile`, `expression`, `tpose*`, `base_*`, `outfit_*` | Qwen2.1 family | unchanged **until Phase 3**, then an A/B Qwen vs MiniMax on chat photos (16 slots, ~3× faster). Never switch blind. | the person ↔ slot naming is the precondition of any fair comparison |
| `location`, `event`, `prop`, `regenerate`, `frame` | Flux2-9B | unchanged; dialect `ordinal` | no dialect issue |
| Qwen2.1 at 2048 | — | only as its own entry for texture jobs, never for chat | 4× time |

## 10. Test plan

Smokes (standalone, expected values derived by hand in the docstring, no server, no world DB):
1. `scripts/smoke_edit_prompt_dialects.py`. Hand-derived cases, e.g. with 2 slots `"Put the hat from the second image on the first image."`:
   - picture_edit → `"Edit <Picture 1>. Put the hat from <Picture 2> on <Picture 1>."`
   - picture_subject → tokens only + note `free_text`
   - image_tag → `"Put the hat from <image2> on <image1>."`
   - ordinal → unchanged

   Further cases:
   - 1 slot with image_tag: `"the first image"` → `"the image"`.
   - `"from <ref 3>"` with 2 slots: the sentence is dropped, `dropped` has 1 entry.
   - The lone unresolved sentence on all four dialects (and "the third image" spelled out): no token of a missing slot in any output, each output idempotent.
   - `<ref` never appears in any output.
   - `normalise(normalise(x)) == normalise(x)` for every case.
   - 0 slots: byte-identical.
   - `"Edit the image. …"` with picture_edit gets a single prefix.
2. `scripts/smoke_edit_prompt_table.py`: `dialect_of` for every model id of the current routing table (`P-H3-Image`→picture_edit, `MiniMax-H3-Image`→picture_subject, `Qwen2.1`/`Qwen2.1-Turbo`→image_tag, `Flux2-9B…`→ordinal). An explicit field beats auto. `lint_backend` on stub entries. A grep guard: no model-id literal from the table appears in `app/` outside `edit_prompt.py`.
3. `scripts/smoke_cut_texture_dialects.py`: Dario/Kai fixture islands. Checks:
   - `picture_subject` front = the `prompts.json` N string, quoted in the docstring, byte for byte.
   - `picture_edit` = the main winners with `<Picture N>`.
   - Every section renders under `StrictUndefined`.
   - `compose(keep_negations=True)` keeps "without folds".
   - `PROMPT_SHA` changes when a single section changes.
4. `scripts/smoke_cut_texture_attempts.py`: stub `run_routed`/`post_job`. Checks:
   - Attempt 1 rejected → attempt 2 aimed at position 2: `attempt_entry {2,2,2}`, no `fallback_from`, a different dialect in the record, `.raw_front.a2.png`.
   - Busy → no attempt 2.
   - Single-entry chain → same backend, seed + 1000.
   - `job_plan` max = 2 × jobs.
5. `scripts/smoke_chat_photo_slots.py`: `generate_on_backend` with a capture backend (P-H3 dialect). Agent Mia + room + Kai → `final_prompt` contains `Mia (<Picture 1>)`, `the room in <Picture 2>`, `Kai (<Picture 3>)`, matching `params["reference_images"]` order. A 1-slot backend → only Mia gets a token. The existing `smoke_image_routing_runtime.py` cases 1-11 stay green.
6. Existing guards: `smoke_imports_resolve.py`, `smoke_garment_cut_texture.py`, `smoke_cut_texture_*`, `smoke_image_routing_*`.

Live E2E (local hub only: `MiniMax-H3-Image`, `P-H3-Image`, Iris upscaler; never another backend):
- `scripts/e2e_cut_texture.py` gets `--chain MiniMax-H3-Image,P-H3-Image`. This is an in-process override of `image_generation.routing.garment_cut_texture`; the recorder still fails the run on any config write. Its allowlist grows to these two aliases + the upscaler.
- Runs on COPIES (the script's temp STORAGE_DIR) of Dario, Tilda and Kai:
  1. normal Build: every job lands on MiniMax, `dialect = picture_subject`, `image_prompts.jsonl` `final_prompt` starts with "The flat sewing pattern", gates pass, the back on the zoomed template (the untested case);
  2. `--reject-attempt 1` (the gate of attempt 1 is stubbed to "rejected"): attempt 2 runs on P-H3, `final_prompt` starts `Edit <Picture 1>.`, `attempt_entry.position == 2`, no `fallback_from`, job count = announced max.
- Budget: 3 characters × ≤2 jobs × 2 runs ≤ 12 image jobs + upscales.
- Output sheets go to `~/claude-out/edit-prompts/`.

## 11. Open points

- **Live result 2026-11-21** (`scripts/e2e_cut_texture.py --chain MiniMax-H3-Image,P-H3-Image`, copies): Kai with
  `--reject-attempt 1` -> attempt 1 MiniMax `picture_subject` (its answer passed the gates; the rejection was forced),
  attempt 2 P-H3 `picture_edit`, `attempt_entry {2, 2, 2}`, no `fallback_from`, 3 image jobs (upscale + 2). Dario ->
  MiniMax passes on attempt 1: the chest embroidery on the front panel, sleeves plain fabric, no invented motif. Both
  backs are plain (fabric fill, no back job) — the MiniMax back on the zoomed template is still untested.

- MiniMax N back on the zoomed template is untested (E2E run 1 decides). If it fails: the MiniMax back job uses the un-zoomed template (`job_frame` gets a per-dialect switch), not a new text.
- Qwen `image_tag` cut texts are research drafts, untested. They are used only if someone puts Qwen into the chain.
- The detail gate does not catch small invented emblems (summary "Urteil"). That is a separate topic; MiniMax first reduces the risk but does not close it.
- The "Übersicht fertige/offene Schnittmuster" from the user's request is not part of this design step.
