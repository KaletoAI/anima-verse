/** Focus, selection and controlled-input tracking without a browser dependency. */
import assert from 'node:assert/strict';
import { loadHudRealm } from './load_hud_realm.mjs';
import { smokeHudText as smokeHudTextBrowser } from './smoke_hud_text_browser.mjs';

export function smokeHudText(wire) {
  const hud = loadHudRealm();
  let send;
  let stop;
  if (wire === 'gdcef') {
    let receive;
    stop = hud.connectHudSide(hud.gdcefTransport({
      godotMethods: { hud_bridge: () => true }, godotEvents: { on: (_, fn) => { receive = fn; } },
    }));
    send = msg => receive(JSON.stringify(msg));
  } else {
    const [scene, transport] = hud.loopbackPair();
    stop = hud.connectHudSide(transport);
    send = msg => scene.send(msg);
  }
  class Input extends EventTarget {
    tagName = 'INPUT'; type = 'text'; stored = ''; tracked = ''; state = ''; selectionStart = 0; selectionEnd = 0;
    disabled = false; readOnly = false; isContentEditable = false;
    constructor() {
      super();
      // React tracks assignments to the instance setter; native editing must bypass it.
      Object.defineProperty(this, 'value', { get: () => this.stored, set: value => { this.stored = this.tracked = value; } });
      this.addEventListener('input', () => {
        if (this.tracked !== this.value) this.state = this.tracked = this.value;
      });
    }
    get value() { return this.stored; }
    set value(value) { this.stored = value; }
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  }
  class Textarea extends Input {
    tagName = 'TEXTAREA';
    get value() { return this.stored; }
    set value(value) { this.stored = value; }
  }
  const old = new Map(['document', 'HTMLInputElement', 'HTMLTextAreaElement'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const input = new Input();
  const document = { activeElement: input, execCommand: (_command, _ui, value) => {
    const target = document.activeElement;
    if (target.isContentEditable) { target.textContent += value; return true; }
    const start = target.selectionStart, end = target.selectionEnd;
    Object.getOwnPropertyDescriptor(Input.prototype, 'value').set.call(target, target.value.slice(0, start) + value + target.value.slice(end));
    target.setSelectionRange(start + value.length, start + value.length);
    target.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  } };
  Object.assign(globalThis, { document, HTMLInputElement: Input, HTMLTextAreaElement: Textarea });
  const text = value => send({ v: 4, kind: 'text', value });
  try {
    for (const value of ['.', '(', 'ö']) text(value);
    assert.equal(input.value, '.(ö', 'text reaches focused input');
    assert.equal(input.state, '.(ö', 'input event updates controlled state');
    input.setSelectionRange(1, 3); text('!');
    assert.equal(input.state, '.!', 'selected text replaced');
    const editable = { tagName: 'DIV', isContentEditable: true, textContent: '' };
    document.activeElement = editable; text('.'); text('('); text('ö');
    assert.equal(editable.textContent, '.(ö', 'contenteditable uses insertText');
    document.activeElement = input;
    for (const unavailable of [undefined, () => false, () => { throw new Error('unavailable'); }]) {
      document.execCommand = unavailable;
      input.setSelectionRange(1, 2); text('ö');
      assert.equal(input.value, '.ö'); assert.equal(input.state, '.ö', 'fallback bypasses controlled value tracker');
      assert.equal(input.selectionStart, 2);
      input.setSelectionRange(1, 2); text('!');
      const area = new Textarea(); document.activeElement = area; text('ö');
      assert.equal(area.state, 'ö', 'textarea native setter sends input');
      document.activeElement = input;
    }
    for (const active of [null, { tagName: 'BUTTON', isContentEditable: false }, { tagName: 'DIV', isContentEditable: false }]) {
      document.activeElement = active; text('x'); assert.equal(input.value, '.!');
    }
    document.activeElement = input;
    input.readOnly = true; text('x'); assert.equal(input.value, '.!'); input.readOnly = false;
    input.disabled = true; text('x'); assert.equal(input.value, '.!'); input.disabled = false;
    const warn = console.warn; console.warn = () => {};
    try { text(null); text(7); } finally { console.warn = warn; }
    assert.equal(input.value, '.!', 'malformed text ignored');
    stop(); text('x'); assert.equal(input.value, '.!', 'disconnected receiver ignored');
    const focus = new EventTarget();
    document.addEventListener = focus.addEventListener.bind(focus);
    document.removeEventListener = focus.removeEventListener.bind(focus);
    const messages = [];
    const stopFocus = hud.connectHudSide({ send: msg => messages.push(msg), onMessage: () => () => {} });
    try {
      hud.setHudUiState({ typing: true });
      const patch = () => messages.findLast(msg => msg.kind === 'hud').patch;
      assert.equal(patch().textInput, true, 'new page advertises text capability for a text field');
      for (const type of ['checkbox', 'radio', 'range', 'button', 'file']) {
        input.type = type; focus.dispatchEvent(new Event('focusin'));
        assert.equal(patch().typing, true, 'keyboard ownership preserved for controls');
        assert.equal(patch().textInput, false, type + ' keeps CEF keys');
      }
      input.type = 'text'; focus.dispatchEvent(new Event('focusin'));
      assert.equal(patch().textInput, true, 'text capability refreshes even when typing remains true');
      document.activeElement = { tagName: 'SELECT', isContentEditable: false };
      focus.dispatchEvent(new Event('focusin')); assert.equal(patch().textInput, false, 'select keeps CEF typeahead');
      document.activeElement = null;
      focus.dispatchEvent(new Event('focusout')); assert.equal(patch().textInput, false, 'blur clears text flag');
      stopFocus(); const before = messages.length;
      document.activeElement = input; focus.dispatchEvent(new Event('focusin'));
      assert.equal(messages.length, before, 'focus listeners removed on disconnect');
    } finally { stopFocus(); }
  } finally {
    stop();
    for (const [key, descriptor] of old) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
  console.log('hud text: PASS (' + wire + ', text, selection, controlled-input setter/events, focus, cleanup)');
  // Opt into the actual React DOM smoke on hosts that permit Chromium subprocesses.
  if (process.env.CHROME_BIN) smokeHudTextBrowser(wire);
}
