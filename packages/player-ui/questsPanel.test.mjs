// Run from repository root: node packages/player-ui/questsPanel.test.mjs
// Renders the actual quest book (QuestBook, pure) with D14 payload fixtures under the real I18nProvider.
// Hand-derived expectations from plan D14 / app/core/quest_book.py:
//  - a done step renders with class is-done and shows "done_by · done_label" ("Mira · Day 3, 09:15");
//  - the current step renders with class is-current, and nothing else does;
//  - a quest with "locked" shows the lock reason text visibly (not only in a hint);
//  - the "Completed" divider appears only when an ended quest (state != open) is in the list;
//  - an ended quest shows its ended_label and its state word (cancelled -> "Cancelled");
//  - an empty list renders "No quests yet";
//  - German: every t() literal of QuestsPanel.tsx has a de.json entry, and "Time left" reads "Verbleibend".
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(new URL('../../client3d/package.json', import.meta.url));
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const modules = new Map();
function moduleUrl(file) {
  const key = file.href;
  if (modules.has(key)) return modules.get(key);
  const source = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText.replace(/from (['"])([^'"]+)\1/g, (_, quote, specifier) => {
    if (!specifier.startsWith('.')) return `from '${pathToFileURL(require.resolve(specifier)).href}'`;
    const base = new URL(specifier, file);
    const dependency = ['.ts', '.tsx'].map(extension => new URL(base.href + extension)).find(candidate => existsSync(fileURLToPath(candidate)));
    assert.ok(dependency, `missing source dependency ${specifier}`);
    return `from '${moduleUrl(dependency)}'`;
  });
  const url = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
  modules.set(key, url);
  return url;
}
const { I18nProvider } = await import(moduleUrl(new URL('./src/I18nProvider.tsx', import.meta.url)));
const panel = await import(moduleUrl(new URL('./src/QuestsPanel.tsx', import.meta.url)));
assert.equal(typeof panel.QuestBook, 'function', 'QuestBook is exported');
assert.equal(typeof panel.QuestsPanel, 'function', 'QuestsPanel is exported');
const { QuestBook } = panel;
const render = data => renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(QuestBook, { data })));
const textNodes = html => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ');

const open = { id: 'r1', title: 'Errand', summary: 'Run an errand for someone.', state: 'open',
  steps: [{ text: 'Talk to the giver.', state: 'done', done_by: 'Mira', done_label: 'Day 3, 09:15' },
          { text: 'Go to the place.', state: 'current' }],
  time_left_label: '1 d 4 h' };
const html = render({ avatar: 'Mira', quests: [open] });
const stepTags = [...html.matchAll(/<li\b[^>]*class="([^"]*player-quest-step[^"]*)"[^>]*>/g)].map(m => m[1]);
assert.equal(stepTags.length, 2, 'one row per listed step');
assert.match(stepTags[0], /\bis-done\b/);
assert.doesNotMatch(stepTags[0], /\bis-current\b/);
assert.match(stepTags[1], /\bis-current\b/);
assert.doesNotMatch(stepTags[1], /\bis-done\b/);
assert.match(textNodes(html), /Talk to the giver\..*Mira · Day 3, 09:15/);
assert.match(textNodes(html), /Go to the place\./);
assert.match(textNodes(html), /Run an errand for someone\./);
assert.match(textNodes(html), /Time left: 1 d 4 h/);
assert.doesNotMatch(html, /Completed/, 'no divider without an ended quest');
assert.doesNotMatch(html, /player-quest-locked/, 'no lock without "locked"');
console.log('PASS open quest: done and current steps, time left, no divider');

const locked = { ...open, id: 'r2', steps: [{ text: 'Talk to the giver.', state: 'current' }],
  time_left_label: undefined, locked: 'Only for members of the guild.' };
const lockedHtml = render({ avatar: 'Mira', quests: [locked] });
assert.match(lockedHtml, /class="player-quest-locked"/);
assert.match(textNodes(lockedHtml), /Only for members of the guild\./, 'the reason is visible text');
assert.match(lockedHtml, /<svg/, 'the lock icon is drawn');
assert.doesNotMatch(lockedHtml, /Time left/);
console.log('PASS locked quest shows its reason');

const ended = { id: 'r3', title: 'Old errand', summary: 'Done before.', state: 'cancelled',
  steps: [{ text: 'Talk to the giver.', state: 'done', done_by: 'Kira', done_label: 'Day 1, 10:00' }],
  ended_label: 'Day 2, 18:30' };
const both = render({ avatar: 'Mira', quests: [open, ended] });
assert.match(both, /Completed/);
const afterDivider = textNodes(both).split('Completed')[1];
assert.ok(afterDivider && afterDivider.includes('Old errand'), 'ended quest is listed under the divider');
assert.ok(!afterDivider.includes('Errand Run'), 'the open quest stays above the divider');
assert.match(afterDivider, /Cancelled/);
assert.match(afterDivider, /Day 2, 18:30/);
assert.match(both, /player-quest-done/);
console.log('PASS ended quest under "Completed" with its state and end label');

const empty = render({ avatar: 'Mira', quests: [] });
assert.match(empty, /No quests yet/);
assert.doesNotMatch(empty, /Completed/);
console.log('PASS empty book');

const de = JSON.parse(readFileSync(new URL('../../shared/languages/de.json', import.meta.url), 'utf8')).translations;
assert.equal(de['Time left'], 'Verbleibend');
const source = readFileSync(new URL('./src/QuestsPanel.tsx', import.meta.url), 'utf8');
const literals = [...source.matchAll(/\bt\('([^']+)'\)/g)].map(m => m[1]);
assert.ok(literals.length >= 5, 'the panel translates its strings');
for (const literal of literals) assert.ok(de[literal], `missing German entry: ${literal}`);
assert.doesNotMatch(source, /story-arcs|StoryArc|import '.*\.css'/);
console.log(`PASS German entries for ${literals.length} panel strings`);
