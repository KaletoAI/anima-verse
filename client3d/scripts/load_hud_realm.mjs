import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, extname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInThisContext } from 'node:vm';
import ts from 'typescript';

const root = fileURLToPath(new URL('../../', import.meta.url));
const nodeRequire = createRequire(import.meta.url);

/** Execute the real HUD modules with independent module caches, like two JS
 * realms. Uses the workspace's declared TypeScript dependency, not a bundler. */
export function loadHudRealm() {
  const cache = new Map();
  const events = new EventTarget();
  const realmWindow = new Proxy(events, {
    get(target, key) {
      if (key === 'setTimeout' || key === 'clearTimeout') return globalThis[key].bind(globalThis);
      const host = globalThis.window ?? target;
      const value = Reflect.get(host, key, host);
      return typeof value === 'function' ? value.bind(host) : value;
    },
  });
  class RealmCustomEvent extends Event {
    constructor(type, options) { super(type); this.detail = options?.detail; }
  }
  function load(path) {
    if (cache.has(path)) return cache.get(path).exports;
    const module = { exports: {} };
    cache.set(path, module);
    const source = readFileSync(path, 'utf8');
    const compiled = ts.transpileModule(source, {
      fileName: path,
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    }).outputText;
    const localRequire = specifier => {
      let target;
      if (specifier.startsWith('.')) {
        const base = resolve(dirname(path), specifier);
        target = [base, `${base}.ts`, `${base}.tsx`, resolve(base, 'index.ts')]
          .find(candidate => existsSync(candidate) && ['.ts', '.tsx', '.js', '.mjs'].includes(extname(candidate)));
      } else {
        target = nodeRequire.resolve(specifier);
      }
      if (!target) throw new Error(`Cannot resolve ${specifier} from ${path}`);
      return ['.ts', '.tsx'].includes(extname(target)) ? load(target) : nodeRequire(target);
    };
    const execute = runInThisContext(`(function(require,module,exports,window,CustomEvent){${compiled}\n})`, { filename: path });
    execute(localRequire, module, module.exports, realmWindow, RealmCustomEvent);
    return module.exports;
  }
  return {
    ...load(resolve(root, 'client3d/src/hud/bus.ts')),
    ...load(resolve(root, 'client3d/src/hud/bridge.ts')),
    load: relative => load(resolve(root, relative)),
  };
}
