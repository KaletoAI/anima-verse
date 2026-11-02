// Usage: node packages/player-ui/photoDialog.test.mjs
// Render the real dialog; only the portal transport is replaced for SSR.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
const cache = new Map();
let portal;
function load(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} }; cache.set(path, module);
  const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  }}).outputText;
  new Function('require', 'module', 'exports', code)(specifier => {
    if (specifier === 'react-dom') return { createPortal: children => { portal = children; return children; } };
    if (!specifier.startsWith('.')) return require(specifier);
    const base = resolve(dirname(path), specifier);
    const target = [base + '.ts', base + '.tsx'].find(existsSync);
    assert.ok(target, specifier);
    return load(target);
  }, module, module.exports);
  return module.exports;
}
globalThis.document = { body: {} };
const { PlayerPhotoDialog } = load(resolve('packages/player-ui/src/PlayerPhotoDialog.tsx'));
const { I18nProvider } = load(resolve('packages/player-ui/src/I18nProvider.tsx'));
const props = { prompt: 'Friends by the window', subjects: ['Bob'], available: ['Bob'], avatar: 'Ann', backendOptions: { options: [], resolved: 'Fake' }, onSubmit() {}, onClose() {} };
const render = extra => renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(PlayerPhotoDialog, { ...props, ...extra })));
const ordinary = render({});
assert.doesNotMatch(ordinary, /<img|The screenshot sets/);
const screenshot = render({ referenceImageId: 'abc.jpg', referenceImageUrl: '/chat/me/upload-image/abc.jpg' });
assert.match(screenshot, /src="\/chat\/me\/upload-image\/abc.jpg"/);
assert.match(screenshot, /The screenshot sets composition and angle; the picture follows the photo style\./);
assert.match(screenshot, /Friends by the window/);
assert.match(screenshot, /Who is in the picture/);
assert.match(screenshot, /Negative prompt/);
assert.match(screenshot, /Auto \(routing\)/);
function findButton(node, text) {
  if (!node || typeof node !== 'object') return null;
  if (Array.isArray(node)) return node.map(child => findButton(child, text)).find(Boolean);
  if (node.type === 'button' && node.props.children === text) return node;
  return findButton(node.props?.children, text);
}
let submitted;
render({ referenceImageId: 'abc.jpg', referenceImageUrl: '/chat/me/upload-image/abc.jpg', onSubmit: payload => { submitted = payload; } });
await findButton(portal, 'Generate').props.onClick();
assert.equal(submitted.reference_image_id, 'abc.jpg');
assert.equal(submitted.prompt, 'Friends by the window');
assert.deepEqual(submitted.character_names, ['Bob']);
render({ onSubmit: payload => { submitted = payload; } });
await findButton(portal, 'Generate').props.onClick();
assert.equal(Object.hasOwn(submitted, 'reference_image_id'), false, 'ordinary photos carry no screenshot');
console.log('photo dialog: PASS (ordinary/screenshot render and real submit handlers)');
