// Usage: node packages/player-ui/videoSources.test.mjs
// Hand oracle: a clip URL yields exactly two <source> children, WebM first
// (`<mp4 url>/webm`, type video/webm), the original MP4 second; a query string
// rides along; a non-mp4 URL gets no companion.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
const path = 'packages/player-ui/src/VideoSources.tsx';
const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
}}).outputText;
const m = { exports: {} };
new Function('require', 'module', 'exports', code)(require, m, m.exports);
const { VideoSources, webmCompanionUrl } = m.exports;
const html = renderToStaticMarkup(React.createElement(VideoSources, { src: '/characters/Ann/images/a_1.mp4', controls: true }));
assert.equal(html, '<video controls=""><source src="/characters/Ann/images/a_1.mp4/webm" type="video/webm"/><source src="/characters/Ann/images/a_1.mp4" type="video/mp4"/></video>');
assert.equal(webmCompanionUrl('/instagram/images/x.mp4?v=3'), '/instagram/images/x.mp4/webm?v=3');
assert.equal(webmCompanionUrl('/a/b.png'), '');
const png = renderToStaticMarkup(React.createElement(VideoSources, { src: '/a/b.webm' }));
assert.equal((png.match(/<source/g) || []).length, 1);
console.log('videoSources: ok');
