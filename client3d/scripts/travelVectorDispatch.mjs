/** Test-only adapters for travel.json. All geometry stays in travelPath.ts. */
import { readFile } from 'node:fs/promises';
import { transformSync } from 'esbuild';

const source = await readFile(new URL('../src/scene/travelPath.ts', import.meta.url), 'utf8');
const { code } = transformSync(source, { loader: 'ts', format: 'esm' });
const travel = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
export const travelDispatch = {
  ...travel,
  errWindowMax(samples, nowMs) {
    const window = travel.createErrWindow();
    for (const [tMs, err] of samples) travel.pushErr(window, tMs, err);
    return travel.maxErr(window, nowMs);
  },
};
