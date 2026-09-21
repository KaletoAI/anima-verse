#!/usr/bin/env node
/**
 * Smoke check for the HTML escapers of the Python-rendered admin pages —
 * the one helper each file in `static/admin/` uses before a value goes into
 * `innerHTML` / `insertAdjacentHTML`.
 *
 * Usage:  node scripts/smoke_admin_escape.mjs
 *
 * Runs headless: it does NOT load the page scripts (they touch `document` at
 * the top level). It cuts the escaper out of each file by regex and runs that
 * function alone in a `node:vm` context — the same trick
 * `scripts/smoke_clock_format.mjs` uses for `AdminClock`, one step smaller.
 *
 * Background: review 2026-09-20, findings SEC-8 / UI-5 / UI-6 / UI-10. The
 * log viewers escaped only `& < >`, so provider error text landed inside
 * `title="…"` with its quotes intact; `dashboard.js` built its escaper from
 * `textContent → innerHTML`, which by definition never escapes a quote; and
 * `models.js` put a JS-escaped value into a `"`-delimited `onclick` without
 * any HTML escaping.
 *
 * ============================================================================
 * THE CONTRACT, DERIVED BY HAND
 * ============================================================================
 * Every escaper listed in ESCAPERS below must map, in ONE pass over the
 * input (so a produced `&` is never escaped again):
 *
 *     &  ->  &amp;      <  ->  &lt;      >  ->  &gt;
 *     "  ->  &quot;     '  ->  &#39;
 *
 * and must leave every other character untouched. A backtick needs no
 * escaping: it is not special to the HTML parser, and none of these files
 * interpolates into a template literal that the browser re-parses.
 *
 * Hand-derived expectations (each character replaced once, left to right):
 *
 *   in   `&<>"'`
 *   out  `&amp;&lt;&gt;&quot;&#39;`
 *
 *   in   `&amp;`                    (already-escaped text stays data)
 *   out  `&amp;amp;`                 -> the `&` becomes `&amp;`, `amp;` is literal
 *
 *   in   `" onmouseover="alert(1)`  (the attribute breakout of SEC-8)
 *   out  `&quot; onmouseover=&quot;alert(1)`
 *        placed as  title="&quot; onmouseover=&quot;alert(1)"  the attribute
 *        ends at the real `"` the template wrote — no new attribute appears.
 *
 *   in   `</script><img src=x onerror=alert(1)>`
 *   out  `&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;`
 *        no `<` survives, so no tag and no handler attribute is created.
 *
 *   in   `x' onerror='alert(1)`     (the single-quoted-attribute breakout)
 *   out  `x&#39; onerror=&#39;alert(1)`
 *
 * Coercion, derived from `String(s == null ? '' : s)`:
 *
 *   null -> ``      undefined -> ``      0 -> `0`      false -> `false`
 *   5    -> `5`     `` -> ``
 *
 * `0` and `false` matter: the old `if (!s) return ''` guards in the two log
 * viewers swallowed a seed of 0 and printed nothing.
 *
 * ============================================================================
 * THE COMPOSED ESCAPERS
 * ============================================================================
 * Two files put a value inside an inline `onclick="fn('…')"`. That value
 * crosses TWO grammars, so it needs both steps, JS first, HTML second:
 *
 *   `models.js`           escJs = esc(jsEscape(s))
 *   `settings-routing.js` rtJs  = esc(jsEscape(s))   (esc lives in settings.js,
 *                                                     both load on one page)
 *
 * with jsEscape = `\` -> `\\` then `'` -> `\'`.
 *
 * Hand-derived, for input  a'b  :
 *   jsEscape ->  a\'b
 *   esc      ->  a\&#39;b
 *   written  ->  onclick="deletePattern('a\&#39;b')"
 *   the HTML parser decodes the attribute value ->  deletePattern('a\'b')
 *   the JS parser reads the string literal       ->  a'b            (round trip)
 *
 * For input  a"b  :
 *   jsEscape ->  a"b        (untouched, not special in a '-string)
 *   esc      ->  a&quot;b
 *   written  ->  onclick="deletePattern('a&quot;b')"
 *   decoded  ->  deletePattern('a"b')                               (round trip)
 *   the `"` never reaches the parser as a delimiter — that is UI-10.
 *
 * For input  a\b  :
 *   jsEscape ->  a\\b   ->  esc unchanged  ->  decoded  deletePattern('a\\b')
 *   the JS literal `'a\\b'` is  a\b                                 (round trip)
 *
 * For the breakout  `); alert(1); //`  :
 *   jsEscape ->  \'); alert(1); //     esc ->  \&#39;); alert(1); //
 *   decoded  ->  deletePattern('\'); alert(1); //')  — the `'` is INSIDE the
 *   string literal, the call is never closed early.
 *
 * ============================================================================
 * WHAT ELSE IS CHECKED
 * ============================================================================
 * - every `static/admin/*.js` parses (`node --check`)
 * - every escaper body is character-for-character the same one (only the
 *   function name differs), so the next edit cannot let one file drift again
 * - no `static/admin/*.js` still defines an escaper that misses a quote
 *
 * Exit code 0 = all checks passed, 1 = at least one failed.
 */

import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const ADMIN = join(ROOT, 'static/admin');

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}`);
  if (!ok) {
    console.log(`        expected: ${JSON.stringify(expected)}`);
    console.log(`        actual:   ${JSON.stringify(actual)}`);
  }
}

/** Cuts `function <name>(s) { … }` out of a file and returns its source.
 *  All admin escapers are top-level declarations whose closing brace sits in
 *  column 0 (or on the same line), so the brace counter below is enough. */
function extractFunction(src, name) {
  const head = new RegExp(`function\\s+${name}\\s*\\(`, 'g');
  const m = head.exec(src);
  if (!m) return null;
  const open = src.indexOf('{', m.index);
  if (open < 0) return null;
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    const c = src[i];
    if (c === '{') depth += 1;
    else if (c === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(m.index, i + 1);
    }
  }
  return null;
}

/** Runs the extracted sources in a bare vm context and hands back the fns. */
function loadFns(sources) {
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(`${sources.join('\n')}\n`, sandbox);
  return sandbox;
}

// ── which file owns which escaper ────────────────────────────────────────────
// `settings-routing.js` has no escaper of its own: it is loaded next to
// `settings.js` on /admin/settings and uses that file's `esc`.
const ESCAPERS = [
  ['agent-loop.js', 'escapeHtml'],
  ['dashboard.js', '_esc'],
  ['llm-stats.js', 'escapeHtml'],
  ['logs-image.js', 'esc'],
  ['logs-viewer.js', 'escapeHtml'],
  ['models.js', 'esc'],
  ['settings.js', 'esc'],
  ['users.js', 'escapeHtml'],
];

// ── the table, hand-derived in the header ────────────────────────────────────
const CASES = [
  ['&<>"\'', '&amp;&lt;&gt;&quot;&#39;'],
  ['&amp;', '&amp;amp;'],
  ['" onmouseover="alert(1)', '&quot; onmouseover=&quot;alert(1)'],
  ["x' onerror='alert(1)", 'x&#39; onerror=&#39;alert(1)'],
  ['</script><img src=x onerror=alert(1)>',
   '&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;'],
  ['plain text 123', 'plain text 123'],
  ['`backtick`', '`backtick`'],
];
const COERCIONS = [
  [null, ''],
  [undefined, ''],
  [0, '0'],
  [false, 'false'],
  [5, '5'],
  ['', ''],
];

console.log('=== admin escapers ===');
const bodies = new Map();
for (const [file, name] of ESCAPERS) {
  const src = readFileSync(join(ADMIN, file), 'utf8');
  const fnSrc = extractFunction(src, name);
  if (!fnSrc) {
    failures += 1;
    console.log(`FAIL  ${file}: no top-level "function ${name}(…)" found`);
    continue;
  }
  // The name is stripped so files with different helper names still compare.
  bodies.set(`${file}:${name}`, fnSrc.replace(new RegExp(`\\b${name}\\b`), 'ESC'));
  const fn = loadFns([fnSrc])[name];
  // A helper built on `document` (the old dashboard.js `_esc`) throws here —
  // report that as a failed case instead of killing the whole run.
  const call = (v) => { try { return fn(v); } catch (e) { return `<threw: ${e.message}>`; } };
  for (const [input, expected] of CASES) {
    check(`${file} ${name}(${JSON.stringify(input)})`, call(input), expected);
  }
  for (const [input, expected] of COERCIONS) {
    check(`${file} ${name}(${String(input)})`, call(input), expected);
  }
}

console.log('\n=== every escaper is the SAME implementation ===');
{
  const seen = [...bodies.values()];
  const first = seen[0];
  for (const [key, body] of bodies) {
    check(`${key} body identical to the canonical one`, body, first);
  }
}

console.log('\n=== composed escapers (JS string, then HTML attribute) ===');
{
  // models.js: esc + escJs ; settings-routing.js: rtJs + settings.js esc
  const modelsSrc = readFileSync(join(ADMIN, 'models.js'), 'utf8');
  const routingSrc = readFileSync(join(ADMIN, 'settings-routing.js'), 'utf8');
  const settingsSrc = readFileSync(join(ADMIN, 'settings.js'), 'utf8');
  const usersSrc = readFileSync(join(ADMIN, 'users.js'), 'utf8');
  const mFns = loadFns([extractFunction(modelsSrc, 'esc'),
                        extractFunction(modelsSrc, 'escJs')]);
  const rFns = loadFns([extractFunction(settingsSrc, 'esc'),
                        extractFunction(routingSrc, 'rtJs')]);
  const sFns = loadFns([extractFunction(settingsSrc, 'esc'),
                        extractFunction(settingsSrc, 'sJs')]);
  const uFns = loadFns([extractFunction(usersSrc, 'escapeHtml'),
                        extractFunction(usersSrc, 'escJs')]);
  const COMPOSED = [
    ["a'b", 'a\\&#39;b'],
    ['a"b', 'a&quot;b'],
    ['a\\b', 'a\\\\b'],
    ["'); alert(1); //", '\\&#39;); alert(1); //'],
    ['<img src=x>', '&lt;img src=x&gt;'],
  ];
  for (const [input, expected] of COMPOSED) {
    check(`models.js escJs(${JSON.stringify(input)})`, mFns.escJs(input), expected);
    check(`settings-routing.js rtJs(${JSON.stringify(input)})`, rFns.rtJs(input), expected);
    check(`settings.js sJs(${JSON.stringify(input)})`, sFns.sJs(input), expected);
    check(`users.js escJs(${JSON.stringify(input)})`, uFns.escJs(input), expected);
  }
  // Round trip: HTML-decode the attribute value, then read the JS literal.
  // Only the five entities this escaper produces can appear.
  const htmlDecode = (s) => s
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');
  const PREFIX = 'onclick="deletePattern(\'';   // 24 chars
  const SUFFIX = '\')"';                        //  3 chars
  for (const raw of ["a'b", 'a"b', 'a\\b', "'); alert(1); //", '<img src=x>']) {
    const attr = `${PREFIX}${mFns.escJs(raw)}${SUFFIX}`;
    check(`onclick attribute for ${JSON.stringify(raw)} carries exactly 2 quote chars`,
          (attr.match(/"/g) || []).length, 2);
    // What the HTML parser hands the JS parser: the attribute value, decoded.
    const literal = htmlDecode(attr.slice(PREFIX.length, -SUFFIX.length));
    check(`round trip ${JSON.stringify(raw)}`,
          vm.runInNewContext(`'${literal}'`), raw);
  }
}

console.log('\n=== URL guards (src=/href= fed from data) ===');
{
  // dashboard.js `_safeUrl` also lets a data:image through (the <img> beat
  // picture); settings.js `safeUrl` guards an <iframe src>, where a data: URL
  // would be a same-origin document, so it allows relative + http(s) only.
  //
  // Hand-derived, from "a scheme is [a-z][a-z0-9+.-]* before the first ':'":
  //   /characters/Kira/images/a.png   relative, no scheme   -> kept
  //   https://example.org/a.png       http(s)               -> kept
  //   //evil.example/a.png            protocol-relative     -> dropped
  //   javascript:alert(1)             other scheme          -> dropped
  //   JaVaScript:alert(1)             case-insensitive      -> dropped
  //   java\nscript:alert(1)           control char stripped -> dropped
  //   data:image/png;base64,AAA       image data URL        -> kept (dashboard)
  //                                                         -> dropped (settings)
  //   data:text/html,<script>         not an image          -> dropped (both)
  const dFns = loadFns([extractFunction(readFileSync(join(ADMIN, 'dashboard.js'), 'utf8'), '_safeUrl')]);
  const sFns = loadFns([extractFunction(readFileSync(join(ADMIN, 'settings.js'), 'utf8'), 'safeUrl')]);
  const COMMON = [
    ['/characters/Kira/images/a.png', '/characters/Kira/images/a.png'],
    ['https://example.org/a.png', 'https://example.org/a.png'],
    ['//evil.example/a.png', ''],
    ['javascript:alert(1)', ''],
    ['JaVaScript:alert(1)', ''],
    ['java\nscript:alert(1)', ''],
    ['vbscript:msgbox(1)', ''],
    ['data:text/html,<script>alert(1)</script>', ''],
    [null, ''],
    ['', ''],
  ];
  for (const [input, expected] of COMMON) {
    check(`dashboard.js _safeUrl(${JSON.stringify(input)})`, dFns._safeUrl(input), expected);
    check(`settings.js safeUrl(${JSON.stringify(input)})`, sFns.safeUrl(input), expected);
  }
  check('dashboard.js _safeUrl keeps a data:image', dFns._safeUrl('data:image/png;base64,AAA'),
        'data:image/png;base64,AAA');
  check('settings.js safeUrl drops a data: iframe', sFns.safeUrl('data:image/png;base64,AAA'), '');
}

console.log('\n=== no admin file keeps a quote-blind escaper ===');
for (const file of readdirSync(ADMIN).filter(f => f.endsWith('.js'))) {
  const src = readFileSync(join(ADMIN, file), 'utf8');
  // An escaper that replaces `<` but never mentions &quot; is the old bug.
  const hasLt = /replace\([^)]*&lt;/.test(src) || /'<':\s*'&lt;'/.test(src);
  const hasQuot = src.includes('&quot;');
  check(`${file} escaper mentions &quot;`, !hasLt || hasQuot, true);
  // The dashboard's old `textContent`→`innerHTML` trick can never escape a quote.
  check(`${file} has no textContent→innerHTML escaper`,
        !/textContent\s*=\s*s\s*;[\s\S]{0,40}innerHTML/.test(src), true);
}

console.log('\n=== node --check on every static/admin/*.js ===');
for (const file of readdirSync(ADMIN).filter(f => f.endsWith('.js'))) {
  let ok = true;
  let err = '';
  try {
    execFileSync(process.execPath, ['--check', join(ADMIN, file)], { stdio: 'pipe' });
  } catch (e) {
    ok = false;
    err = String(e.stderr || e.message).split('\n').slice(0, 3).join(' | ');
  }
  check(`${file} parses${ok ? '' : ` (${err})`}`, ok, true);
}

console.log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : `${failures} CHECK(S) FAILED`}`);
process.exit(failures === 0 ? 0 : 1);
