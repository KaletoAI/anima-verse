
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
        // /characters/list ships {name, template, temporary} rows — this page
        // only ever needs the names.
        CHARS = ((await cResp.json()).characters || []).map(c => c.name);
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
                '<button class="btn btn-sm" onclick="openEdit(\'' + escJs(u.id) + '\')">Edit</button>' +
                '<button class="btn btn-sm btn-danger" onclick="deleteUser(\'' + escJs(u.id) + '\')">Del</button>' +
            '</td>' +
        '</tr>';
    }).join('');
}

function openEdit(userId) {
    EDIT_ID = userId;
    const u = userId ? USERS.find(x => x.id === userId) : null;
    document.getElementById('modal-title').textContent = u ? 'Edit user' : 'Create user';
    document.getElementById('edit-username').value = u ? u.username : '';
    document.getElementById('edit-role').value = u ? u.role : 'user';
    document.getElementById('edit-password').value = '';
    document.getElementById('edit-password-label').textContent = u ? 'Password (empty = unchanged)' : 'Password';
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

    if (!username) { err.textContent = 'Username is required'; err.style.display = 'block'; return; }
    if (!EDIT_ID && !password) { err.textContent = 'Password is required'; err.style.display = 'block'; return; }

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
        const body = await resp.json().catch(() => ({}));
        const wasEdit = !!EDIT_ID;
        closeEdit();
        toast(wasEdit ? 'User updated' : 'User created');
        // A password reset revokes the old credential, so the server ends the
        // target's sessions (its own survives when an admin resets their own
        // password). Say so, with the count the server returned.
        if (password && wasEdit) {
            const n = body.sessions_ended || 0;
            showNote('Password reset for "' + username + '". '
                + n + ' session(s) of that account were signed out.');
        } else {
            showNote('');
        }
        await loadAll();
    } catch (e) {
        err.textContent = 'Connection error: ' + e.message;
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

function showNote(msg) {
    const el = document.getElementById('reset-note');
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('show', !!msg);
}

// ── Own password (POST /auth/password) ────────────────────────────────
// The route takes the account from the SESSION, so this form needs no user id
// — an admin can only ever change their own password here. The server checks
// the current password through the login throttle and ends every OTHER
// session of the account; this page's session survives.
const PW_MIN_LENGTH = 8;

async function changeOwnPassword() {
    const cur = document.getElementById('pw-current').value;
    const next = document.getElementById('pw-new').value;
    const rep = document.getElementById('pw-repeat').value;
    const btn = document.getElementById('pw-submit');
    if (!cur || !next || !rep) { pwMsg('All three fields are required', true); return; }
    if (next !== rep) { pwMsg('The two new passwords do not match', true); return; }
    if (next.length < PW_MIN_LENGTH) {
        pwMsg('The new password must be at least ' + PW_MIN_LENGTH + ' characters long', true);
        return;
    }
    btn.disabled = true;
    pwMsg('', false);
    try {
        const resp = await fetch('/auth/password', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: cur, new_password: next })
        });
        const d = await resp.json().catch(() => ({}));
        if (!resp.ok) { pwMsg(d.detail || 'Could not change the password', true); return; }
        const n = d.sessions_ended || 0;
        pwMsg('Password changed.' + (n > 0 ? ' ' + n + ' other session(s) were signed out.' : ''), false);
        document.getElementById('pw-current').value = '';
        document.getElementById('pw-new').value = '';
        document.getElementById('pw-repeat').value = '';
    } catch (e) {
        pwMsg('Connection error: ' + e.message, true);
    } finally {
        btn.disabled = false;
    }
}

function pwMsg(msg, isError) {
    const el = document.getElementById('pw-msg');
    el.textContent = msg || '';
    el.className = 'pw-msg' + (isError ? ' error' : '');
}

// A value that ends up INSIDE an inline onclick="fn('…')" crosses two
// grammars: escape it for the single-quoted JS literal first, then for the
// double-quoted HTML attribute. Same shape as rtJs() in settings-routing.js.
function escJs(s) {
    return escapeHtml(String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function toast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + (type === 'error' ? 'error' : '') + ' show';
    setTimeout(() => t.classList.remove('show'), 2500);
}

loadAll();
