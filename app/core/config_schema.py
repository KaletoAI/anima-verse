"""Config schema definition for admin settings page.

Each section defines field metadata: type, label, description, default,
sensitive flag, choices, and validation rules. This drives both the
admin UI rendering and server-side validation.
"""

# Field types: str, int, float, bool, text (multiline), select, password, json_str
# "array" and "object" are handled by section-level definitions

SECTIONS = {
    "server": {
        "label": "Server",
        "icon": "⚙",
        "fields": {
            "log_level": {
                "type": "select",
                "label": "Log Level",
                "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
                "default": "INFO",
            },
            "jwt_secret": {
                "type": "password",
                "label": "JWT Secret",
                "description": "Secret key for JWT token signing. Change in production!",
                "sensitive": True,
                "requires_restart": True,
            },
            "storage_dir": {
                "type": "str",
                "label": "Storage Directory",
                "default": "./storage",
                "description": "Basisverzeichnis fuer Datenbanken, Configs und Uploads",
                "requires_restart": True,
            },
            "timezone": {
                "type": "str",
                "label": "World Timezone",
                "default": "Europe/Berlin",
                "description": "IANA timezone (e.g. Europe/Berlin) for the in-world clock the "
                               "characters see and for day boundaries. Storage stays UTC — this "
                               "only affects displayed/world time. Empty = UTC.",
            },
            "log_retention_days": {
                "type": "int",
                "label": "Log Aufbewahrung (Tage)",
                "default": 5,
                "min": 1,
                "max": 365,
                "description": "Eintraege in logs/llm_calls.jsonl und logs/image_prompts.jsonl, "
                               "die aelter als diese Anzahl Tage sind, werden beim Server-Start "
                               "automatisch entfernt.",
            },
            "world_admin_tick_interval_seconds": {
                "type": "int",
                "label": "World-Admin-Tick Intervall (Sek.)",
                "default": 60,
                "min": 10,
                "max": 3600,
                "description": "Frequenz des zentralen Hintergrund-Ticks. Triggert: "
                               "Status-Decay, Force-Rules (z.B. Wake-Up), Assignment-Expiry, "
                               "Random-Events, Relationship-Decay. Sub-Tasks haben eigene "
                               "Sub-Frequenzen — Status-Decay laeuft z.B. nur stuendlich, "
                               "Force-Rules jeden Tick. Niedrigere Werte = schnellere Reaktion "
                               "auf Stat-Schwellen, hoehere Werte = weniger CPU-Last.",
            },
            "api_key": {
                "type": "password",
                "label": "API Key",
                "description": "Shared secret for external services that write data back via the "
                               "API (sent as X-API-Key header) — e.g. the post-processing service "
                               "writing a processed image. Stored in secrets.json, never committed.",
                "sensitive": True,
            },
        },
    },
    "providers": {
        "label": "LLM Providers",
        "icon": "🤖",
        "is_array": True,
        "item_label_field": "name",
        "fields": {
            "name": {"type": "str", "label": "Name", "required": True, "description": "Eindeutiger Name (wird in Task Defaults und GPU-Zuordnung referenziert)"},
            "type": {
                "type": "select",
                "label": "Typ",
                "choices": ["openai", "ollama", "anthropic"],
                "default": "openai",
                "description": "API-Protokoll des Providers",
            },
            "api_base": {"type": "str", "label": "API Base URL", "required": True, "placeholder": "http://host:port/v1"},
            "api_key": {"type": "password", "label": "API Key", "sensitive": True, "default": "not-needed", "description": "API Key (bei lokalen Providern: 'not-needed')"},
            "timeout": {"type": "int", "label": "Timeout (s)", "default": 120, "min": 10, "max": 3600, "description": "Request Timeout in Sekunden"},
            "max_concurrent": {"type": "int", "label": "Max Concurrent", "default": 1, "min": 1, "max": 50, "description": "Maximale gleichzeitige Anfragen"},
            "serialize_group": {"type": "str", "label": "Serialize Group", "description": "Channels with the same group run strictly one at a time (e.g. LLM + image backend sharing one GPU). Empty = no serialization."},
        },
    },
    "llm_retry": {
        "label": "LLM Busy-Retry",
        "icon": "🔁",
        "fields": {
            "busy_max_attempts": {"type": "int", "label": "Max Busy Retries", "default": 3, "min": 0, "max": 10, "description": "When an LLM provider answers 503 ('busy' — the gateway is at its parallel-call limit), wait and retry the SAME model this many times before giving up. 0 disables busy-retry. Triggers ONLY on a real 503 / Service Unavailable; other errors (500/502/504/timeout) keep the cooldown + fallback path."},
            "busy_base_delay_seconds": {"type": "float", "label": "Busy Retry Base Delay (s)", "default": 10, "min": 1, "max": 120, "step": 1, "description": "Backoff base wait before retrying a busy (503) model. Doubles each attempt (e.g. 10 → 20 → 40s), capped at 120s. Keep total backoff under the provider Timeout so the queue worker does not abort mid-wait."},
        },
    },
    "llm_simple": {
        # Virtuelle Section (kein eigenes Config-Feld) — eine einfache,
        # kategorie-basierte Oberflaeche, die CONFIG.llm_routing automatisch
        # befuellt. Gerendert durch renderLlmSimpleEditor() in admin_settings.py.
        "label": "LLM Models (Simple)",
        "icon": "🧭",
        "virtual": True,
    },
    "llm_routing": {
        "label": "LLM Routing (Advanced)",
        "icon": "🔧",
        "nav_sub": True,
        "is_array": True,
        "item_label_field": ["name", "model"],
        "fields": {
            "name": {
                "type": "str",
                "label": "Name",
                "description": "Optional display name for this routing entry. Falls back to the model name when empty.",
            },
            "enabled": {
                "type": "bool",
                "label": "Enabled",
                "default": True,
                "description": "Disable to skip this LLM in routing without removing it (preserves task assignments).",
            },
            "preload_on_startup": {
                "type": "bool",
                "label": "Preload on Startup",
                "default": False,
                "description": "Send a 1-token warmup request at server start so the backend (e.g. llama-swap, vLLM) loads the model into memory. Runs asynchronously and does not block startup. Useful for slow-loading local models.",
            },
            "provider": {"type": "provider_select", "label": "Provider", "required": True},
            "model": {"type": "model_select", "label": "Model", "required": True},
            "temperature": {
                "type": "float",
                "label": "Temperature",
                "default": 0.7,
                "min": 0,
                "max": 2,
                "step": 0.1,
                "description": "Recommended by task category — Tools: 0.0-0.2 · Image: 0.2-0.4 · Helper: 0.3-0.6 · Chat: 0.7-0.9",
                "hide_for_embedding": True,
            },
            "max_tokens": {"type": "int", "label": "Max Tokens", "min": 0, "max": 100000, "hide_for_embedding": True},
            "chat_template": {
                "type": "text",
                "label": "Chat Template (optional)",
                "description": "Jinja chat_template — only set if the provider's tokenizer has no default template (some Infermatic / vLLM finetunes since transformers v4.44). Sent via extra_body.chat_template. Leave empty to use the provider default.",
            },
            "tasks": {
                "type": "task_order_list",
                "label": "Tasks",
                "description": "Tasks this LLM serves. Order is the fallback rank between LLMs that share the same task (1 = primary, 2 = fallback if primary unavailable). Use the + All <category> buttons below to bulk-add a whole task group.",
            },
        },
    },
    "embedding": {
        "label": "Embedding",
        "icon": "🔢",
        "fields": {
            "backend": {
                "type": "select",
                "label": "Backend",
                "choices": ["auto", "internal", "external"],
                "default": "auto",
                "description": "How pose-matching embeddings are produced. "
                               "auto = built-in model if no external embedding model is routed (works out of the box). "
                               "internal = always the built-in ONNX model (fastembed, CPU). "
                               "external = only the LLM-routed 'Pose Embedding' provider.",
            },
            "internal_model": {
                "type": "select",
                "label": "Internal Model",
                # Keys must match app.core.embedding.INTERNAL_MODELS.
                "choices": [
                    "BAAI/bge-small-en-v1.5",
                    "BAAI/bge-base-en-v1.5",
                    "sentence-transformers/all-MiniLM-L6-v2",
                    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                ],
                "default": "BAAI/bge-small-en-v1.5",
                "description": "Built-in embedding model (downloaded on first use, CPU). "
                               "Pose descriptions are normalized to short English, so a small "
                               "English model is enough. Only used when backend is internal/auto.",
            },
            "cache_dir": {
                "type": "str",
                "label": "Model Cache Dir",
                "default": "./models/fastembed",
                "description": "Where the built-in embedding model is downloaded/cached.",
            },
        },
    },
    "chat": {
        "label": "Chat / Anti-Repetition",
        "icon": "💬",
        "fields": {
            "frequency_penalty": {"type": "float", "label": "Frequency Penalty", "default": 0.3, "min": 0, "max": 2, "step": 0.05, "description": "Static token-repetition penalty sent to the chat model on every reply (OpenAI param). 0 = off, 0.3 = light, 0.6+ = strong. This is a global default ON TOP of the per-model base temperature configured in LLM Routing — not a per-model sampling value. Some backends ignore it."},
            "anti_rep_step": {"type": "float", "label": "Temperature bump per repetition", "default": 0.1, "min": 0, "max": 0.5, "step": 0.05, "description": "Reactive anti-loop: when the character repeats phrases across its recent replies, the temperature is raised by this amount PER detected repetition — added on top of the LLM Routing base temperature. Model-agnostic safety layer, NOT a static sampling value. 0 = disable the reactive bump."},
            "anti_rep_max": {"type": "float", "label": "Temperature ceiling", "default": 1.2, "min": 0.7, "max": 2, "step": 0.05, "description": "Upper bound for the reactively-raised temperature, so a repetition spiral cannot push it into pure chaos."},
            "anti_rep_lookback": {"type": "int", "label": "Repetition lookback (turns)", "default": 6, "min": 2, "max": 20, "description": "How many of the character's recent replies are fuzzy-checked for near-duplicates to drive the reactive temperature bump."},
        },
    },
    "memory": {
        "label": "Memory / Gedaechtnis",
        "icon": "🧠",
        "fields": {
            "short_term_days": {"type": "int", "label": "Kurzzeit (Tage)", "default": 3, "min": 1, "max": 14, "description": "Chat-History im Prompt (Stufe 1). Ab diesem Alter werden Episodics zu Tages-Summaries konsolidiert."},
            "mid_term_days": {"type": "int", "label": "Mittelzeit (Tage)", "default": 30, "min": 7, "max": 180, "description": "Ab diesem Alter werden Tages-Summaries zu Wochen-Summaries konsolidiert (Stufe 2 → 3)."},
            "long_term_days": {"type": "int", "label": "Langzeit (Tage)", "default": 90, "min": 30, "max": 365, "description": "Ab diesem Alter werden Wochen-Summaries zu Monats-Summaries konsolidiert."},
            "max_messages": {"type": "int", "label": "Max Nachrichten", "default": 100, "min": 10, "max": 500, "description": "Safety-Cap: Maximale Anzahl Chat-Nachrichten im Prompt."},
            "session_gap_hours": {"type": "int", "label": "Session-Bruch (Stunden)", "default": 4, "min": 0, "max": 24, "description": "Zeitluecke zwischen Turns, ab der die Chat-History abgeschnitten wird — Turns vor der letzten solchen Luecke wandern in die Session-Summary. 0 = deaktiviert."},
            "max_semantic": {"type": "int", "label": "Max Fakten", "default": 50, "min": 10, "max": 200, "description": "Maximale Anzahl semantischer Memories pro Character (Hard-Cap)."},
            "commitment_max_days": {"type": "int", "label": "Commitment Max-Alter (Tage)", "default": 5, "min": 1, "max": 30, "description": "Offene Commitments ohne 'completed'/'important'-Tag und importance<4 werden nach diesem Alter beim Cleanup entfernt."},
            "commitment_completed_days": {"type": "int", "label": "Erledigtes Commitment (Tage)", "default": 3, "min": 1, "max": 14, "description": "Erledigte Commitments (Tag 'completed') werden nach diesem Alter entfernt."},
        },
    },
    "image_generation": {
        "label": "Image Generation",
        "icon": "🎨",
        "fields": {
            "enabled": {"type": "bool", "label": "Aktiviert", "default": True},

            # --- Post-Processing Hand-off ---
            "postprocess_enabled": {"type": "bool", "label": "Post-Processing aktiviert", "default": False, "description": "Nach dem Erzeugen eines geeigneten Bildes einen externen Post-Processing-Dienst benachrichtigen. Der Dienst liest das Bild selbst (Galerie-API / Dateisystem) und schreibt das Ergebnis ueber den API-Endpoint zurueck. Dieses Programm bearbeitet keine Bilder selbst und sendet keine Bild-Bytes."},
            "postprocess_trigger_url": {"type": "str", "label": "Post-Processing Trigger URL", "default": "", "description": "Basis-URL, die nach der Erzeugung benachrichtigt wird. Das Programm haengt Parameter an (welt-relativer Bildpfad). Es werden KEINE Bild-Bytes gesendet. Beispiel: http://127.0.0.1:8005/trigger"},

            # --- Default backends ---
            "outfit_imagegen_default": {"type": "imagegen_select", "label": "Outfit/Preview Default (Match)", "description": "Backend-name glob (e.g. 'Flux*' or an exact name) — resolved by availability + cost, no fixed backend."},
            "expression_imagegen_default": {"type": "imagegen_select", "label": "Expression Default (Match)", "description": "Backend-name glob for mood/activity variants — resolved by availability + cost."},
            "location_imagegen_default": {"type": "imagegen_select", "label": "Location Default (Match)", "description": "Backend-name glob (e.g. 'Flux*') — resolved by availability + cost."},
            "scene_imagegen_default": {"type": "imagegen_select", "label": "Scene Render Default (Match)", "description": "Backend-name glob (e.g. 'Krea2') for the player's 'Rendered' environment view — composes the room background + present characters (expression images as references) into one image. Empty = location default."},
            "scene_render_mode": {"type": "select", "label": "Scene Render Mode", "choices": ["collage", "multi_ref"], "default": "collage", "description": "How the 'Rendered' view builds its request. 'collage' (recommended for edit workflows like Krea): the server pastes the figures onto the background at their live panel positions and sends ONE image — the model only blends lighting/shadows/edges. 'multi_ref': background + each person as separate reference images, pose from text — for backends with true identity conditioning."},
            # KEEP the two defaults IN SYNC with PROMPT_*_DEFAULT in app/core/scene_render.py.
            "scene_prompt_collage": {"type": "text", "label": "Scene Prompt (collage)", "default": "{label}: this is a rough photo composite — cut-out people were pasted onto a room photo. Rework it into ONE photorealistic photograph: relight every person to match the room's light sources and color temperature, add natural contact shadows and reflections, fix scale and perspective mismatches, and smooth all cut-out edges. Keep the room and keep each person's position, size, pose and identity unchanged — {count} in total, no additional people, no duplicates", "description": "Prompt template for the collage render mode. Placeholders: {label} = room name, {count} = e.g. 'exactly two people'. Action-first wording — edit models reproduce the input unless changes are COMMANDED. Tune per edit workflow without code changes."},
            "scene_prompt_multi_ref": {"type": "text", "label": "Scene Prompt (multi_ref)", "default": "{label}: the exact room from the first reference image, keeping the room layout, lighting and perspective. Compose {count} into the scene and NO ONE else — each person appears exactly once, no additional people, no duplicates. The person reference images provide IDENTITY ONLY (face, hair, body, outfit) — IGNORE the pose and background they show; each person's pose follows the text. People: {people}", "description": "Prompt template for the multi_ref render mode. Placeholders: {label} = room name, {count} = e.g. 'exactly two people', {people} = person list with reference bindings and poses. Tune per workflow (e.g. Qwen edit) without code changes."},
            "mapfit_imagegen_default": {"type": "imagegen_select", "label": "Map Fit/Match-edges target", "default": "", "description": "Imagegen target (backend-name glob) for 'Fit to neighbors' and 'Match edges'. Must resolve to a category=inpaint backend, which generates via POST /v1/images/edits (canvas + mask as two images)."},
            "map_tile_vision_analysis": {"type": "bool", "label": "Analyze neighbor tiles for map prompts", "default": False, "description": "For Fit/Match-edges: run a short vision-LLM analysis of each neighbour's ACTUAL 2D tile to build the north/south/east/west prompt (instead of the stored description, which drifts after regeneration). Cached per tile — re-analysed only when a tile changes. Costs one vision call per new tile."},

            # --- Prompt-Prefixes ---

            # --- Outfit-Bild Groesse ---
            "outfit_image_width": {
                "type": "int",
                "label": "Outfit Breite (px)",
                "default": 832,
                "min": 64,
                "max": 4096,
                "description": (
                    "Hochformat (~2:3) fuer Ganzkoerper-Outfits. Render-Zeit skaliert grob "
                    "linear mit der Pixelanzahl, deshalb sind nur Sprünge mit deutlichem "
                    "Performance-Effekt sinnvoll:\n"
                    "  - 640x960   (~0.6 MP — ca. 60% Zeit, fuer schnelle Iteration/Vorschau)\n"
                    "  - 832x1216  (~1.0 MP — Default, SDXL-/Flux-Sweet-Spot)\n"
                    "  - 1024x1536 (~1.6 MP — ca. 60% mehr Zeit/VRAM, mehr Detail)\n"
                    "Darüber hinaus (z.B. 1280x1920) waechst die Zeit weiter linear, der "
                    "Qualitaetsgewinn flacht aber ab und Repetitionsartefakte werden "
                    "wahrscheinlicher — fuer scharfe grosse Bilder besser einen Upscale-Pass "
                    "nachschalten."
                ),
            },
            "outfit_image_height": {
                "type": "int",
                "label": "Outfit Hoehe (px)",
                "default": 1216,
                "min": 64,
                "max": 4096,
                "description": "Siehe Outfit Breite fuer empfohlene Bucket-Kombinationen im selben Verhaeltnis.",
            },

            # --- Location-Background Groesse ---
            "location_image_width": {
                "type": "int",
                "label": "Location Background Width (px)",
                "default": 1280,
                "min": 256,
                "max": 4096,
                "description": (
                    "Width for newly generated location backgrounds (rooms, day/night variants, "
                    "event illustrations). Existing backgrounds are not re-rendered. The body CSS "
                    "uses background-size: contain — match the aspect ratio of the typical viewport "
                    "to avoid letterboxing. Examples: 1280x720 (16:9 HD), 1920x1080 (16:9 FHD), "
                    "2560x1080 (21:9 ultrawide). Larger sizes increase VRAM and render time."
                ),
            },
            "location_image_height": {
                "type": "int",
                "label": "Location Background Height (px)",
                "default": 720,
                "min": 256,
                "max": 4096,
                "description": "See Location Background Width.",
            },

            # --- Sonstiges ---
            "u2net_home": {"type": "str", "label": "U2Net Model Path", "default": "./models/u2net", "description": "Pfad fuer u2net-Modell (Hintergrundentfernung via rembg)"},
            "image_analysis_prompt": {
                "type": "text",
                "label": "Image Analysis Prompt",
                "description": "System prompt for objective post-generation image analysis (vision LLM, task image_analysis).",
                "default": (
                    "You are an expert image analyst. Provide a detailed and objective "
                    "description of the image (max 300 tokens) in flowing prose. Cover:\n"
                    "1. Overall scene: setting, environment, lighting, mood, composition.\n"
                    "2. Subjects: number of people, body type, hair, skin tone, facial "
                    "expression, pose.\n"
                    "3. Clothing: garments in detail (style, color, fit, condition).\n"
                    "4. Actions and interactions: what is happening, body positions.\n"
                    "5. Visual style: photographic, illustrated, 3D render, anime, etc. "
                    "Camera angle, depth of field, color palette.\n\n"
                    "Rules:\n"
                    "- Respond in fluent, descriptive English prose.\n"
                    "- If something is ambiguous or partially visible, describe it as such.\n"
                    "- Plain text only — no markdown."
                ),
            },
            "rebuild_llm_system_template": {
                "type": "text",
                "label": "Rebuild LLM System Prompt",
                "default": (
                    "You are an image prompt enhancer for the {target_model} image model. "
                    "{prompt_instruction} "
                    "Rewrite the following prompt in the style requested, keeping ALL factual content "
                    "(persons, outfits, pose, expression, scene, location, mood). "
                    "Do NOT add new visual elements, do NOT remove any. "
                    "Respond with ONLY the rewritten prompt, no preamble, no commentary."
                ),
                "description": "System prompt for the image-prompt-enhancer LLM. Placeholders: {target_model} (z_image/qwen/flux), {prompt_instruction} (from the use-case config).",
            },
        },
        "sub_arrays": {
            "use_cases": {
                "label": "Use-Cases (Styles)",
                "use_cases_editor": True,
            },
            "lora_triggers": {
                "label": "LoRA Library",
                "lora_triggers_editor": True,
            },
            "backends": {
                "label": "Backends",
                "item_label_field": "name",
                "sort_alphabetically": True,
                "master_detail": True,
                "list_columns": [
                    {"field": "name", "label": "Name"},
                    {"field": "api_type", "label": "Type"},
                    {"field": "enabled", "label": "Status", "kind": "status"},
                ],
                "fields": {
                    "name": {"half": True, "type": "str", "label": "Name", "required": True},
                    "lora_filter": {"half": True, "type": "str", "label": "LoRA Filter", "description": "Glob for this backend's LoRAs (e.g. 'Qwen*'). Applied by the discovery sync AND every LoRA dropdown — only matching LoRAs are stored/offered for this backend. Empty = all.", "applicable_for": ["localai", "openai_diffusion"]},
                    "category": {"type": "select", "label": "Category", "choices": ["generate", "inpaint"], "default": "generate", "triggers_rerender": True, "description": "Purpose category. 'generate' = standard generation via POST /v1/images/generations. 'inpaint' = generation via POST /v1/images/edits (canvas + mask as two images); the backend is offered as inpaint target in the map fit/edge dialog, and the alias workflow needs image + mask slots on the gateway side.", "applicable_for": ["openai_diffusion"]},
                    "enabled": {"type": "bool", "label": "Enabled", "default": True},
                    "api_type": {
                        "type": "select",
                        "label": "API Type",
                        "choices": ["a1111", "openai_chat", "openai_diffusion", "localai", "civitai", "together"],
                        "triggers_rerender": True,
                    },
                    "api_url": {"type": "str", "label": "API URL"},
                    "api_key": {"type": "password", "label": "API Key", "sensitive": True, "description": "Required for cloud backends (civitai, together) and the LLM gateway (openai_diffusion, always Bearer); optional for openai_chat/localai (e.g. LocalAI/vLLM without auth)", "applicable_for": ["openai_chat", "openai_diffusion", "localai", "civitai", "together"]},
                    "model": {"type": "imagegen_model", "label": "Model", "description": "Model ID, gateway generation alias (openai_diffusion) or URN (civitai: urn:air:sdxl:checkpoint:...). Free text + 'Load Models' fetches the list from the backend (/v1/models) as suggestions.", "applicable_for": ["openai_chat", "openai_diffusion", "localai", "civitai", "together"]},
                    "lora_url": {"type": "str", "label": "LoRA Query URL", "description": "Optional: endpoint that lists the LoRAs available for the model (GET -> {\"loras\": [...]}). Source for the LoRA-library discovery sync (hourly + on demand in the LoRA Library editor) — every LoRA dropdown feeds from the library. '{alias}' is replaced with the model name; without the placeholder '/v1/generations/<model>/loras' is appended. Example: http://192.168.8.10:4000", "applicable_for": ["openai_diffusion", "localai"]},
                    "cost": {"type": "int", "label": "Cost", "default": 0, "min": 0, "description": "Relative cost (0 = local/free, higher = more expensive)"},
                    "width": {
                        "type": "int",
                        "label": "Width",
                        "default": 800,
                        "min": 64,
                        "max": 4096,
                        "half": True,
                    },
                    "height": {
                        "type": "int",
                        "label": "Height",
                        "default": 800,
                        "min": 64,
                        "max": 4096,
                        "half": True,
                    },
                    "_size_note": {
                        "type": "note",
                        "text": (
                            "Square default format (~1:1). Render time scales roughly "
                            "linearly with the pixel count, so only jumps with a clear "
                            "performance effect are worthwhile:\n"
                            "  - 512x512   (~0.26 MP — ~30% time, fast iteration)\n"
                            "  - 768x768   (~0.59 MP — ~70% time, decent detail)\n"
                            "  - 1024x1024 (~1.05 MP — SDXL/Flux sweet spot)\n"
                            "  - 1280x1280 (~1.64 MP — ~60% more time/VRAM)\n"
                            "The default 800x800 sits between the buckets — pick one of the "
                            "above for best results. Above 1MP render time keeps growing "
                            "linearly while the quality gain flattens — for sharp large "
                            "images prefer an upscale pass afterwards."
                        ),
                    },
                    "image_family": {"type": "select", "label": "Image Family", "choices": ["", "natural", "keywords"], "description": "How the model wants its prompts: keywords = comma tags (Z-Image/SD), natural = flowing prose (Flux/Qwen). Selects the prompt adapter and which use-case style family applies. Empty = fallback via backend model name."},
                    "ref_slot_count": {"type": "number", "label": "Reference Slots", "default": 4, "description": "How many reference images this backend consumes per generation (slot priority: agent > room > others > items). 0 = no reference images.", "applicable_for": ["localai", "openai_diffusion"]},
                    "guidance_scale": {"type": "float", "label": "Guidance Scale", "min": 0, "max": 50, "step": 0.5, "applicable_for": ["a1111"]},
                    "num_inference_steps": {"type": "int", "label": "Inference Steps", "min": 1, "max": 200, "applicable_for": ["a1111", "together", "openai_diffusion", "localai"]},
                    "response_format": {"type": "select", "label": "Response Format", "choices": ["b64_json", "url"], "default": "b64_json", "description": "Wie das Gateway das Bild liefert. 'b64_json' (empfohlen): inline im JSON, ein Request. 'url': Result-URL, die mit demselben Bearer-Header abgeholt wird.", "applicable_for": ["openai_diffusion"]},
                    "extra_params": {"type": "text", "label": "Extra-Params (JSON)", "description": "Optionales JSON-Objekt mit zusaetzlichen Request-Parametern (z.B. {\"cfg\": 4.5, \"sampler\": \"euler\"}). Wird 1:1 in den Gateway-Request gemergt; ueberschreibt gleichnamige Defaults. Welche Keys gueltig sind, definiert der Alias-Workflow gateway-seitig. LoRAs NICHT hier eintragen — die kommen automatisch aus der LoRA-Library (lora_NN/strength_NN).", "applicable_for": ["openai_diffusion"]},
                    "prompt": {"visible_when": {"category": "inpaint"}, "type": "text", "label": "Default Prompt", "description": "Fallback prompt when the caller provides none (inpaint fill instruction). Also prefills the prompt field in the fit/edge dialog.", "applicable_for": ["openai_diffusion"]},
                    "full_mask": {"visible_when": {"category": "inpaint"}, "half": True, "type": "bool", "label": "Full mask", "default": True, "description": "Map blend: ON = mask the whole area (edit/gray-fill models like Qwen/Flux2). OFF = mask only the center/cell (fill models like Flux-Dev-Fill).", "applicable_for": ["openai_diffusion"]},
                    "terrain_hint": {"visible_when": {"category": "inpaint"}, "half": True, "type": "bool", "label": "Terrain hint", "default": False, "description": "ON = a dynamic terrain description of the neighbors is appended to the prompt (fill models). OFF = don't append (edit models see the gray canvas themselves).", "applicable_for": ["openai_diffusion"]},
                    "mask_grow": {"visible_when": {"category": "inpaint"}, "half": True, "type": "float", "label": "Mask grow", "default": 1.05, "min": 1.0, "max": 1.5, "step": 0.01, "description": "Mask border factor: how far the mask extends beyond the cell/seam (1.05 = +5%, 1.02 = +2%).", "applicable_for": ["openai_diffusion"]},
                    "inner_crop": {"visible_when": {"category": "inpaint"}, "half": True, "type": "float", "label": "Inner crop", "default": 0.7, "min": 0.05, "max": 1.0, "step": 0.05, "description": "With Full mask (Fit) only: share of the center that gets cut out (0.7 = inner 70%, 1.0 = whole center). Not applied for Match Edges.", "applicable_for": ["openai_diffusion"]},
                    "mask_format": {"visible_when": {"category": "inpaint"}, "type": "select", "label": "Mask format", "choices": ["grayscale", "openai"], "default": "grayscale", "description": "How the inpaint mask reaches the gateway. 'grayscale' (recommended): the L-PNG is sent 1:1 as generated, white = edit region (byte-identical to mapblend_debug/last_mask.png). 'openai': RGBA with transparent = edit, for true OpenAI/DALL-E edits endpoints.", "applicable_for": ["openai_diffusion"]},
                    "disable_safety": {"type": "bool", "label": "Disable safety", "default": False, "description": "Sends disable_safety_checker=true (Together.ai-specific).", "applicable_for": ["together"]},
                    "poll_interval": {"half": True, "type": "float", "label": "Poll Interval (s)", "default": 3.0, "min": 0.5, "step": 0.5, "description": "Wait time between status polls on async cloud backends (CivitAI, Together): lower = faster detection, but more API calls.", "applicable_for": ["civitai", "together"]},
                    "max_wait": {"half": True, "type": "int", "label": "Max Wait (s)", "default": 300, "min": 30, "description": "Maximum wait time before the generation counts as failed.", "applicable_for": ["civitai", "together"]},
                    "timeout": {"type": "int", "label": "Timeout (s)", "default": 120, "min": 10, "max": 3600, "description": "Request timeout for the image generation (HTTP). Raise it for slow models/large images — be generous with the synchronous gateway (e.g. 300). Applies to together/openai_diffusion/localai/openai_chat.", "applicable_for": ["together", "openai_diffusion", "localai", "openai_chat"]},
                    "max_concurrent": {"half": True, "type": "int", "label": "Max Concurrent", "default": 1, "min": 1, "max": 50, "description": "Parallel jobs on this backend queue. Additional concurrent requests wait until a slot frees up. Applies to all backend types (including cloud/OpenAI)."},
                    "serialize_group": {"half": True, "type": "str", "label": "Serialize Group", "description": "Channels with the same group run strictly one at a time (e.g. LLM + image backend sharing one GPU). Empty = no serialization."},
                },
            },
        },
    },
    "animation": {
        "label": "Animation (Video)",
        "icon": "🎬",
        "subsections": {
            "together": {
                "label": "Together.ai Animation",
                "fields": {
                    "enabled": {"type": "bool", "label": "Aktiviert", "default": False},
                    "label": {"type": "str", "label": "Anzeigename"},
                    "api_key": {"type": "password", "label": "API Key", "sensitive": True, "description": "Leer = wird aus Together-Provider API Key gelesen"},
                    "model": {"type": "str", "label": "Model"},
                    "width": {"type": "int", "label": "Breite", "default": 720, "description": "Kling 2.1: 1280x720, 720x1280 oder 720x720"},
                    "height": {"type": "int", "label": "Höhe", "default": 720},
                    "seconds": {"type": "int", "label": "Dauer (s)", "default": 5, "min": 1, "max": 30},
                    "poll_interval": {"type": "float", "label": "Poll Interval (s)", "default": 5.0, "step": 0.5},
                    "max_wait": {"type": "int", "label": "Max Wait (s)", "default": 600},
                },
            },
        },
    },
    "tts": {
        "label": "Text-to-Speech",
        "icon": "🔊",
        "fields": {
            "enabled": {"type": "bool", "label": "TTS Aktiviert", "default": False},
            "auto": {"type": "bool", "label": "Auto-TTS", "default": False, "description": "Automatisch Audio generieren fuer jede Antwort"},
            "chunk_size": {"type": "int", "label": "Chunk Size (Zeichen)", "default": 300, "min": 0, "description": "Audio ab dieser Zeichenanzahl erzeugen (0 = ein Audio nach komplettem Text)"},
            "backend": {
                "type": "select",
                "label": "Backend",
                "choices": ["xtts", "f5", "magpie"],
                "default": "xtts",
            },
            "fallback_backend": {
                "type": "select",
                "label": "Fallback Backend",
                "choices": ["", "xtts", "f5", "magpie"],
                "default": "",
                "description": "Falls primaeres Backend nicht erreichbar",
            },
        },
        "subsections": {
            "xtts": {
                "label": "XTTS v2",
                "fields": {
                    "url": {"type": "str", "label": "XTTS URL", "default": "http://localhost:8020"},
                    "speaker_wav": {"type": "str", "label": "Speaker WAV", "description": "Eigene WAV oder built-in: calm_female, female, male"},
                    "language": {"type": "str", "label": "Sprache", "default": "de"},
                },
            },
            "magpie": {
                "label": "Magpie (NVIDIA Riva)",
                "fields": {
                    "url": {"type": "str", "label": "Magpie URL", "default": "http://localhost:9000"},
                    "voice": {"type": "str", "label": "Stimme", "description": "Format: Magpie-Multilingual.{LANG}.{Name}[.{Emotion}]"},
                    "language": {"type": "str", "label": "Sprache", "default": "de-DE"},
                },
            },
            "f5": {
                "label": "F5-TTS",
                "fields": {
                    "url": {"type": "str", "label": "F5 URL", "default": "http://localhost:7860"},
                    "ref_audio": {"type": "str", "label": "Referenz Audio", "description": "Pfad zur WAV-Datei fuer Voice Cloning (5-8 Sekunden empfohlen)"},
                    "ref_text": {"type": "str", "label": "Referenz Text", "description": "Transkription des Referenz-Audios (leer = auto-detect)"},
                    "speed": {"type": "float", "label": "Geschwindigkeit", "default": 1.0, "min": 0.1, "max": 3.0, "step": 0.1, "description": "1.0 = normal"},
                    "remove_silence": {"type": "bool", "label": "Stille entfernen", "default": False},
                    "nfe_steps": {"type": "int", "label": "NFE Steps", "default": 32, "min": 1, "max": 64, "description": "Mehr = bessere Qualitaet, langsamer"},
                    "custom_cfg": {"type": "text", "label": "Custom Config (JSON)", "description": "Base-Architektur Config fuer alle Custom-Modelle"},
                },
            },
        },
    },
    "skills": {
        "label": "Skills",
        "icon": "🛠",
        "subsections": {
            "searx": {
                "label": "SearX Web Search",
                "fields": {
                    "enabled": {"type": "bool", "label": "Aktiviert", "default": False},
                    "url": {"type": "str", "label": "SearX URL"},
                    "engines": {"type": "str", "label": "Engines", "default": "google,duckduckgo,bing", "description": "Kommaseparierte Suchmaschinen"},
                    "categories": {"type": "str", "label": "Kategorien", "default": "general"},
                    "num_results": {"type": "int", "label": "Max Ergebnisse", "default": 5, "min": 1, "max": 50},
                },
            },
            "instagram": {
                "label": "Instagram",
                "fields": {
                    "enabled": {"type": "bool", "label": "Aktiviert", "default": False},
                    "caption_language": {"type": "select", "label": "Caption Sprache", "choices": ["de", "en", "fr", "es", "it"], "default": "en"},
                    "default_popularity": {"type": "int", "label": "Default Popularität", "default": 50, "min": 0, "max": 100, "description": "Default-Popularitaet fuer neue Characters (0-100%, per-Character ueberschreibbar)"},
                    "imagegen_default": {"type": "imagegen_select", "label": "Default ImageGen"},
                    "pending_window_hours": {"type": "int", "label": "Recent-Posts Window (h)", "default": 4, "min": 1, "max": 72, "description": "Wie lange neue Instagram-Posts als 'pending' im Agent-Thought-Prompt sichtbar sind (Stunden). Standardwert 4."},
                },
            },
            "set_location": {
                "label": "SetLocation",
                "fields": {
                    "enabled": {"type": "bool", "label": "Aktiviert", "default": True},
                },
            },
            "set_pose": {
                "label": "SetPose",
                "fields": {
                    "enabled": {"type": "bool", "label": "Aktiviert", "default": True},
                },
            },
            "set_mood": {
                "label": "SetMood",
                "fields": {
                    "enabled": {"type": "bool", "label": "Aktiviert", "default": True},
                },
            },
            "talk_to": {
                "label": "TalkTo (face-to-face)",
                "fields": {
                    "enabled": {"type": "bool", "label": "Aktiviert", "default": True},
                },
            },
            "send_message": {
                "label": "SendMessage (remote)",
                "fields": {
                    "enabled": {"type": "bool", "label": "Aktiviert", "default": True},
                },
            },
            "outfit_change": {
                "label": "Outfit Change",
                "fields": {
                    "generate_image": {"type": "bool", "label": "Bild generieren", "default": True},
                    "language": {"type": "select", "label": "Sprache", "choices": ["de", "en"], "default": "en"},
                    "max_outfits": {"type": "int", "label": "Max Outfits", "default": 10, "min": 1, "max": 100, "description": "Maximale Anzahl gespeicherter Outfits pro Character (aelteste werden entfernt)"},
                    "cooldown_minutes": {"type": "int", "label": "Outfit-Cooldown (Min)", "default": 120, "min": 0, "max": 1440, "description": "Minuten bis ein LLM-gesteuerter Outfit-Wechsel am gleichen Ort moeglich ist. 0 = kein Cooldown. Gilt nicht bei Location-Wechsel oder User-Anfrage."},
                },
            },
            "markdown_writer": {
                "label": "Markdown Writer",
                "fields": {
                    "folders": {"type": "str", "label": "Ordner (kommasepariert)", "default": "diary,notes,guides"},
                    "default_folder": {"type": "str", "label": "Default Ordner", "default": "diary"},
                    "max_size_kb": {"type": "int", "label": "Max Größe (KB)", "default": 512, "min": 1},
                    "max_files": {"type": "int", "label": "Max Dateien", "default": 50, "min": 1},
                },
            },
        },
    },
    "knowledge": {
        "label": "Knowledge System",
        "icon": "📚",
        "fields": {
            "max_prompt_entries": {"type": "int", "label": "Max Prompt Entries", "default": 20, "min": 1, "description": "Max Eintraege im System-Prompt (Token-Budget)"},
            "max_entries": {"type": "int", "label": "Max Entries", "default": 200, "min": 1, "description": "Max gespeicherte Eintraege pro Character (Sliding Window)"},
            "daily_summary_days": {"type": "int", "label": "Daily Summary Tage", "default": 7, "min": 1, "description": "Anzahl vergangene Tage im System-Prompt"},
            "batch_size": {"type": "int", "label": "Batch Size", "default": 5, "min": 1},
            "max_input_tokens": {"type": "int", "label": "Max Input Tokens", "default": 12000, "min": 100},
            "max_output_tokens": {"type": "int", "label": "Max Output Tokens", "default": 1500, "min": 100},
            "search_max_candidates": {"type": "int", "label": "Search Max Candidates", "default": 50, "min": 1},
            "search_max_return": {"type": "int", "label": "Search Max Return", "default": 8, "min": 1},
        },
    },
    "relationships": {
        "label": "Relationships",
        "icon": "❤",
        "fields": {
            "summary_enabled": {"type": "bool", "label": "Summaries Aktiviert", "default": True, "description": "Periodische Zusammenfassung der Beziehungen"},
            "summary_interval_minutes": {"type": "int", "label": "Summary Interval (min)", "default": 120, "min": 10},
        },
    },
    "social_reactions": {
        "label": "Social Reactions",
        "icon": "👥",
        "fields": {
            "enabled": {"type": "bool", "label": "Aktiviert", "default": True, "description": "Wenn ein Character postet, reagieren andere Characters (Background-Queue)"},
        },
    },
    "thoughts": {
        "label": "Gedanken",
        "icon": "🧠",
        "fields": {
            "min_turn_gap_seconds": {"type": "int", "label": "Min Turn Gap (s)", "default": 30, "min": 0, "max": 600, "description": "Mindest-Pause (Sekunden) zwischen zwei aufeinanderfolgenden Thought-Turns. Verhindert dass der AgentLoop bei wenigen Charakteren zu eng taktet. Gilt nicht fuer in_chat_skip / Fehler (die haben eigene Backoffs)."},
            "min_per_char_cooldown_minutes": {"type": "int", "label": "Min Per-Char Cooldown (min)", "default": 5, "min": 0, "max": 240, "description": "Mindest-Wartezeit (Minuten) bevor derselbe Charakter wieder einen echten Thought-Turn bekommt. Bumps (externe Trigger wie Avatar-Roomentry) umgehen den Cooldown."},
        },
    },
    "random_events": {
        "label": "Zufaellige Events",
        "icon": "🎲",
        "fields": {
            "enabled": {"type": "bool", "label": "Aktiviert", "default": True, "description": "Automatische Event-Generierung an besetzten Locations"},
            "base_probability": {"type": "int", "label": "Basis-Wahrscheinlichkeit %", "default": 0, "min": 0, "max": 50, "description": "Wahrscheinlichkeit pro Stunde pro Location. Pro Location ueberschreibbar."},
            "entry_roll_enabled": {"type": "bool", "label": "Roll-on-Entry", "default": True, "description": "Sofort wuerfeln wenn ein Avatar/Character eine Location betritt — zusaetzlich zum stuendlichen Tick. Macht 'beim Betreten passiert was' moeglich."},
            "entry_roll_cooldown_minutes": {"type": "int", "label": "Entry Cooldown (min)", "default": 10, "min": 0, "max": 120, "description": "Mindestabstand zwischen zwei Roll-on-Entry-Wuerfen pro (Character, Location). Verhindert Wuerfel-Spam beim schnellen Rein-Raus."},
            "entry_roll_jitter_seconds": {"type": "int", "label": "Entry Jitter (s)", "default": 3, "min": 0, "max": 30, "description": "Zufaellige Verzoegerung 0–N Sekunden bevor das Event nach Eintritt aufploppt. 0 = sofort, sonst fuehlt es sich an als wuerde was 'passieren' nach Ankunft."},
            "resolution_proactive": {"type": "bool", "label": "Proaktive Event-Aufloesung", "default": True, "description": "Characters an betroffener Location versuchen offene disruption/danger Events automatisch zu loesen (alle 5 Min)."},
            "resolution_cooldown_minutes": {"type": "int", "label": "Resolution Cooldown (min)", "default": 15, "min": 1, "max": 240, "description": "Mindestabstand zwischen zwei Loesungsversuchen am gleichen Event."},
            "event_imagegen_default": {"type": "imagegen_select", "label": "Event Illustration Default Backend", "description": "Backend-name glob used to render disruption/danger event illustrations that swap the location background while the event is active."},
            "resolved_image_linger_minutes": {"type": "int", "label": "Resolved-Image Linger (min)", "default": 30, "min": 0, "max": 240, "description": "How long the 'after' illustration of a resolved disruption/danger event keeps overriding the normal location background before reverting."},
        },
    },
    "story_engine": {
        "label": "Story Engine",
        "icon": "📖",
        "fields": {
            "enabled": {"type": "bool", "label": "Aktiviert", "default": False, "description": "Story Arc Fortschritt (Background-Prozess)"},
            "max_active_arcs": {"type": "int", "label": "Max Active Arcs", "default": 2, "min": 1, "description": "Maximale aktive Arcs pro User"},
            "cooldown_hours": {"type": "int", "label": "Cooldown (Stunden)", "default": 6, "min": 1, "description": "Mindest-Cooldown zwischen Arc-Advances pro User"},
            "max_beats": {"type": "int", "label": "Max Beats", "default": 5, "min": 1, "description": "Maximale Beats pro Arc bevor Aufloesung"},
            "beat_images": {"type": "bool", "label": "Beat Bilder", "default": True, "description": "Bilder pro Story-Beat generieren"},
            "imagegen_default": {"type": "imagegen_select", "label": "Default ImageGen"},
        },
    },
    "ui": {
        "label": "UI / Themes & Image Downscaling",
        "icon": "🎨",
        "fields": {
            "default_theme": {
                "type": "select",
                "label": "Default Theme",
                "choices": ["default", "minimal", "dark"],
            },
            "available_themes": {"type": "str", "label": "Verfügbare Themes", "default": "default,minimal,dark"},
            "_grp_downscale": {"type": "group_header", "label": "Image Downscaling"},
            "downscale_enabled": {
                "type": "bool",
                "label": "Downscale enabled",
                "default": True,
                "description": "Re-encode generated item and map-icon images at a lower resolution after the backend returns them. Location backgrounds (day/night/scene) keep their full resolution; only the on-disk copy shrinks.",
            },
            "downscale_item_max_dim": {
                "type": "int",
                "label": "Item max dimension (px)",
                "default": 512,
                "min": 128,
                "max": 4096,
                "description": "Longest side after downscale for item images (shared/items/). Aspect ratio preserved, PNG/alpha intact (rembg output not damaged).",
            },
            "downscale_map_max_dim": {
                "type": "int",
                "label": "Map icon max dimension (px)",
                "default": 400,
                "min": 128,
                "max": 2048,
                "description": "Longest side for map-icon thumbnails (gallery images tagged image_type=map). Used for the world overview map. 400 px is plenty for the in-game tile view.",
            },
            "_grp_migrate": {"type": "group_header", "label": "Migrate existing images"},
            "_action_dryrun_items_current": {
                "type": "button",
                "label": "Dry-run (items, this world + shared)",
                "endpoint": "/admin/image-postprocess/dryrun?scope=item&world_scope=current",
                "method": "POST",
                "description": "Scan shared/items/ + the active world's worlds/<w>/items/ without writing. Outfit-pieces and other items both live there.",
            },
            "_action_dryrun_items_all": {
                "type": "button",
                "label": "Dry-run (items, ALL worlds + shared)",
                "endpoint": "/admin/image-postprocess/dryrun?scope=item&world_scope=all",
                "method": "POST",
                "description": "Scan shared/items/ + every per-world items dir.",
            },
            "_action_dryrun_maps_current": {
                "type": "button",
                "label": "Dry-run (map icons, this world)",
                "endpoint": "/admin/image-postprocess/dryrun?scope=map&world_scope=current",
                "method": "POST",
                "description": "Scan map-tagged images of the active world only. Backgrounds are ignored.",
            },
            "_action_dryrun_maps_all": {
                "type": "button",
                "label": "Dry-run (map icons, ALL worlds)",
                "endpoint": "/admin/image-postprocess/dryrun?scope=map&world_scope=all",
                "method": "POST",
                "description": "Scan map-tagged images across every world under worlds/. Use sparingly.",
            },
            "_action_migrate_items_current": {
                "type": "button",
                "label": "Migrate items now (this world + shared)",
                "endpoint": "/admin/image-postprocess/migrate?scope=item&world_scope=current",
                "method": "POST",
                "confirm": "Re-encode item images in shared/items/ + the active world's items dir. Originals are not kept. Continue?",
            },
            "_action_migrate_items_all": {
                "type": "button",
                "label": "Migrate items now (ALL worlds + shared)",
                "endpoint": "/admin/image-postprocess/migrate?scope=item&world_scope=all",
                "method": "POST",
                "confirm": "Re-encode item images across shared/ AND every per-world items dir. Continue?",
            },
            "_action_migrate_maps_current": {
                "type": "button",
                "label": "Migrate map icons now (this world)",
                "endpoint": "/admin/image-postprocess/migrate?scope=map&world_scope=current",
                "method": "POST",
                "confirm": "Re-encode all map-tagged images of the ACTIVE world in place. Day/Night/Scene backgrounds are NOT touched. Continue?",
            },
            "_action_migrate_maps_all": {
                "type": "button",
                "label": "Migrate map icons now (ALL worlds)",
                "endpoint": "/admin/image-postprocess/migrate?scope=map&world_scope=all",
                "method": "POST",
                "confirm": "Re-encode map-tagged images across EVERY world under worlds/. This affects all worlds at once. Continue?",
            },
        },
    },
    "content_marketplace": {
        "label": "Content Marketplace",
        "icon": "📦",
        "fields": {
            "cache_ttl_minutes": {
                "type": "int",
                "label": "Cache TTL (minutes)",
                "default": 60,
                "min": 0,
                "max": 1440,
                "description": "How long each catalog response is cached locally. 0 = always re-fetch.",
            },
            "allow_install_url": {
                "type": "bool",
                "label": "Allow ad-hoc URL install",
                "default": False,
                "description": "Permit installing a pack from any URL (not just catalog entries). Off by default.",
            },
        },
        "sub_arrays": {
            "catalogs": {
                "label": "Catalogs",
                "item_label_field": ["name", "url"],
                "fields": {
                    "name": {
                        "type": "str",
                        "label": "Display name",
                        "default": "",
                        "description": "Shown in the marketplace dropdown.",
                    },
                    "url": {
                        "type": "str",
                        "label": "Catalog URL",
                        "default": "",
                        "description": "Catalog repo URL — pack list is discovered via the hosting API. Examples: https://github.com/<org>/<repo> — or Forgejo: http(s)://<host>/<owner>/<repo>. Legacy raw …/index.json URLs are still accepted for backwards compatibility.",
                    },
                    "auth_token": {
                        "type": "password",
                        "label": "Auth token",
                        "sensitive": True,
                        "default": "",
                        "description": "Optional. PAT for private repos. Bare token gets prepended with 'token '; an already-prefixed value (e.g. 'Bearer xyz') is used as-is. Sent to both catalog and download URLs of this entry.",
                    },
                    "enabled": {
                        "type": "bool",
                        "label": "Enabled",
                        "default": True,
                    },
                },
            },
        },
    },
    "messaging_frame": {
        "label": "Messaging-Frame (Phone-Chat-Layout)",
        "icon": "📱",
        "fields": {
            "prompt": {
                "type": "text",
                "label": "Bild-Prompt",
                "default": "photorealistic modern smartphone, isolated on white, screen is pure chroma green, centered, no person, no reflection, top-down product photo",
                "description": "Beschreibung des Frames. Wichtig: 'pure green screen' / 'chroma green' fuer die Anzeigeflaeche — sonst kann der Chroma-Key sie nicht erkennen. Beispiel Fantasy: 'ornate magical mirror, gold frame, mirror surface pure green, no reflection'",
            },
            "target": {
                "type": "imagegen_target_select",
                "label": "Backend",
                "description": "Which image backend renders the frame. Each backend uses its configured model name. Offline options are greyed out.",
            },
            "_grp_actions": {"type": "group_header", "label": "Aktion"},
            "_action_generate": {
                "type": "button",
                "label": "Frame generieren",
                "endpoint": "/world/messaging-frame/generate",
                "method": "POST",
                "body_from": ["prompt", "target"],
                "preview_url": "/world/messaging-frame.png",
                "description": "Generiert das Frame-Bild via konfiguriertem Image-Backend (~30-90s). Das alte Bild wird ueberschrieben. Im Fehlerfall (Green-Region nicht erkennbar) Prompt anpassen und erneut versuchen.",
            },
            "_preview": {
                "type": "image_preview",
                "label": "Aktuelles Frame",
                "url": "/world/messaging-frame.png",
                "meta_url": "/world/messaging-frame",
                "description": "Aktuell gespeichertes Frame (transparente Anzeigeflaeche im Browser ggf. als Schachbrett sichtbar).",
            },
            "_action_delete": {
                "type": "button",
                "label": "Frame entfernen",
                "endpoint": "/world/messaging-frame",
                "method": "DELETE",
                "confirm": "Frame wirklich entfernen? Das Phone-Chat-Layout faellt dann auf den Default-CSS-Frame zurueck.",
            },
        },
    },
}


def get_schema() -> dict:
    """Return the full schema for the admin API."""
    return SECTIONS


def iter_restart_required_paths() -> list:
    """Sammelt alle Schema-Pfade mit `requires_restart: true`.

    Liefert eine Liste von dot-notation Pfaden, die einem geladenen Config-Dict
    entsprechen — z.B. ``server.jwt_secret`` oder
    ``providers[*].api_url`` (Wildcard fuer alle Array-Items).
    """
    paths = []

    def _walk_fields(fields: dict, prefix: str) -> None:
        for fkey, fdef in (fields or {}).items():
            if not isinstance(fdef, dict):
                continue
            if fdef.get("requires_restart") is True:
                paths.append(f"{prefix}.{fkey}" if prefix else fkey)

    for skey, sdef in SECTIONS.items():
        if not isinstance(sdef, dict):
            continue
        if sdef.get("is_array") or sdef.get("is_dict"):
            _walk_fields(sdef.get("fields"), f"{skey}[*]")
            for arrkey, arrdef in (sdef.get("sub_arrays") or {}).items():
                _walk_fields(arrdef.get("fields"), f"{skey}[*].{arrkey}[*]")
        else:
            _walk_fields(sdef.get("fields"), skey)
            for arrkey, arrdef in (sdef.get("sub_arrays") or {}).items():
                _walk_fields(arrdef.get("fields"), f"{skey}.{arrkey}[*]")
    return paths
