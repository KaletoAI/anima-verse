
let CURRENT_ROWS = [];
let SORT_KEY = "calls";
let SORT_DIR = -1;

function isoLocal(dt) {
    const pad = n => String(n).padStart(2, "0");
    return dt.getFullYear() + "-" + pad(dt.getMonth()+1) + "-" + pad(dt.getDate())
        + "T" + pad(dt.getHours()) + ":" + pad(dt.getMinutes());
}

function applyPreset(p) {
    const now = new Date();
    let from = new Date(now);
    if (p === "1h") from.setHours(now.getHours() - 1);
    else if (p === "24h") from.setHours(now.getHours() - 24);
    else if (p === "7d") from.setDate(now.getDate() - 7);
    else if (p === "30d") from.setDate(now.getDate() - 30);
    document.getElementById("from-input").value = isoLocal(from);
    document.getElementById("to-input").value = isoLocal(now);
    document.querySelectorAll(".preset-row .btn").forEach(b => b.classList.remove("active"));
    const btn = document.querySelector(".preset-row .btn[data-preset='" + p + "']");
    if (btn) btn.classList.add("active");
    loadData();
}

function buildQuery() {
    const fromVal = document.getElementById("from-input").value;
    const toVal = document.getElementById("to-input").value;
    const task = document.getElementById("task-filter").value.trim();
    const agentSel = document.getElementById("agent-select");
    const agents = Array.from(agentSel.selectedOptions).map(o => o.value).filter(v => v);
    const grouped = document.getElementById("group-by-agent").checked;
    const params = new URLSearchParams();
    if (fromVal) params.set("from", fromVal.length === 16 ? fromVal + ":00" : fromVal);
    if (toVal) params.set("to", toVal.length === 16 ? toVal + ":00" : toVal);
    if (task) params.set("task", task);
    if (agents.length) params.set("agents", agents.join(","));
    if (grouped) params.set("group_by_agent", "1");
    return params.toString();
}

async function loadData() {
    const errBox = document.getElementById("error-box");
    errBox.innerHTML = "";
    document.getElementById("stats-tbody").innerHTML =
        '<tr><td class="empty" colspan="20">Loading…</td></tr>';
    try {
        const q = buildQuery();
        const resp = await fetch("/admin/llm-stats/data?" + q, { credentials: "same-origin" });
        if (resp.status === 401 || resp.status === 403) {
            const ret = encodeURIComponent(window.location.pathname);
            window.location.href = "/?return=" + ret;
            return;
        }
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const data = await resp.json();
        CURRENT_ROWS = data.rows || [];
        updateAgentDropdown(data.agents || []);
        renderSummary(data);
        renderTable();
    } catch (e) {
        errBox.innerHTML = '<div class="error">Error: ' + escapeHtml(e.message) + "</div>";
        document.getElementById("stats-tbody").innerHTML = "";
    }
}

function updateAgentDropdown(agents) {
    const sel = document.getElementById("agent-select");
    const prev = new Set(Array.from(sel.selectedOptions).map(o => o.value));
    sel.innerHTML = "";
    for (const a of agents) {
        const opt = document.createElement("option");
        opt.value = a;
        opt.textContent = a;
        if (prev.has(a)) opt.selected = true;
        sel.appendChild(opt);
    }
}

function renderSummary(data) {
    const total = CURRENT_ROWS.reduce((s, r) => s + r.calls, 0);
    const groups = CURRENT_ROWS.length;
    const grouped = data.group_by_agent ? "Task x Model x Provider x Character" : "Task x Model x Provider";
    document.getElementById("summary").textContent =
        groups + " Gruppen, " + total + " Calls insgesamt | Gruppierung: " + grouped
        + " | Zeitraum: " + data.from + " bis " + data.to;
}

function renderTable() {
    const grouped = document.getElementById("group-by-agent").checked;
    const thead = document.getElementById("stats-thead");
    const tbody = document.getElementById("stats-tbody");

    const cols = [
        { key: "task",             label: "Task",          cls: "left" },
        { key: "model",            label: "Model",         cls: "left" },
        { key: "provider",         label: "Provider",      cls: "left" }
    ];
    if (grouped) cols.push({ key: "agent_name", label: "Character", cls: "left" });
    cols.push(
        { key: "calls",            label: "Calls" },
        { key: "avg_duration",     label: "avg s" },
        { key: "min_duration",     label: "min s" },
        { key: "max_duration",     label: "max s" },
        { key: "p90_duration",     label: "p90 s" },
        { key: "avg_in_tokens",    label: "avg in" },
        { key: "avg_out_tokens",   label: "avg out" },
        { key: "avg_max_tokens",   label: "cfg max out" },
        { key: "avg_total_tokens", label: "avg in+out" },
        { key: "max_in_tokens",    label: "peak in" },
        { key: "max_total_tokens", label: "peak in+out" }
    );

    let th = "<tr>";
    for (const c of cols) {
        const isSort = c.key === SORT_KEY;
        const arrow = isSort ? '<span class="arrow">' + (SORT_DIR > 0 ? "↑" : "↓") + "</span>" : "";
        th += '<th class="' + (c.cls || "") + '" onclick="sortBy(\'' + c.key + '\')">'
            + escapeHtml(c.label) + arrow + "</th>";
    }
    th += "</tr>";
    thead.innerHTML = th;

    const sorted = CURRENT_ROWS.slice().sort((a, b) => {
        const va = a[SORT_KEY], vb = b[SORT_KEY];
        if (typeof va === "number") return (va - vb) * SORT_DIR;
        return String(va || "").localeCompare(String(vb || "")) * SORT_DIR;
    });

    if (!sorted.length) {
        tbody.innerHTML = '<tr><td class="empty" colspan="' + cols.length + '">No data in the selected period</td></tr>';
        return;
    }

    tbody.innerHTML = sorted.map(r => {
        let row = "<tr>";
        row += '<td class="left task">' + escapeHtml(r.task) + "</td>";
        row += '<td class="left model">' + escapeHtml(r.model) + "</td>";
        row += '<td class="left provider">' + escapeHtml(r.provider || "—") + "</td>";
        if (grouped) row += '<td class="left agent">' + escapeHtml(r.agent_name || "—") + "</td>";
        row += "<td>" + r.calls + "</td>";
        row += "<td>" + r.avg_duration.toFixed(2) + "</td>";
        row += "<td>" + r.min_duration.toFixed(2) + "</td>";
        row += "<td>" + r.max_duration.toFixed(2) + "</td>";
        row += "<td>" + r.p90_duration.toFixed(2) + "</td>";
        row += "<td>" + r.avg_in_tokens + "</td>";
        row += "<td>" + r.avg_out_tokens + "</td>";
        const cfg = r.avg_max_tokens;
        row += '<td class="' + (cfg ? "" : "dim") + '">' + (cfg || "—") + "</td>";
        row += "<td>" + r.avg_total_tokens + "</td>";
        row += "<td>" + r.max_in_tokens + "</td>";
        row += "<td>" + r.max_total_tokens + "</td>";
        row += "</tr>";
        return row;
    }).join("");
}

function sortBy(key) {
    if (SORT_KEY === key) SORT_DIR = -SORT_DIR;
    else { SORT_KEY = key; SORT_DIR = -1; }
    renderTable();
}

function escapeHtml(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

applyPreset("24h");
