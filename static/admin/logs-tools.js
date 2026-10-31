function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

const filters = ['character', 'tool', 'status', 'source'];
const nonOk = ['error', 'blocked', 'unknown_tool', 'suppressed', 'exception', 'discarded'];
const byId = id => document.getElementById(id);
const initial = new URLSearchParams(location.search);
for (const key of filters) {
    const value = initial.get(key);
    if (value) byId(key + 'Filter').add(new Option(value, value, true, true));
}
byId('searchInput').value = initial.get('search') || '';
let offset = 0;
const limit = 100;
let requestId = 0;

function updateOptions(key, values) {
    const select = byId(key + 'Filter');
    const selected = select.value;
    const all = [...new Set([...values, ...(selected ? [selected] : [])])];
    select.replaceChildren(new Option('All ' + key + (key === 'status' ? 'es' : 's'), ''));
    for (const value of all) select.add(new Option(value, value));
    select.value = selected;
}

async function load() {
    const currentRequest = ++requestId;
    const params = new URLSearchParams({limit, offset});
    for (const key of filters) params.set(key, byId(key + 'Filter').value);
    params.set('search', byId('searchInput').value);
    try {
        const response = await fetch('/logs/tools/data?' + params);
        if (!response.ok) throw new Error('Could not load tool calls (' + response.status + ')');
        const data = await response.json();
        if (currentRequest !== requestId) return;
        for (const key of filters) updateOptions(key, data[key === 'status' ? 'statuses' : key + 's']);
        byId('countLabel').textContent = data.total + ' calls';
        byId('summary').innerHTML = '<table><caption>Tool outcomes</caption><thead><tr><th>Tool</th><th>Total</th><th>ok</th>' +
            nonOk.map(s => '<th>' + escapeHtml(s) + '</th>').join('') +
            '<th>Fail %</th></tr></thead><tbody>' +
            data.summary.map(row => '<tr data-tool="' + escapeHtml(row.tool) + '"><td><button class="tool-choice" data-tool="' +
                escapeHtml(row.tool) + '">' + escapeHtml(row.tool) + '</button></td><td>' +
                escapeHtml(row.total) + '</td><td>' + escapeHtml(row.by_status.ok || 0) + '</td>' +
                nonOk.map(s => '<td>' + escapeHtml(row.by_status[s] || 0) + '</td>').join('') +
                '<td>' + escapeHtml((row.fail_rate * 100).toFixed(1)) + '%</td></tr>').join('') +
            '</tbody></table>';
        byId('entries').innerHTML = data.entries.map(row => {
            const state = ['ok', ...nonOk].includes(row.status) ? row.status : 'unknown';
            const time = row.starttime ? new Date(row.starttime).toLocaleString() : '';
            return '<article><header><time>' + escapeHtml(time) + '</time> · ' +
                escapeHtml(row.game_ts) + ' · <strong>' + escapeHtml(row.character) + '</strong> · ' +
                escapeHtml(row.tool) + ' <span class="badge status-' + escapeHtml(state) + '">' +
                escapeHtml(row.status) + '</span> · ' + escapeHtml(row.source) +
                (row.duration_ms == null ? '' : ' · ' + escapeHtml(row.duration_ms) + ' ms') +
                (row.trace_id ? ' · <a href="/logs/llm?search=' +
                    escapeHtml(encodeURIComponent(row.trace_id)) + '">LLM turn</a>' : '') +
                '</header><details><summary>Input</summary><pre>' + escapeHtml(row.input) +
                '</pre></details><details><summary>Result</summary><pre>' +
                escapeHtml(row.result) + '</pre></details></article>';
        }).join('') || '<p>No tool calls found.</p>';
        byId('prevBtn').disabled = offset === 0;
        byId('nextBtn').disabled = offset + limit >= data.total;
        byId('pageLabel').textContent = data.total ?
            (offset + 1) + '–' + Math.min(offset + limit, data.total) + ' of ' + data.total : '0 calls';
    } catch (error) {
        if (currentRequest === requestId) byId('countLabel').textContent = error.message;
    }
}

function search() {
    offset = 0;
    load();
}
byId('summary').addEventListener('click', event => {
    const button = event.target.closest('tr[data-tool]');
    if (!button) return;
    byId('toolFilter').value = button.dataset.tool;
    search();
});
byId('searchBtn').addEventListener('click', search);
byId('searchInput').addEventListener('keydown', event => {
    if (event.key === 'Enter') search();
});
for (const key of filters) byId(key + 'Filter').addEventListener('change', search);
byId('resetBtn').addEventListener('click', () => {
    for (const key of filters) byId(key + 'Filter').value = '';
    byId('searchInput').value = '';
    search();
});
byId('prevBtn').addEventListener('click', () => {
    offset = Math.max(0, offset - limit);
    load();
});
byId('nextBtn').addEventListener('click', () => {
    offset += limit;
    load();
});
load();
