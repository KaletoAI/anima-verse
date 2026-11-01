/* Standalone model picker. ModelCombobox.render({id,value,ariaLabel}) returns
 * HTML; after insertion attach(id,{loadModels: async()=>[names],onChange})
 * wires it up. open() loads the list and shows it; reload() refreshes the
 * names and only shows them while the field has focus. On focus the WHOLE list
 * shows (the current value is selected, so typing replaces it); typing filters.
 * Free text commits on blur or Enter. No settings globals are used.
 */
const ModelCombobox = (() => {
function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
    function render({id, value = '', ariaLabel = 'Model'}) {
        const e = escapeHtml;
        return '<div style="position:relative"><input type="text" style="width:100%;box-sizing:border-box" id="' + e(id) + '" value="' + e(value) + '" aria-label="' + e(ariaLabel)
            + '" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="' + e(id) + '-list" autocomplete="off">'
            + '<div id="' + e(id) + '-list" role="listbox" hidden style="position:absolute;top:100%;left:0;right:0;z-index:20;max-height:240px;overflow:auto;background:#161b22;border:1px solid #30363d"></div>'
            + '<div id="' + e(id) + '-status" class="desc" role="status"></div></div>';
    }
    function filter(names, query) {
        return names.filter(name => name.toLowerCase().includes(query.toLowerCase()));
    }
    function attach(id, {loadModels, onChange}) {
        const input = document.getElementById(id), list = document.getElementById(id + '-list'), status = document.getElementById(id + '-status');
        let names = [], matches = [], active = -1, generation = 0, opened = false, typed = false;
        let committed = input.value;
        function close() { opened = false; list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); }
        function commit(value) { input.value = value; if (value !== committed) { committed = value; onChange(value); } close(); }
        function draw() {
            matches = typed ? filter(names, input.value) : names.slice();
            list.innerHTML = matches.map((name, i) => '<div role="option" id="' + escapeHtml(id) + '-option-' + i + '" aria-selected="' + (i === active) + '" style="padding:6px;cursor:pointer;' + (i === active ? 'background:#30363d' : '') + '">' + escapeHtml(name) + '</div>').join('');
            list.hidden = !opened;
            input.setAttribute('aria-expanded', String(opened));
            if (active >= 0) input.setAttribute('aria-activedescendant', id + '-option-' + active);
            else input.removeAttribute('aria-activedescendant');
            Array.from(list.children).forEach((el, i) => { el.onmousedown = e => e.preventDefault(); el.onclick = () => commit(matches[i]); });
        }
        async function load(show) {
            const request = ++generation;
            opened = show; active = -1; typed = false; names = []; draw(); status.textContent = 'Loading models…';
            try {
                const loaded = await loadModels();
                if (request !== generation) return;
                names = loaded || []; status.textContent = names.length ? '' : 'No models reported — type the name'; draw();
            } catch (error) { if (request === generation) { status.textContent = error.message; draw(); } }
        }
        const open = () => { if (input.select) input.select(); return load(true); };
        const reload = () => load(document.activeElement === input);
        input.addEventListener('focus', open);
        input.addEventListener('input', () => { active = -1; opened = true; typed = true; draw(); });
        input.addEventListener('blur', () => commit(input.value));
        input.addEventListener('keydown', e => {
            if (e.key === 'Escape') { e.preventDefault(); close(); }
            else if (e.key === 'Enter') { e.preventDefault(); commit(opened && active >= 0 ? matches[active] : input.value); }
            else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault(); opened = true;
                if (matches.length) active = active < 0 ? (e.key === 'ArrowDown' ? 0 : matches.length - 1)
                    : (active + (e.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
                draw();
            }
        });
        return {open, reload};
    }
    return {render, attach, filter};
})();
