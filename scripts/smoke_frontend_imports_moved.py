#!/usr/bin/env python3
"""Guard the character-form migration and the shared package boundary.

The character forms (TemplateTab & co.) and AvatarSettingsPanel live in
packages/player-ui since plan-native-client Task 6. Checks:
  1. no file of a moved name remains under frontend/src;
  2. no frontend import points at an old path of a moved file;
  3. nothing in packages/player-ui/src imports from frontend/, the admin
     ImageGenDialog or the admin help context (those reach the forms only
     through CharacterFormHost).

Usage:
    ./.venv/bin/python scripts/smoke_frontend_imports_moved.py
"""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('TemplateTab', 'TemplateField', 'TemplateSectionForm', 'FieldImage',
         'SoulEditor', 'BodyEditor', 'PromptPreview', 'bodyAttributeVisibility',
         'Field', 'ConfirmDialog', 'AvatarSettingsPanel')
errors = []
for path in (ROOT / 'frontend/src').rglob('*'):
    if path.is_file() and path.stem in NAMES:
        errors.append(f'Old component path remains: {path.relative_to(ROOT)}')
# --untracked: a new, not yet committed importer counts too.
result = subprocess.run(['git', 'grep', '--untracked', '-n', '-E',
    r"(from|import).*[/](TemplateTab|TemplateField|TemplateSectionForm|FieldImage|SoulEditor|BodyEditor|PromptPreview|bodyAttributeVisibility|Field|ConfirmDialog|AvatarSettingsPanel)([.]tsx?)?['\"]",
    '--', 'frontend/src'], cwd=ROOT, capture_output=True, text=True)
if result.returncode not in (0, 1):
    raise RuntimeError(result.stderr)
if result.stdout:
    errors.append(result.stdout.rstrip())
for path in (ROOT / 'packages/player-ui/src').rglob('*'):
    if path.suffix not in ('.ts', '.tsx'):
        continue
    for match in re.finditer(r"(?:from\s*|import\s*)['\"]([^'\"]+)['\"]", path.read_text()):
        if any(word in match[1] for word in ('frontend/', 'ImageGenDialog', 'help/HelpContext')):
            errors.append(f'Forbidden dependency: {path.relative_to(ROOT)}: {match[1]}')
if errors:
    print('FAIL: character forms have not moved cleanly')
    print('\n'.join(errors))
    raise SystemExit(1)
print('PASS: character forms moved; frontend importers and player-ui boundary clean')
