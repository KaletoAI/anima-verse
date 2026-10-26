"""Central prompt-builder pipeline for image generation.

Consolidates the prompt logic that used to be spread over chat.py,
image_generation_skill.py and image_regenerate.py into one pipeline.

Flow:
    1. detect_persons()        - detect persons, assign neutral actors
    2. collect_context()       - collect context variables per actor
    3. apply_exclusion_rules() - workflow-dependent exclusion rules
    4. assemble_prompt()       - assemble the final prompt
    5. resolve_reference_slots() - fill the reference-image slots
"""
import re
from dataclasses import dataclass, field

from app.core.timeutils import game_time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.models.character import (
    get_character_config,
    get_effective_activity,
    get_effective_pose_key,
    get_character_current_feeling,
    get_character_current_location,
    get_character_current_room,
    get_character_images_dir,
    get_character_personality,
    get_character_profile,
    get_character_profile_image,
    list_available_characters)
from app.core.outfit_renderer import render_outfit
from app.models.account import (
    get_active_character,
    get_user_appearance,
    get_user_gender,
    get_user_profile_image,
    get_user_images_dir)
from app.models.world import get_background_path, get_location, get_room_by_id

logger = get_logger("prompt_builder")


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class Person:
    """A detected person."""
    name: str                   # Character-Name (z.B. "Kira", "Kai")
    appearance: str             # Appearance text from the profile.
    gender: str                 # "female", "male", ""
    actor_label: str = ""       # Set to the name (formerly Woman1/Man1).
    is_agent: bool = False      # Whether this is the generating character.
    is_user: bool = False       # Whether this is the user.


@dataclass
class PromptVariables:
    """Separate prompt variables collected by the pipeline."""
    # Per person (1-based slot index)
    persons: List[Person] = field(default_factory=list)
    prompt_persons: Dict[int, str] = field(default_factory=dict)    # {1: "Woman1, blonde hair..."}
    prompt_outfits: Dict[int, str] = field(default_factory=dict)    # {1: "Woman1 is wearing red dress"}
    ref_images: Dict[int, str] = field(default_factory=dict)        # {1: "/path/to/image.png"}

    # Items selected as props in the room-items panel
    # items: [{"id": "...", "name": "chair", "description": "...", "image": "/path"}]
    items: List[Dict[str, Any]] = field(default_factory=list)

    # Global variables
    prompt_mood: str = ""
    prompt_activity: str = ""
    prompt_location: str = ""
    ref_image_room: str = ""        # Room reference

    # Internal variables for separated-prompt workflows
    prompt_pose: str = ""
    prompt_expression: str = ""

    # LLM-generated scene prompt
    scene_prompt: str = ""

    # Additions
    prompt_style: str = ""           # Style adjectives
    negative_prompt: str = ""
    personality: str = ""           # Profile image only
    profile_image_hint: str = ""    # Profile image hint

    # Context flags
    photographer_mode: bool = False
    is_selfie: bool = False
    set_profile: bool = False
    profile_reference: str = ""     # Explicit current portrait, independent of person detection
    no_person_detected: bool = False


@dataclass
class EntryPointConfig:
    """Per-entry-point configuration: which variables are populated."""
    name: str
    auto_enhance: bool = True
    include_persons: bool = True
    include_outfit: bool = True
    include_mood: bool = True
    include_activity: bool = True
    include_location: bool = True
    show_dialog: bool = False

    @classmethod
    def chat(cls) -> "EntryPointConfig":
        return cls(name="chat")

    @classmethod
    def instagram(cls) -> "EntryPointConfig":
        return cls(name="instagram")

    @classmethod
    def story(cls) -> "EntryPointConfig":
        return cls(name="story", auto_enhance=False, include_mood=False,
                   include_activity=False, include_outfit=False)

    @classmethod
    def outfit_variant(cls) -> "EntryPointConfig":
        return cls(name="outfit_variant", include_location=False)

    @classmethod
    def outfit_change(cls) -> "EntryPointConfig":
        return cls(name="outfit_change")

    @classmethod
    def dialog_recreation(cls) -> "EntryPointConfig":
        return cls(name="dialog_recreation", show_dialog=True)

    @classmethod
    def dialog_outfit(cls) -> "EntryPointConfig":
        return cls(name="dialog_outfit", show_dialog=True,
                   include_mood=False, include_activity=False, include_location=False)

    @classmethod
    def dialog_location(cls) -> "EntryPointConfig":
        return cls(name="dialog_location", show_dialog=True,
                   include_persons=False, include_outfit=False,
                   include_mood=False, include_activity=False)

    @classmethod
    def dialog_profile(cls) -> "EntryPointConfig":
        return cls(name="dialog_profile", show_dialog=True,
                   include_outfit=False, include_mood=False,
                   include_activity=False, include_location=False)


# ---------------------------------------------------------------------------
# Pronomen-Listen
# ---------------------------------------------------------------------------

_AGENT_PRONOUNS = [
    " ich ", " mir ", " mich ", " mein ", " meinem ", " meiner ",
    " meinen ", " meine ", " i am ", " my ", " me ", " myself ",
]

_USER_PRONOUNS = [
    " du ", " dir ", " dich ", " dein ", " deinem ", " deiner ",
    " deinen ", " deine ", " you ", " your ",
]

SELFIE_KEYWORDS = (
    "selfie", "selbstportrait", "self-portrait", "self portrait",
    "foto von mir", "photo of me", "bild von mir", "picture of me")


def is_photographer_mode(character_name: str) -> bool:
    """Read photographer_mode from character config, accepting string/bool values."""
    if not character_name:
        return False
    cfg = get_character_config(character_name) or {}
    raw = cfg.get("photographer_mode", False)
    if isinstance(raw, str):
        return raw.strip().lower() in ("true", "1", "yes")
    return bool(raw)


def detect_selfie(text: str) -> bool:
    """Whether the text contains an explicit selfie term."""
    if not text:
        return False
    return any(kw in text.lower() for kw in SELFIE_KEYWORDS)

_CAMERA_KEYWORDS = (
    "camera", "photograph", "photo shoot", "taking photo", "taking a photo",
    "taking picture", "snap a photo", "lens", "shutter", "viewfinder",
    "tripod", "flash", "canon", "nikon", "sony alpha", "ready for shot",
    "holding camera", "adjusting light", "behind the camera", "shoots",
    "kamera", "fotografier", "foto mach", "objektiv", "ausloeser")

_COMMON_WORDS = frozenset({
    "with", "from", "that", "this", "have", "been", "were", "they",
    "their", "them", "will", "would", "could", "should", "about",
    "into", "over", "after", "before", "between", "under", "through",
    "each", "other", "some", "than", "then", "also", "just", "like",
    "very", "much", "more", "most", "long", "young", "looks", "looking",
    "eine", "einen", "einem", "einer", "eine", "sind", "sein", "wird",
    "haben", "kann", "auch", "noch", "oder", "aber", "wenn", "sich",
    "nicht", "mehr", "nach", "schon", "noch",
})

_PERSON_KEYWORDS = (
    "woman", "man", "girl", "boy", "person", "people", "frau", "mann",
    "mädchen", "junge", "portrait", "face", "gesicht", "selfie",
    "intern", "she ", "he ", "her ", "his ")


# ---------------------------------------------------------------------------
# Person description — the ONE composition
# ---------------------------------------------------------------------------

# Words that describe a FACE. A render seen from behind (the T-pose back
# view) drops every appearance segment that names one (user decision
# 2026-09-24): each facial word pulls a face into the picture, and the model
# answers by turning the head — or the whole upper body — toward the camera.
# The appearance is free text, so this works per comma/sentence segment: a
# segment like "long hair framing her face" goes as a whole.
_FACE_TERMS_RE = re.compile(
    r"\b(?:faces?|faced|facial|eyes?|eyebrows?|brows?|eyelash(?:es)?|"
    r"lash(?:es)?|eyeliner|eyeshadow|make-?up|lipstick|lips?|mouth|nose|"
    r"cheeks?|cheekbones?|chin|jaw(?:line)?|forehead|teeth|smile|dimples?|"
    r"pupils?|iris(?:es)?|gaze)\b",
    re.IGNORECASE)


def strip_face_terms(text: str) -> str:
    """Drops every comma/semicolon/sentence segment of ``text`` that names a
    facial feature; the rest is re-joined with commas."""
    kept = [seg.strip() for seg in re.split(r"[,;.]", text or "")
            if seg.strip() and not _FACE_TERMS_RE.search(seg)]
    return ", ".join(kept)

def person_description(name: str, *,
                       include_outfit: bool = False,
                       apply_state_modifiers: bool = True,
                       back_view: bool = False,
                       mesh_input: bool = False,
                       body_profile: Optional[Dict[str, Any]] = None,
                       include_exposed: bool = True,
                       neutral_state: bool = False) -> str:
    """THE text description of a person for image prompts.

    Every path that describes a person — PromptBuilder (chat images,
    expression variants, outfit images), the scene render / scene photo
    (``include_outfit=True``) and every prompt PREVIEW — goes through this
    one function, so a preview always shows what the render would send.

    Layers: appearance (profile tokens resolved, whitespace collapsed)
    → body-slot suffix (species packages; exposed fragments only while
    uncovered, and in a ``back_view`` render only from slots visible from
    behind; left out with ``include_exposed=False``) → optionally the
    worn-outfit line → triggered
    image_modifier directives over the composed text (with the outfit
    included, a replacement may rewrite outfit text too — scene-render
    semantics) → in a ``back_view`` render, every segment naming a facial
    feature dropped (``strip_face_terms``)."""
    from app.models.character import get_character_appearance, get_character_profile
    from app.models.character_template import get_template, resolve_profile_tokens
    appearance = ((body_profile or {}).get("character_appearance", "")
                  if body_profile is not None else get_character_appearance(name)) or ""
    if appearance and "{" in appearance:
        try:
            profile = body_profile if body_profile is not None else get_character_profile(name)
            tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
            appearance = resolve_profile_tokens(
                appearance, profile, template=tmpl, target_key="character_appearance"
            )
        except Exception:
            pass
    appearance = " ".join(appearance.split())
    # Body slots (species packages, plan-body-slots.md): always/covered
    # fragments extend the general person description, exposed fragments
    # render only while uncovered. Also sent with reference images (F3).
    # Empty without species packages — safe no-op.
    try:
        from app.core.body_slots import appearance_suffix
        suffix = appearance_suffix(name, profile=body_profile, back_view=back_view,
                                   mesh_input=mesh_input, include_exposed=include_exposed,
                                   neutral_state=neutral_state)
    except Exception:
        suffix = ""
    if suffix:
        appearance = f"{appearance}, {suffix}" if appearance else suffix
    if include_outfit:
        try:
            from app.core.outfit_renderer import render_outfit
            # render_outfit 'full' already carries its own 'wearing:' prefix
            outfit = (render_outfit(character_name=name, mesh_input=mesh_input).get("full", "") or "").strip()
        except Exception:
            outfit = ""
        if outfit:
            appearance = f"{appearance}, {outfit}" if appearance else outfit
    # Triggered states rewrite/extend the description afterwards
    # (image_modifier replacements + additive fragments).
    if apply_state_modifiers:
        try:
            from app.core.prompt_filters import apply_image_modifiers
            appearance = apply_image_modifiers(name, appearance)
        except Exception:
            pass
    # Last, so a state modifier cannot bring a face back ("flushed cheeks").
    if back_view:
        appearance = strip_face_terms(appearance)
    return appearance or ""


# ---------------------------------------------------------------------------
# PromptBuilder
# ---------------------------------------------------------------------------

class PromptBuilder:
    """Central pipeline for building image-generation prompts."""

    def __init__(self, character_name: str, *,
                 apply_state_modifiers: bool = True,
                 back_view: bool = False,
                 mesh_input: bool = False,
                 body_profile: Optional[Dict[str, Any]] = None,
                 neutral_state: bool = False):
        self.user_id = ""
        self.character_name = character_name
        # State-triggered image_modifier directives rewrite the person
        # description. Neutral cache renders (outfit-batch pre-warm) turn
        # this off — their cache key deliberately carries no state.
        self.apply_state_modifiers = apply_state_modifiers
        # A render seen from behind (the T-pose back view) keeps only the
        # exposed body-slot fragments of slots declared visible from behind.
        self.back_view = back_view
        self.mesh_input = mesh_input
        self.body_profile = body_profile
        self.neutral_state = neutral_state

    # ------------------------------------------------------------------
    # Step 1: detect people.
    # ------------------------------------------------------------------

    def detect_persons(
        self,
        text: str,
        *,
        character_names: Optional[List[str]] = None,
        explicit_appearances: Optional[List[Dict[str, str]]] = None) -> List[Person]:
        """Detect people in text and assign neutral actor labels.

        Args:
            text: Prompt or chat text.
            character_names: Explicit names, bypassing auto-detection.
            explicit_appearances: Resolved appearances, bypassing detection entirely.

        Returns:
            Person objects with neutral actor labels.
        """
        if explicit_appearances is not None:
            persons = self._persons_from_appearances(explicit_appearances)
        elif character_names is not None:
            persons = self._resolve_by_names(character_names)
        else:
            persons = self._auto_detect(text)

        self._assign_actor_labels(persons)
        return persons

    def _avatar_name(self) -> str:
        """Name of the player's avatar — empty when the player controls none.

        The avatar IS the player in the world. The account login name used to
        serve as a fallback here, which drew a person who exists nowhere: with
        no avatar there is nobody to put in the picture.
        """
        return get_active_character()

    def _is_avatar_name(self, name: str) -> bool:
        """True when *name* refers to the player's avatar."""
        if not name:
            return False
        active = get_active_character()
        return bool(active) and name == active

    def _persons_from_appearances(self, appearances: List[Dict[str, str]]) -> List[Person]:
        """Konvertiert bestehende Appearance-Dicts in Person-Objekte."""
        persons = []
        avatar_name = self._avatar_name()

        for app in appearances:
            name = app.get("name", "")
            if not name:
                continue
            if self._is_avatar_name(name):
                gender = get_user_gender().strip().lower()
                persons.append(Person(
                    name=avatar_name, appearance=app.get("appearance", ""),
                    gender=gender, is_user=True))
            else:
                profile = get_character_profile(name)
                gender = profile.get("gender", "").strip().lower()
                persons.append(Person(
                    name=name, appearance=app.get("appearance", ""),
                    gender=gender, is_agent=(name == self.character_name)))
        return persons

    def _resolve_by_names(self, names: List[str]) -> List[Person]:
        """Resolve appearances for an explicit list of names."""
        persons = []
        avatar_name = self._avatar_name()

        for name in names:
            if self._is_avatar_name(name):
                appearance = get_user_appearance() or ""
                gender = get_user_gender().strip().lower()
                persons.append(Person(
                    name=avatar_name, appearance=appearance,
                    gender=gender, is_user=True))
            else:
                appearance = self._resolve_character_appearance(name)
                profile = get_character_profile(name)
                gender = profile.get("gender", "").strip().lower()
                if appearance:
                    persons.append(Person(
                        name=name, appearance=appearance,
                        gender=gender, is_agent=(name == self.character_name)))
        return persons

    def _auto_detect(self, text: str) -> List[Person]:
        """Automatically detect people in prompt text through pronouns and names."""
        padded = f" {text.lower()} "
        persons = []

        # 1. Agent: Name oder Ich-Pronomen
        agent_mentioned = (
            bool(re.search(r'\b' + re.escape(self.character_name.lower()) + r'\b', padded))
            or any(p in padded for p in _AGENT_PRONOUNS)
        )
        if agent_mentioned:
            appearance = self._resolve_character_appearance(self.character_name)
            if appearance:
                profile = get_character_profile(self.character_name)
                gender = profile.get("gender", "").strip().lower()
                persons.append(Person(
                    name=self.character_name, appearance=appearance,
                    gender=gender, is_agent=True))

        # 2. User-Avatar: Avatar-Name oder Du-Pronomen
        avatar_name = self._avatar_name()
        if avatar_name:
            user_mentioned = (
                re.search(r'\b' + re.escape(avatar_name.lower()) + r'\b', padded) is not None
                or any(p in padded for p in _USER_PRONOUNS)
            )
            if user_mentioned:
                user_app = get_user_appearance()
                if user_app:
                    gender = get_user_gender().strip().lower()
                    persons.append(Person(
                        name=avatar_name, appearance=user_app,
                        gender=gender, is_user=True))

        # 3. Other named characters, excluding duplicate agent/user entries.
        # Strict location scope: other characters may appear only when they share
        # the agent's location. This prevents an incidental tool-LLM name from
        # pulling a character into the picture from somewhere else.
        # For example, mentioning someone who is currently asleep must not pull them in.
        already_added = {p.name for p in persons}
        all_chars = list_available_characters()
        _agent_loc = (get_character_current_location(self.character_name) or "").strip()
        for char_name in all_chars:
            if char_name == self.character_name or char_name in already_added:
                continue
            if re.search(r'\b' + re.escape(char_name.lower()) + r'\b', padded):
                # Strict location check: another location excludes the character.
                if _agent_loc:
                    _other_loc = (get_character_current_location(char_name) or "").strip()
                    if _other_loc and _other_loc != _agent_loc:
                        logger.info(
                            "Person '%s' im Text erwaehnt aber NICHT ergaenzt — "
                            "anderer Ort (Agent=%s, %s=%s)",
                            char_name, _agent_loc, char_name, _other_loc)
                        continue
                appearance = self._resolve_character_appearance(char_name)
                if appearance:
                    profile = get_character_profile(char_name)
                    gender = profile.get("gender", "").strip().lower()
                    persons.append(Person(
                        name=char_name, appearance=appearance,
                        gender=gender))

        # 4. With no detected person, use the active agent as the default subject,
        # including its appearance and reference image (for example, an
        # unspecific group-chat tool prompt describing a beautiful sunset).
        if not persons and self.character_name:
            appearance = self._resolve_character_appearance(self.character_name)
            if appearance:
                profile = get_character_profile(self.character_name)
                gender = profile.get("gender", "").strip().lower()
                persons.append(Person(
                    name=self.character_name, appearance=appearance,
                    gender=gender, is_agent=True))
                logger.debug("Auto-Detect: Keine Personen erkannt — Agent '%s' als Default", self.character_name)

        return persons

    def _resolve_character_appearance(self, name: str) -> str:
        """Resolves the appearance text — delegates to the shared
        person_description so previews and renders cannot drift."""
        return person_description(
            name, apply_state_modifiers=self.apply_state_modifiers,
            back_view=self.back_view, mesh_input=self.mesh_input,
            body_profile=self.body_profile if name == self.character_name else None,
            neutral_state=self.neutral_state)

    def _assign_actor_labels(self, persons: List[Person]) -> None:
        """Set actor_label to the actual character name."""
        for person in persons:
            person.actor_label = person.name

    # ------------------------------------------------------------------
    # Step 1b: centralized photographer filter, after detect_persons.
    # ------------------------------------------------------------------

    def apply_photographer_filter(
        self,
        persons: List[Person],
        *,
        photographer_mode: bool,
        is_selfie: bool,
        set_profile: bool) -> List[Person]:
        """Exclude the agent when it is the photographer rather than a subject.

        Rules (done/image-creation.md 4.2.2 and plan-image-creation-redesign.md 5):
        - photographer_mode=False: leave persons unchanged.
        - is_selfie=True: retain the agent as the self-portrait subject.
        - set_profile=True: retain the agent for its profile picture.
        - Photographer detected without another subject: insert the user avatar.
        - Photographer absent with no subjects: leave persons empty for a stranger photo.

        Repeated calls are idempotent.
        """
        if not photographer_mode or is_selfie or set_profile:
            return persons

        agent_was_detected = any(p.is_agent for p in persons)
        filtered = [p for p in persons if not p.is_agent]

        if agent_was_detected and not filtered:
            user = self._create_user_person()
            if user:
                filtered.append(user)
                logger.info(
                    "Photographer-Filter: Agent erkannt, kein Subject "
                    "-> User-Avatar '%s' als Default", user.name)

        if filtered != persons:
            logger.info(
                "Photographer-Filter: Agent '%s' entfernt, Subjects=%s",
                self.character_name, [p.name for p in filtered])

        return filtered

    # ------------------------------------------------------------------
    # Step 2: collect context variables.
    # ------------------------------------------------------------------

    def collect_context(
        self,
        persons: List[Person],
        config: EntryPointConfig,
        *,
        prompt_text: str = "",
        photographer_mode: bool = False,
        set_profile: bool = False,
        item_ids: Optional[List[str]] = None) -> PromptVariables:
        """Collect context variables for detected people.

        Args:
            persons: People returned by detect_persons().
            config: Entry-point configuration.
            prompt_text: Original prompt for selfie detection.
            photographer_mode: Whether photographer mode is active.
            set_profile: Whether this is a profile image.
            item_ids: Prop item IDs using available reference slots.
        """
        variables = PromptVariables()
        variables.persons = persons
        variables.photographer_mode = photographer_mode
        variables.set_profile = set_profile
        variables.is_selfie = any(kw in prompt_text.lower() for kw in SELFIE_KEYWORDS)
        # Collect items early; later steps read variables.items.
        if item_ids:
            variables.items = self._collect_items(item_ids)

        # Apply the photographer filter before collect_context.
        # See apply_photographer_filter(); only the stranger-photo case remains here.
        # Fallback for an empty people list.
        agent_person = next((p for p in persons if p.is_agent), None)

        # No person detected?
        if not persons:
            if config.include_persons and any(kw in prompt_text.lower() for kw in _PERSON_KEYWORDS):
                variables.no_person_detected = False
                if not photographer_mode:
                    # Non-Photographer Fallback: Agent als Default nehmen
                    agent_person = self._create_agent_person()
                    if agent_person:
                        persons = [agent_person]
                        variables.persons = persons
                        logger.info("Fallback: Person-Keywords erkannt -> Agent '%s' hinzugefuegt",
                                    self.character_name)
                else:
                    # Photographer mode excludes the photographer from the picture.
                    # The prompt describes a person (person keyword detected)
                    # without naming a known character.
                    # genannt — also FIKTIVE Person (Stranger-Photo).
                    # Leave persons empty instead of forcing the user avatar;
                    # the renderer creates the person described by the prompt.
                    logger.info("Photographer-Stranger: keine bekannte Person — "
                                "fiktives Motiv")
            else:
                variables.no_person_detected = True
                logger.debug("Keine Person erkannt -> reines Ort-/Raum-Bild")

        # Ensure the agent exists for set_profile or when other people are present.
        if config.include_persons and not any(p.is_agent for p in persons):
            if set_profile or (persons and not photographer_mode):
                agent_person = self._create_agent_person()
                if agent_person:
                    persons.insert(0, agent_person)
                    variables.persons = persons
                    logger.info("Agent '%s' automatisch hinzugefuegt", self.character_name)

        # Personen-Variablen befuellen
        if config.include_persons:
            for idx, person in enumerate(persons, 1):
                variables.prompt_persons[idx] = f"{person.actor_label}, {person.appearance}"

        # Outfit + Reference-Bilder pro Person.
        # Profile images carry neither outfit text nor reference images:
        # otherwise they create a self-reference loop; the profile-image workflow
        # needs only a head and face description anyway.
        if config.include_outfit and not set_profile:
            self._collect_outfits(persons, variables, photographer_mode)

        # Stimmung
        if config.include_mood and persons:
            self._collect_mood(persons, variables, photographer_mode)

        # Aktivitaet
        if config.include_activity and persons:
            self._collect_activity(persons, variables, photographer_mode)

        # Location. Not for a profile render: a portrait shows the character,
        # never the room it happens to stand in — the dedicated profile entry
        # point (dialog_profile) says the same via include_location=False, and
        # the slot planner drops the room reference for the same reason.
        if config.include_location and not set_profile:
            self._collect_location(variables)

        # Personality applies only to profile images.
        if set_profile:
            personality = get_character_personality(self.character_name) or ""
            variables.personality = personality

        self._log_variables(variables)
        return variables

    def _create_agent_person(self) -> Optional[Person]:
        """Create the agent's Person object."""
        appearance = self._resolve_character_appearance(self.character_name)
        if not appearance:
            return None
        profile = get_character_profile(self.character_name)
        gender = profile.get("gender", "").strip().lower()
        person = Person(
            name=self.character_name, appearance=appearance,
            gender=gender, is_agent=True)
        # Label zuweisen
        self._assign_actor_labels([person])
        return person

    def _create_user_person(self) -> Optional[Person]:
        """Create a Person object for the user avatar (active character)."""
        avatar_name = self._avatar_name()
        if not avatar_name:
            return None
        appearance = get_user_appearance()
        if not appearance:
            return None
        gender = get_user_gender().strip().lower()
        person = Person(
            name=avatar_name, appearance=appearance,
            gender=gender, is_user=True)
        self._assign_actor_labels([person])
        return person

    def _collect_items(self, item_ids: List[str]) -> List[Dict[str, Any]]:
        """Load name, description and image_path for the supplied item IDs.

        Only items with an existing PNG receive reference slots. Other items may
        still appear in prompt text.
        """
        from app.models.inventory import get_item, get_item_image_path
        out: List[Dict[str, Any]] = []
        for iid in item_ids or []:
            it = get_item(iid)
            if not it:
                continue
            img_path = ""
            try:
                p = get_item_image_path(iid)
                if p and Path(p).exists():
                    img_path = str(p)
            except Exception:
                img_path = ""
            out.append({
                "id": iid,
                "name": it.get("name", iid),
                "description": (it.get("description") or "").strip(),
                "image": img_path,
            })
        logger.debug("Items gesammelt: %d von %d (mit Bild: %d)",
                     len(out), len(item_ids or []),
                     sum(1 for x in out if x["image"]))
        return out

    def _collect_outfits(
        self, persons: List[Person], variables: PromptVariables,
        photographer_mode: bool) -> None:
        """Collect outfit prompts and reference images for each person."""
        for idx, person in enumerate(persons, 1):
            outfit_text = ""
            ref_path = ""

            if person.is_user:
                # User-Avatar: gleiche Outfit-Kette wie Character.
                active_char = get_active_character() or person.name
                if active_char:
                    outfit_text = render_outfit(character_name=active_char, mesh_input=self.mesh_input).get("full", "")
                    ref_path = self._resolve_person_ref_image(
                        Person(name=active_char, appearance=person.appearance,
                               gender=person.gender, is_agent=False)
                    )
                if not ref_path:
                    profile_img = get_user_profile_image()
                    if profile_img:
                        images_dir = get_user_images_dir()
                        candidate = images_dir / profile_img
                        if candidate.exists():
                            ref_path = str(candidate)
            else:
                outfit_text = render_outfit(character_name=person.name, mesh_input=self.mesh_input).get("full", "")
                ref_path = self._resolve_person_ref_image(person)

            if outfit_text:
                # render_outfit().full may supply "wearing: <fragments>";
                # strip that prefix to avoid "is wearing wearing: ...".
                _ot = outfit_text.lstrip()
                if _ot.lower().startswith("wearing: "):
                    outfit_text = _ot[len("wearing: "):]
                elif _ot.lower().startswith("wearing:"):
                    outfit_text = _ot[len("wearing:"):].lstrip()
                variables.prompt_outfits[idx] = f"{person.actor_label} is wearing {outfit_text}"
            if ref_path:
                variables.ref_images[idx] = ref_path

    def _resolve_person_ref_image(self, person: Person, profile_only: bool = False) -> str:
        """Resolves the best reference image of a person (fallback chain).

        Args:
            person: Person object.
            profile_only: True = profile image only (e.g. outfit creation).
        """
        # User: profile image
        if person.is_user:
            profile_img = get_user_profile_image()
            if profile_img:
                images_dir = get_user_images_dir()
                candidate = images_dir / profile_img
                if candidate.exists():
                    logger.debug("RefImage [%s]: User-Profilbild", person.name)
                    return str(candidate)
            return ""

        # profile_only: jump straight to the profile image (e.g. outfit creation)
        if profile_only:
            profile_img = get_character_profile_image(person.name)
            if profile_img:
                images_dir = get_character_images_dir(person.name)
                candidate = images_dir / profile_img
                if candidate.exists():
                    logger.debug("RefImage [%s]: Profilbild (profile_only)", person.name)
                    return str(candidate)
            return ""

        # Current expression contract, same selected set and exact outfit only.
        try:
            from app.core.expression_regen import expression_snapshot, find_compatible_expression
            mood = get_character_current_feeling(person.name) or ""
            cached = find_compatible_expression(expression_snapshot(person.name, mood))
            if cached:
                return str(cached)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.debug("Expression identity reference unavailable for %s: %s", person.name, exc)

        # Prio 2: profile image
        profile_img = get_character_profile_image(person.name)
        if profile_img:
            images_dir = get_character_images_dir(person.name)
            candidate = images_dir / profile_img
            if candidate.exists():
                logger.debug("RefImage [%s]: Profilbild", person.name)
                return str(candidate)

        return ""

    def _collect_mood(
        self, persons: List[Person], variables: PromptVariables,
        photographer_mode: bool) -> None:
        """Collect each person's mood."""
        # Mood tracking must be enabled.
        char_config = get_character_config(self.character_name) if self.character_name else {}
        if not char_config.get("mood_tracking", False):
            return

        mood_parts = []
        for person in persons:
            if person.is_user:
                continue  # User hat kein Mood-Tracking
            feeling = get_character_current_feeling(person.name) or ""
            if feeling:
                mood_parts.append(f"{person.actor_label} looks {feeling}")

        if mood_parts:
            variables.prompt_mood = ", ".join(mood_parts)

    def _collect_activity(
        self, persons: List[Person], variables: PromptVariables,
        photographer_mode: bool) -> None:
        """Collect each person's activity."""
        activity_parts = []
        for person in persons:
            if person.is_user:
                continue
            raw = get_effective_activity(person.name)
            if raw:
                # Pose text already describes the activity; there is no library lookup.
                # Beschreibung mehr.
                activity_parts.append(f"{person.actor_label} is {raw}")

        if activity_parts:
            variables.prompt_activity = ", ".join(activity_parts)

    def _collect_location(self, variables: PromptVariables) -> None:
        """Collect location and room data."""
        raw_location = get_character_current_location(self.character_name)
        if not raw_location:
            return

        loc_data = get_location(raw_location)
        current_room_id = get_character_current_room(self.character_name)
        # Day/night is a GAME-clock question and the calendar answers it: the
        # season's sunrise/sunset, not a fixed hour of the system clock.
        is_day = game_time().is_day()

        location_name = ""
        location_desc = ""

        def _safe_desc_fallback(desc: str) -> str:
            """Use description only when it resembles an image description, not
            first-person narration or a chat monologue accidentally stored by a tool call.
            """
            if not desc:
                return ""
            d = desc.strip().lower()
            # First-person markers distinguish chat monologue from room description.
            _bad_starts = ("mein blick", "ich ", "ich.", "i feel", "i am",
                           "i'm ", "my ", "we ", "wir ", "sollte ich",
                           "should i ", "let me ", "lass mich")
            if any(d.startswith(s) for s in _bad_starts):
                logger.warning(
                    "Location-description verworfen (First-Person-Marker): %s",
                    desc[:80])
                return ""
            return desc

        # Raum-Prompt hat Prioritaet
        if current_room_id and loc_data:
            room_data = get_room_by_id(loc_data, current_room_id)
            if room_data:
                location_name = room_data.get("name", "")
                if is_day:
                    location_desc = (room_data.get("image_prompt_day", "")
                                     or _safe_desc_fallback(room_data.get("description", "")))
                else:
                    location_desc = (room_data.get("image_prompt_night", "")
                                     or _safe_desc_fallback(room_data.get("description", "")))

        if not location_name:
            # Fallback: Location-Level
            location_name = loc_data.get("name", raw_location) if loc_data else raw_location
            if loc_data:
                if is_day:
                    location_desc = (loc_data.get("image_prompt_day", "")
                                     or _safe_desc_fallback(loc_data.get("description", "")))
                else:
                    location_desc = (loc_data.get("image_prompt_night", "")
                                     or _safe_desc_fallback(loc_data.get("description", "")))

        if location_desc:
            variables.prompt_location = f"{location_name}, {location_desc}"
        elif location_name:
            variables.prompt_location = location_name

        # Room reference image: the character's room (its own images, else the
        # location default — get_background_path decides), the same place the
        # setting text above names.
        bg_path = get_background_path(raw_location, room=current_room_id or "")
        if bg_path and bg_path.exists():
            variables.ref_image_room = str(bg_path)

    def _log_variables(self, variables: PromptVariables) -> None:
        """Log the collected variables."""
        for idx, prompt in variables.prompt_persons.items():
            logger.info("prompt_person_%d: %s...", idx, prompt[:80])
        for idx, prompt in variables.prompt_outfits.items():
            logger.debug("prompt_outfit_%d: %s", idx, prompt[:100])
        for idx, path in variables.ref_images.items():
            logger.debug("ref_image_%d: %s", idx, path.split("/")[-1] if "/" in path else path)
        if variables.prompt_mood:
            logger.debug("prompt_mood: %s", variables.prompt_mood)
        if variables.prompt_activity:
            logger.debug("prompt_activity: %s", variables.prompt_activity)
        if variables.prompt_location:
            logger.debug("prompt_location: %s", variables.prompt_location[:100])
        if variables.ref_image_room:
            logger.debug("ref_image_4 (room): %s", Path(variables.ref_image_room).name)

    # ------------------------------------------------------------------
    # Step 3: apply exclusion rules.
    # ------------------------------------------------------------------

    def apply_exclusion_rules(
        self,
        variables: PromptVariables,
        *,
        max_slots: int = 0) -> PromptVariables:
        """Applies reference-slot exclusion rules.

        A person reference image only supplies the *appearance* (identity).
        Outfit AND activity therefore always stay in the text — the ref image
        does not show the desired outfit or action. Only the *location* is
        dropped, and only when a room reference image actually ends up in a
        slot (then the image shows the location and the text would be
        redundant).

        Args:
            variables: Collected prompt variables.
            max_slots: Number of reference slots of the target backend
                  (``backend.ref_slot_count``). <= 0 means the backend takes
                  no reference images — everything stays in the text.
        """
        if max_slots <= 0:
            return variables

        # The location is dropped ONLY when a room reference image really
        # lands in a slot (priority plan). Outfit and activity deliberately
        # stay in the text.
        room_slotted = any(
            e["kind"] == "room" for e in self._plan_qwen_slots(variables, max_slots))

        if room_slotted and variables.prompt_location:
            logger.debug("Ausschluss: prompt_location entfernt (Raum-Ref im Slot)")
            variables.prompt_location = ""

        return variables

    # ------------------------------------------------------------------
    # Step 3b: clean scene_prompt as defence in depth.
    # ------------------------------------------------------------------

    def sanitize_scene_prompt(
        self,
        scene_prompt: str,
        variables: PromptVariables) -> str:
        """Remove duplicated content from the LLM-generated scene_prompt.

        Remove appearance/outfit phrases already present in prompt_persons or
        prompt_outfits; see plan 4.2.1b.

        Args:
            scene_prompt: Generated scene text.
            variables: Collected prompt variables used for comparison.

        Returns:
            The cleaned scene prompt.
        """
        if not scene_prompt:
            return scene_prompt

        original = scene_prompt

        # 0. Remove photographer references (plan 4.2.2).
        # The photographer must not appear in scene_prompt.
        # Remove segments containing the agent name or camera actions.
        if variables.photographer_mode:
            character_name_lower = self.character_name.lower()
            segments = [s.strip() for s in scene_prompt.split(",")]
            cleaned = []
            for s in segments:
                s_lower = s.lower()
                # Character name in the segment.
                if character_name_lower in s_lower:
                    logger.debug("scene_prompt: Photographer-Segment entfernt (Name): '%s'", s[:80])
                    continue
                # Camera/photography actions belong to the photographer, not the subject.
                if any(kw in s_lower for kw in _CAMERA_KEYWORDS):
                    logger.debug("scene_prompt: Photographer-Segment entfernt (Kamera): '%s'", s[:80])
                    continue
                cleaned.append(s)
            scene_prompt = ", ".join(s for s in cleaned if s)

        # 0b. Remove duplicated name introductions.
        # The tool LLM may duplicate a name introduction despite a separate appearance.
        # Remove segments such as "<Name>, a/an <adjective> man/woman/person".
        known_names = {p.name.lower() for p in variables.persons if p.name}
        if known_names:
            segments = [s.strip() for s in scene_prompt.split(",")]
            cleaned = []
            for s in segments:
                s_stripped = s.strip().lower()
                # Check whether the segment is only a name or "a/an ... man/woman/person/guy/girl".
                is_name_intro = False
                for name in known_names:
                    if s_stripped == name:
                        is_name_intro = True
                        break
                    if s_stripped.startswith(("a ", "an ")) and any(
                        w in s_stripped for w in ("man", "woman", "person", "guy", "girl", "male", "female")
                    ):
                        is_name_intro = True
                        break
                if is_name_intro:
                    logger.debug("scene_prompt: Namens-Einleitung entfernt: '%s'", s[:80])
                else:
                    cleaned.append(s)
            scene_prompt = ", ".join(s for s in cleaned if s)

        # 1. Extract outfit phrases from scene_prompt and put them into
        # prompt_outfits[1] (agent), so the tool LLM's requested outfit
        # ("posing in sports bra and leggings") replaces the DB outfit.
        # Without this replacement, tool-LLM and DB outfits would both appear.
        # Do not leave the same phrases as extra garbage in the final prompt.
        #
        #    Erkannte Patterns (case-insensitive, je bis Komma/Punkt):
        #      - "(is) wearing X"
        #      - "posing in X" / "dressed in X" / "clad in X"
        #      - "in X attire" / "in X clothes" / "in X outfit"
        _outfit_patterns = [
            re.compile(r',?\s*(?:is\s+)?wearing\s+([^,\.]+)(?=[,\.]|$)', re.IGNORECASE),
            re.compile(r',?\s*(?:posing|dressed|clad)\s+in\s+([^,\.]+)(?=[,\.]|$)', re.IGNORECASE),
            re.compile(r',?\s*in\s+([^,\.]+?\s+(?:attire|clothes|outfit))(?=[,\.]|$)', re.IGNORECASE),
        ]
        _extracted_outfits: List[str] = []
        for _pat in _outfit_patterns:
            for _m in _pat.finditer(scene_prompt):
                _phrase = _m.group(1).strip()
                if _phrase:
                    _extracted_outfits.append(_phrase)
            scene_prompt = _pat.sub('', scene_prompt).strip()

        # 1b. Detect implicit clothing mentions without a "wearing" verb.
        # When the tool LLM supplies "young woman's legs in a short black skirt"
        # or "lace thong, business heels", use that full outfit rather than
        # use its outfit completely rather than also injecting the DB outfit
        # combining two outfits in one picture.
        _CLOTHING_KEYWORDS = (
            "skirt", "dress", "blazer", "shirt", "blouse", "pants", "trousers",
            "jeans", "shorts", "leggings", "stockings", "tights", "socks",
            "shoes", "boots", "heels", "sneakers", "sandals", "sneekers",
            "jacket", "coat", "hoodie", "sweater", "cardigan", "vest",
            "bra", "bikini", "panties", "thong", "underwear", "lingerie",
            "lederhose", "rock", "kleid", "hose", "stiefel", "schuhe",
            "blazer", "weste", "mantel",
        )
        _segments = [s.strip() for s in scene_prompt.split(",")]
        _cleaned_segments = []
        for _seg in _segments:
            _seg_low = _seg.lower()
            _has_clothing = any(
                re.search(r'\b' + re.escape(kw) + r'\b', _seg_low)
                for kw in _CLOTHING_KEYWORDS
            )
            if _has_clothing:
                # Remove a "young woman's? " prefix when the tool LLM
                # uses that instead of the subject's name.
                _clean = re.sub(
                    r"\byoung\s+woman'?s?\s+", "",
                    _seg, flags=re.IGNORECASE).strip()
                # Remove remaining person-with-clothing description prefixes.
                # Do not leave stripped prefixes behind.
                _clean = re.sub(
                    r"^(her|his|their)\s+", "",
                    _clean, flags=re.IGNORECASE).strip()
                if _clean:
                    _extracted_outfits.append(_clean)
                    logger.debug(
                        "scene_prompt: Implizites Outfit-Segment extrahiert: '%s'",
                        _clean[:80])
            else:
                _cleaned_segments.append(_seg)
        scene_prompt = ", ".join(s for s in _cleaned_segments if s)

        if _extracted_outfits and variables.persons:
            # Assign the outfit to the detected agent, otherwise to the first person.
            # The tool-LLM outfit replaces, rather than merges with, the DB outfit:
            # it describes a specific scene while the DB outfit is only a default.
            # One picture must have one coherent outfit.
            _agent_idx = next(
                (i + 1 for i, p in enumerate(variables.persons) if p.is_agent),
                1)
            _agent_label = variables.persons[_agent_idx - 1].actor_label or variables.persons[_agent_idx - 1].name
            _new_outfit = ", ".join(_extracted_outfits)
            variables.prompt_outfits[_agent_idx] = f"{_agent_label} is wearing {_new_outfit}"
            logger.info(
                "scene_prompt: Outfit aus Tool-LLM extrahiert -> prompt_outfits[%d] = '%s'",
                _agent_idx, _new_outfit[:120])

            # A concrete tool-LLM scene already specifies its own outfit, so
            # DB state fields are irrelevant to THIS image:
            # - prompt_activity: "sitting at desk" contradicts a gym scene.
            # - prompt_mood: the DB mood expression overrides the tool-LLM expression.
            #                explizit beschriebene Expression ("shy smile")
            # - prompt_location: an office contradicts a gym setting.
            # Keep scene details (pose, expression and setting) in
            # bereinigten scene_prompt erhalten und gehen so ins Bild.
            if variables.prompt_activity:
                logger.info(
                    "scene_prompt: Outfit-Override -> DB-Activity '%s' geloescht "
                    "(Tool-LLM-Szene gilt)", variables.prompt_activity[:80])
                variables.prompt_activity = ""
            if variables.prompt_mood:
                logger.info(
                    "scene_prompt: Outfit-Override -> DB-Mood '%s' geloescht",
                    variables.prompt_mood[:80])
                variables.prompt_mood = ""
            if variables.prompt_location:
                logger.info(
                    "scene_prompt: Outfit-Override -> DB-Location '%s' geloescht",
                    variables.prompt_location[:80])
                variables.prompt_location = ""

        # 2. Remove appearance phrases for detected people.
        # Check each person for significant appearance words in scene_prompt.
        for person in variables.persons:
            if not person.appearance:
                continue
            # Split the appearance into significant words (more than 3 characters).
            app_words = set(
                w.lower() for w in re.findall(r'\b\w+\b', person.appearance)
                if len(w) > 3 and w.lower() not in _COMMON_WORDS
            )
            if not app_words:
                continue

            # scene_prompt in Segmente (Komma-getrennt) zerlegen
            segments = [s.strip() for s in scene_prompt.split(",")]
            cleaned_segments = []
            for segment in segments:
                seg_words = set(
                    w.lower() for w in re.findall(r'\b\w+\b', segment)
                    if len(w) > 3 and w.lower() not in _COMMON_WORDS
                )
                # Remove a segment when over 60% of its words occur in the appearance.
                if seg_words and len(seg_words & app_words) / len(seg_words) > 0.6:
                    logger.debug("scene_prompt: Appearance-Segment entfernt fuer '%s': '%s'",
                                 person.name, segment[:80])
                else:
                    cleaned_segments.append(segment)
            scene_prompt = ", ".join(s for s in cleaned_segments if s)

        # Aufraumen: mehrfache Kommas/Leerzeichen
        scene_prompt = re.sub(r'\s*,\s*,\s*', ', ', scene_prompt).strip(", ")

        if scene_prompt != original:
            logger.info("scene_prompt bereinigt: '%s' -> '%s'",
                        original[:120], scene_prompt[:120])

        return scene_prompt

    # ------------------------------------------------------------------
    # Step 4: assemble the prompt.
    # ------------------------------------------------------------------
    # Final assembly now happens in app/core/prompt_adapters.render()
    # for the target model (z_image/qwen/flux); no assembly is needed here.

    # ------------------------------------------------------------------
    # Step 5: resolve reference-image slots.
    # ------------------------------------------------------------------

    def resolve_reference_slots(
        self,
        variables: PromptVariables,
        max_slots: int = 4) -> Dict[str, Any]:
        """Builds the reference-image slot map for the target backend.

        Slots are filled by priority — 1 creating character, 2 room,
        3 other characters, 4 items (until slots are full).

        Args:
            variables: Collected prompt variables.
            max_slots: Number of reference slots of the target backend
                (``backend.ref_slot_count``). <= 0 means no slots.

        Returns:
            Dict with keys:
                reference_images: {slot_name: file_path}
                has_reference_slots: bool   (True when person slots are used)
        """
        if max_slots <= 0:
            return {"reference_images": {}, "has_reference_slots": False}

        return self._resolve_qwen_slots(variables, max_slots)

    def _plan_qwen_slots(
        self, variables: PromptVariables, max_slots: int) -> List[Dict[str, Any]]:
        """Assign reference images to the available slots by priority.

        Order (fills slots 1..max_slots in turn until full):
            1. creating character (is_agent)
            2. room / location (ref_image_room)
            3. other characters in the prompt
            4. items

        The ONE source of the slot assignment — used both for the generation
        (_resolve_qwen_slots) and for the exclusion rules, so both decide
        consistently what actually sits in a slot.

        A profile render accepts only an explicitly supplied identity reference
        of the creating character. It never inherits the room, other people or
        item references. The default profile request supplies no identity ref.
        """


        def _person_entry(pos: int, person) -> Optional[Dict[str, Any]]:
            ref_path = variables.ref_images.get(pos, "")
            if not ref_path or not Path(ref_path).exists():
                return None
            return {"kind": "person", "pos": pos, "path": ref_path,
                    "name": person.name, "is_agent": person.is_agent,
                    "gender": self._normalize_gender(person.gender)}

        if variables.set_profile:
            ref = variables.profile_reference
            if not ref or not Path(ref).is_file() or max_slots <= 0:
                return []
            return [{"kind": "person", "pos": 1, "path": ref,
                     "name": self.character_name, "is_agent": True, "gender": ""}]

        plan: List[Dict[str, Any]] = []

        # Prio 1: erstellender Character
        for pos, person in enumerate(variables.persons, 1):
            if person.is_agent:
                entry = _person_entry(pos, person)
                if entry:
                    plan.append(entry)
                break

        # Prio 2: Raum / Location
        if variables.ref_image_room and Path(variables.ref_image_room).exists():
            plan.append({"kind": "room", "path": variables.ref_image_room})

        # Prio 3: andere Charaktere
        for pos, person in enumerate(variables.persons, 1):
            if person.is_agent:
                continue
            entry = _person_entry(pos, person)
            if entry:
                plan.append(entry)

        # Prio 4: Items
        for it in (variables.items or []):
            img_path = it.get("image", "")
            if img_path and Path(img_path).exists():
                plan.append({"kind": "item", "path": img_path,
                             "name": it.get("name", "?")})

        return plan[:max(0, max_slots)]

    def _resolve_qwen_slots(
        self, variables: PromptVariables, max_slots: int) -> Dict[str, Any]:
        """Distributes reference images onto the slots by priority.

        Slot order = priority (see _plan_qwen_slots): creating character
        first, then room, then other characters, then items.
        """
        reference_images: Dict[str, str] = {}
        has_reference_slots = False

        for slot, entry in enumerate(self._plan_qwen_slots(variables, max_slots), 1):
            key = f"input_reference_image_{slot}"
            reference_images[key] = entry["path"]
            if entry["kind"] == "person":
                has_reference_slots = True
                logger.debug("RefSlot %d: %s (gender=%s)%s", slot, entry["name"],
                             entry["gender"] or "no",
                             " [Agent]" if entry.get("is_agent") else "")
            elif entry["kind"] == "room":
                logger.debug("RefSlot %d: Room/Location", slot)
            else:  # item
                logger.info("RefSlot %d: Item '%s'", slot, entry.get("name", "?"))

        logger.debug("RefSlots: %d belegt (Prio Agent>Raum>andere>Items)",
                     len(reference_images))

        return {
            "reference_images": reference_images,
            "has_reference_slots": has_reference_slots,
        }

    @staticmethod
    def _normalize_gender(gender: str) -> str:
        """Normalize gender for ComfyUI workflows and actor labels."""
        g = gender.strip().lower()
        if g in ("female", "f", "weiblich", "w", "woman", "girl", "frau", "mädchen", "maedchen"):
            return "female"
        if g in ("male", "m", "männlich", "maennlich", "man", "boy", "mann", "junge"):
            return "male"
        return ""
