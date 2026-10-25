/** Bench diagnostics mount only after a requested run has finished. */
import { createPortal } from 'react-dom';
import { createRoot, type Root } from 'react-dom/client';
let root: Root | undefined;
export function showBenchResult(result: Record<string, unknown>): void {
  root ??= createRoot(document.createElement('div'));
  root.render(createPortal(
    <pre id="bench" style={{position:'fixed',right:4,bottom:4,zIndex:9999,
      background:'#000d',color:'#ffd',font:'11px monospace',padding:6,
      maxWidth:'48vw',maxHeight:'80vh',overflow:'auto',whiteSpace:'pre-wrap',userSelect:'text'}}>
      {JSON.stringify(result,null,2)}
    </pre>, document.body));
}
