/** Execute a production main.ts closure with explicit fixture dependencies, without booting WebGL. */
import ts from 'typescript';
import { readFileSync } from 'node:fs';
export async function mainFunction(name, dependencies, observe = []) {
  const source = ts.createSourceFile('main.ts', readFileSync(new URL('../src/main.ts', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true);
  let found;
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === name) found = node;
    if (ts.isBinaryExpression(node) && node.left.getText(source) === name) found = node.right;
    if (ts.isCallExpression(node) && node.expression.getText(source) === 'engine.addFrameHook'
      && name === 'engine.addFrameHook:manualInput' && node.arguments[0]?.getText(source).includes('const manualInput')) found = node.arguments[0];
    ts.forEachChild(node, visit);
  }
  visit(source);
  if (!found) throw new Error(`Missing production function ${name}`);
  const code = ts.transpileModule(`return Object.assign((${found.getText(source)}), { snapshot: () => ({ ${observe.join(", ")} }) });`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  return new Function(...Object.keys(dependencies), code)(...Object.values(dependencies));
}

/** Execute cooperating production closures in one fixture scope, preserving their shared state. */
export async function mainFunctions(names, dependencies, observe = []) {
  const source = ts.createSourceFile('main.ts', readFileSync(new URL('../src/main.ts', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true);
  const found = new Map();
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && names.includes(node.name?.text)) found.set(node.name.text, node.getText(source));
    ts.forEachChild(node, visit);
  }
  visit(source);
  for (const name of names) if (!found.has(name)) throw new Error(`Missing production function ${name}`);
  const code = ts.transpileModule(`${[...found.values()].join('\n')}\nreturn { ${names.join(', ')}, snapshot: () => ({ ${observe.join(', ')} }) };`,
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  return new Function(...Object.keys(dependencies), code)(...Object.values(dependencies));
}
