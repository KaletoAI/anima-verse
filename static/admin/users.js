
let USERS = [];
let CHARS = [];
let EDIT_ID = null;

async function loadAll() {
    try {
        const [uResp, cResp] = await Promise.all([
            fetch('/auth/users'),
            fetch('/characters/list'),
        ]);
        if (uResp.status === 401 || uResp.status === 403) {
            const ret = encodeURIComponent(window.location.pathname);
            window.location.href = '/?return=' + ret;
            return;
        }
        USERS = (await uResp.json()).users || [];
        CHARS = (await cResp.json()).characters || [];
        renderTable();
    } catch (e) {
        toast('Error loading: ' + e.message, 'error');
    }
}

function renderTable() {
    const tb = document.getElementById('users-tbody');
    if (!USERS.length) {
        tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#8b949e;">No users</td></tr>';
        return;
    }
    tb.innerHTML = USERS.map(u => {
        const charList = (u.allowed_characters || []).join(', ') || '—';
        const roleClass = u.role === 'admin' ? 'role-admin' : 'role-user';
        return '<tr>' +
            '<td>' + escapeHtml(u.username) + '</td>' +
            '<td class="' + roleClass + '">' + escapeHtml(u.role) + '</td>' +
            '<td class="chars">' + escapeHtml(charList) + '</td>' +
            '<td>' + escapeHtml(u.last_login || '—') + '</td>' +
            '<td class="actions">' +
                '<button class="btn btn-sm" onclick="openEdit(\'' + u.id + '\')">Edit</button>' +
                '<button class="btn btn-sm btn-danger" onclick="deleteUser(\'' + u.id + '\')">Del</button>' +
            '</td>' +
        '</tr>';
    }).join('');
}

function openEdit(userId) {
    EDIT_ID = userId;
    const u = userId ? USERS.find(x => x.id === userId) : null;
    document.getElementById('modal-title').textContent = u ? 'User bearbeiten' : 'User anlegen';
    document.getElementById('edit-username').value = u ? u.username : '';
    document.getElementById('edit-role').value = u ? u.role : 'user';
    document.getElementById('edit-password').value = '';
    document.getElementById('edit-password-label').textContent = u ? 'Passwort (leer = nicht aendern)' : 'Passwort';
    document.getElementById('modal-error').style.display = 'none';

    const assigned = new Set(u ? u.allowed_characters : []);
    document.getElementById('edit-chars-box').innerHTML = CHARS.map(c =>
        '<label class="char-row"><input type="checkbox" value="' + escapeHtml(c) + '"' + (assigned.has(c) ? ' checked' : '') + '><span>' + escapeHtml(c) + '</span></label>'
    ).join('');
    document.getElementById('modal-bg').classList.add('show');
}

function toggleAllChars(checked) {
    document.querySelectorAll('#edit-chars-box input[type="checkbox"]').forEach(cb => { cb.checked = !!checked; });
}

function closeEdit() {
    document.getElementById('modal-bg').classList.remove('show');
    EDIT_ID = null;
}

async function saveEdit() {
    const username = document.getElementById('edit-username').value.trim();
    const role = document.getElementById('edit-role').value;
    const password = document.getElementById('edit-password').value;
    const chars = Array.from(document.querySelectorAll('#edit-chars-box input:checked')).map(i => i.value);
    const err = document.getElementById('modal-error');
    err.style.display = 'none';

    if (!username) { err.textContent = 'Benutzername erforderlich'; err.style.display = 'block'; return; }
    if (!EDIT_ID && !password) { err.textContent = 'Passwort erforderlich'; err.style.display = 'block'; return; }

    try {
        let resp;
        if (EDIT_ID) {
            const body = { username, role, allowed_characters: chars };
            if (password) body.password = password;
            resp = await fetch('/auth/users/' + EDIT_ID, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
            });
        } else {
            resp = await fetch('/auth/users', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, role, allowed_characters: chars })
            });
        }
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            err.textContent = d.detail || 'Save error';
            err.style.display = 'block';
            return;
        }
        closeEdit();
        toast(EDIT_ID ? 'User aktualisiert' : 'User angelegt');
        await loadAll();
    } catch (e) {
        err.textContent = 'Verbindungsfehler: ' + e.message;
        err.style.display = 'block';
    }
}

async function deleteUser(userId) {
    const u = USERS.find(x => x.id === userId);
    if (!u) return;
    if (!confirm('Really delete user "' + u.username + '"?')) return;
    try {
        const resp = await fetch('/auth/users/' + userId, { method: 'DELETE' });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            toast(d.detail || 'Error', 'error');
            return;
        }
        toast('User deleted');
        await loadAll();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"\']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + (type === 'error' ? 'error' : '') + ' show';
    setTimeout(() => t.classList.remove('show'), 2500);
}

loadAll();
