"""Markdown-writer package — lets a character write markdown files.

The character can:
- Create new .md files (diary, summaries, guides, etc.)
- Continue / extend existing files
- Remember its most recent files and keep writing later
- Write into configurable folders (several possible)

A per-character index (recent_files.json) tracks the most recently edited
files so the agent can seamlessly continue earlier texts.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.timeutils import parse_iso, utc_now, utc_now_iso
from app.core.tool_formats import format_example
from app.models.character import get_character_dir

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec

# Max. number of tracked recent files per character
MAX_RECENT_FILES = 20


class MarkdownWriterSkill(PluginSkill):
    """Skill for creating and continuing markdown files.

    Input format (JSON):
        {
            "action": "write" | "append" | "list" | "read",
            "folder": "diary" | "guides" | ... (configured folder name),
            "filename": "my-diary.md" (optional for write - auto-generated),
            "title": "Diary entry March 15" (optional, for new files),
            "content": "The markdown content ..."
        }

    Actions:
        write   - Create a new file or OVERWRITE an existing one
        append  - Append to an existing file (or create a new one)
        list    - Show the character's recent files in a folder
        read    - Read an existing file (to continue writing)
    """

    SKILL_ID = "markdown_writer"
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description come from templates/llm/skills/markdown_writer.md
        # Per-character defaults seeded from the world config (config_schema).
        self._defaults = {
            "enabled": True,
            "folders": ctx.get_config("skills.markdown_writer.folders", "diary,notes,guides"),
            "max_file_size_kb": ctx.get_config("skills.markdown_writer.max_size_kb", 512),
            "max_files_per_folder": ctx.get_config("skills.markdown_writer.max_files", 50),
            "default_folder": ctx.get_config("skills.markdown_writer.default_folder", "diary"),
        }

    def get_config_fields(self) -> dict:
        return {
            "folders": {
                "type": "str",
                "default": self._defaults["folders"],
                "label": "Available folders (comma-separated)",
            },
            "max_file_size_kb": {
                "type": "int",
                "default": self._defaults["max_file_size_kb"],
                "label": "Max file size (KB)",
            },
            "max_files_per_folder": {
                "type": "int",
                "default": self._defaults["max_files_per_folder"],
                "label": "Max files per folder",
            },
            "default_folder": {
                "type": "str",
                "default": self._defaults["default_folder"],
                "label": "Default folder",
            },
        }

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _get_base_dir(self, character_name: str) -> Path:
        """Base directory for a character's markdown files."""
        return get_character_dir(character_name) / "documents"

    def _get_folder_path(self, character_name: str, folder: str) -> Optional[Path]:
        """Return the path of a configured folder (or None)."""
        cfg = self._get_effective_config(character_name)
        allowed = [f.strip() for f in cfg.get("folders", "diary").split(",") if f.strip()]
        folder_clean = folder.strip().lower()

        if folder_clean not in [f.lower() for f in allowed]:
            return None

        # Keep the original (cased) name
        for f in allowed:
            if f.lower() == folder_clean:
                folder_clean = f
                break

        path = self._get_base_dir(character_name) / folder_clean
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _get_allowed_folders(self, character_name: str) -> List[str]:
        """Return the configured folder names."""
        cfg = self._get_effective_config(character_name)
        return [f.strip() for f in cfg.get("folders", "diary").split(",") if f.strip()]

    # ------------------------------------------------------------------
    # Recent-files tracking
    # ------------------------------------------------------------------

    def _get_recent_files_path(self, character_name: str) -> Path:
        base = self._get_base_dir(character_name)
        base.mkdir(parents=True, exist_ok=True)
        return base / "recent_files.json"

    def _load_recent_files(self, character_name: str) -> List[Dict[str, str]]:
        path = self._get_recent_files_path(character_name)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_recent_files(self, character_name: str, entries: List[Dict[str, str]]):
        path = self._get_recent_files_path(character_name)
        # Keep only the last MAX_RECENT_FILES
        entries = entries[-MAX_RECENT_FILES:]
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    def _track_file(self, character_name: str, folder: str,
                    filename: str, title: str, action: str):
        """Add a file to the recent tracking, or update it."""
        entries = self._load_recent_files(character_name)

        # Update the existing entry or add a new one
        found = False
        for entry in entries:
            if entry.get("folder") == folder and entry.get("filename") == filename:
                entry["last_modified"] = utc_now_iso()
                entry["last_action"] = action
                if title:
                    entry["title"] = title
                found = True
                break

        if not found:
            entries.append({
                "folder": folder,
                "filename": filename,
                "title": title or filename,
                "created": utc_now_iso(),
                "last_modified": utc_now_iso(),
                "last_action": action,
            })

        self._save_recent_files(character_name, entries)

    # ------------------------------------------------------------------
    # Filename helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize a filename (safe characters only)."""
        # Remove unsafe characters
        name = re.sub(r'[^\w\s\-.]', '', name)
        name = re.sub(r'\s+', '-', name.strip())
        name = name.strip('-.')
        if not name:
            name = "document"
        # Ensure the .md extension
        if not name.lower().endswith('.md'):
            name += '.md'
        return name

    @staticmethod
    def _generate_filename(title: str = "", folder: str = "") -> str:
        """Generate a filename based on the date and an optional title."""
        date_str = utc_now().strftime("%Y-%m-%d")
        if title:
            slug = re.sub(r'[^\w\s\-]', '', title)
            slug = re.sub(r'\s+', '-', slug.strip()).lower()[:40]
            return f"{date_str}_{slug}.md"
        return f"{date_str}_{folder or 'doc'}.md"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_write(self, character_name: str, folder: str,
                      filename: str, title: str, content: str, cfg: dict) -> str:
        """Create a new file or overwrite an existing one."""
        folder_path = self._get_folder_path(character_name, folder)
        if not folder_path:
            allowed = self._get_allowed_folders(character_name)
            return f"Error: folder '{folder}' not allowed. Allowed: {', '.join(allowed)}"

        if not content:
            return "Error: content must not be empty."

        # Filename
        if not filename:
            filename = self._generate_filename(title, folder)
        filename = self._sanitize_filename(filename)

        # Check limit: number of files
        max_files = cfg.get("max_files_per_folder", 50)
        existing = list(folder_path.glob("*.md"))
        file_path = folder_path / filename
        if not file_path.exists() and len(existing) >= max_files:
            return f"Error: maximum of {max_files} files in '{folder}' reached."

        # Assemble the content
        md_content = ""
        if title:
            md_content = f"# {title}\n\n"
        md_content += content

        # Check size
        max_kb = cfg.get("max_file_size_kb", 512)
        if len(md_content.encode("utf-8")) > max_kb * 1024:
            return f"Error: content exceeds the {max_kb} KB limit."

        file_path.write_text(md_content, encoding="utf-8")
        self._track_file(character_name, folder, filename, title, "write")

        self.ctx.logger.info("%s wrote file: %s/%s", character_name, folder, filename)
        return f"File written: {folder}/{filename} ({len(md_content)} characters)"

    def _action_append(self, character_name: str, folder: str,
                       filename: str, title: str, content: str, cfg: dict) -> str:
        """Append to an existing file or create a new one."""
        folder_path = self._get_folder_path(character_name, folder)
        if not folder_path:
            allowed = self._get_allowed_folders(character_name)
            return f"Error: folder '{folder}' not allowed. Allowed: {', '.join(allowed)}"

        if not content:
            return "Error: content must not be empty."

        if not filename:
            # Try to find the most recently edited file in the folder
            recent = self._load_recent_files(character_name)
            folder_recent = [r for r in recent if r.get("folder") == folder]
            if folder_recent:
                filename = folder_recent[-1]["filename"]
            else:
                filename = self._generate_filename(title, folder)

        filename = self._sanitize_filename(filename)
        file_path = folder_path / filename

        # Limit: new file?
        max_files = cfg.get("max_files_per_folder", 50)
        if not file_path.exists():
            existing = list(folder_path.glob("*.md"))
            if len(existing) >= max_files:
                return f"Error: maximum of {max_files} files in '{folder}' reached."

        # Load existing content
        existing_content = ""
        if file_path.exists():
            existing_content = file_path.read_text(encoding="utf-8")

        # Append
        separator = "\n\n---\n\n" if existing_content else ""
        if title and not existing_content:
            new_part = f"# {title}\n\n{content}"
        else:
            new_part = content

        final = existing_content + separator + new_part

        # Check size
        max_kb = cfg.get("max_file_size_kb", 512)
        if len(final.encode("utf-8")) > max_kb * 1024:
            return f"Error: the file would exceed {max_kb} KB. Create a new file."

        file_path.write_text(final, encoding="utf-8")
        self._track_file(character_name, folder, filename, title, "append")

        self.ctx.logger.info("%s appended to file: %s/%s", character_name, folder, filename)
        return f"Appended to: {folder}/{filename} ({len(final)} characters total)"

    def _action_list(self, character_name: str, folder: str) -> str:
        """List the recent files of a folder."""
        if folder:
            folder_path = self._get_folder_path(character_name, folder)
            if not folder_path:
                allowed = self._get_allowed_folders(character_name)
                return f"Error: folder '{folder}' not allowed. Allowed: {', '.join(allowed)}"

        recent = self._load_recent_files(character_name)
        if folder:
            recent = [r for r in recent if r.get("folder") == folder]

        if not recent:
            return f"No files found{' in ' + folder if folder else ''}."

        lines = []
        for entry in reversed(recent[-10:]):
            modified = entry.get("last_modified", "?")
            if modified != "?":
                try:
                    dt = parse_iso(modified)
                    modified = dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    pass
            lines.append(
                f"- {entry.get('folder', '?')}/{entry.get('filename', '?')} "
                f"— \"{entry.get('title', '')}\" (last: {modified})"
            )

        return "Recent files:\n" + "\n".join(lines)

    def _action_read(self, character_name: str, folder: str,
                     filename: str) -> str:
        """Read an existing file."""
        if not folder:
            return "Error: folder must be specified."
        if not filename:
            # Most recent file in the folder
            recent = self._load_recent_files(character_name)
            folder_recent = [r for r in recent if r.get("folder") == folder]
            if folder_recent:
                filename = folder_recent[-1]["filename"]
            else:
                return f"Error: no files known in '{folder}'. Use 'list' to show them."

        folder_path = self._get_folder_path(character_name, folder)
        if not folder_path:
            allowed = self._get_allowed_folders(character_name)
            return f"Error: folder '{folder}' not allowed. Allowed: {', '.join(allowed)}"

        filename = self._sanitize_filename(filename)
        file_path = folder_path / filename

        if not file_path.exists():
            # Try a fuzzy match
            candidates = list(folder_path.glob("*.md"))
            name_lower = filename.lower().replace('.md', '')
            for c in candidates:
                if name_lower in c.stem.lower():
                    file_path = c
                    filename = c.name
                    break
            else:
                available = [c.name for c in candidates[:10]]
                if available:
                    return f"File '{filename}' not found. Available: {', '.join(available)}"
                return f"File '{filename}' not found and no files in '{folder}'."

        content = file_path.read_text(encoding="utf-8")

        # Truncate if very long (so the LLM context is not overloaded)
        max_chars = 4000
        truncated = ""
        if len(content) > max_chars:
            content = content[:max_chars]
            truncated = f"\n\n[... truncated, {len(content)} of {len(file_path.read_text(encoding='utf-8'))} characters shown]"

        self._track_file(character_name, folder, filename, "", "read")
        return f"=== {folder}/{filename} ===\n{content}{truncated}"

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "Error: MarkdownWriter skill is not available."

        try:
            return self._execute_inner(raw_input)
        except Exception as e:
            self.ctx.logger.error("MarkdownWriter error: %s", e, exc_info=True)
            return f"Error: {e}"

    def _execute_inner(self, raw_input: str) -> str:
        data = self._parse_base_input(raw_input)
        character_name = data.get("agent_name", "").strip()

        if not character_name:
            return "Error: agent name missing."

        cfg = self._get_effective_config(character_name)

        action = data.get("action", "append").strip().lower()
        folder = data.get("folder", "").strip()
        filename = data.get("filename", "").strip()
        title = data.get("title", "").strip()
        content = data.get("content", "").strip()

        # Default folder if none given
        if not folder:
            folder = cfg.get("default_folder", "diary")

        if action == "write":
            return self._action_write(character_name, folder, filename, title, content, cfg)
        elif action == "append":
            return self._action_append(character_name, folder, filename, title, content, cfg)
        elif action == "list":
            return self._action_list(character_name, folder)
        elif action == "read":
            return self._action_read(character_name, folder, filename)
        else:
            return f"Error: unknown action '{action}'. Allowed: write, append, list, read"

    # ------------------------------------------------------------------
    # memorize_result (for the scheduler)
    # ------------------------------------------------------------------

    def memorize_result(self, result: str, character_name: str) -> bool:
        """Store the result as a memory so the agent knows what it wrote."""
        if "Error:" in result:
            return False
        try:
            from app.models.memory import add_memory
            add_memory(character_name,
                content=f"Document action: {result}",
                memory_type="semantic",
                importance=2,
                tags=["document", "markdown"])
            return True
        except Exception as e:
            self.ctx.logger.warning("Memory storage failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Tool description
    # ------------------------------------------------------------------

    def get_usage_instructions(self, format_name: str = "", character_name: str = "") -> str:
        fmt = format_name or "tag"
        return format_example(
            fmt, self.name,
            '{"action": "append", "folder": "diary", "title": "March 15", '
            '"content": "Today was an exciting day..."}'
        )

    def _build_folders_hint(self, character_name: str) -> str:
        """Build a list of available folders for the tool description."""
        if not character_name:
            return ""
        try:
            folders = self._get_allowed_folders(character_name)
            if folders:
                return f" Available folders: {', '.join(folders)}."
        except Exception:
            pass
        return ""

    def _build_recent_hint(self, character_name: str) -> str:
        """Show the most recently edited files in the tool description."""
        if not character_name:
            return ""
        try:
            recent = self._load_recent_files(character_name)
            if not recent:
                return ""
            # Last 3 files
            hints = []
            for entry in recent[-3:]:
                hints.append(f"{entry.get('folder', '?')}/{entry.get('filename', '?')}")
            return f" Recent files: {', '.join(hints)}."
        except Exception:
            pass
        return ""

    def as_tool(self, character_name: str = "") -> ToolSpec:
        folders_hint = self._build_folders_hint(character_name)
        recent_hint = self._build_recent_hint(character_name)

        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description}. "
                "Input JSON: {\"action\": \"write|append|list|read\", "
                "\"folder\": \"<folder name>\", "
                "\"filename\": \"<optional filename.md>\", "
                "\"title\": \"<optional title>\", "
                "\"content\": \"<markdown text>\"}. "
                "Actions: "
                "'append' adds to an existing file (or creates new) — best for diary entries and ongoing documents. "
                "'write' creates or overwrites a file. "
                "'list' shows recent files in a folder. "
                "'read' reads a file to continue writing later. "
                "If no filename is given for append, the last edited file in that folder is used automatically. "
                "Content should be plain Markdown text."
                f"{folders_hint}{recent_hint}"
            ),
            func=self.execute)
