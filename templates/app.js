/* Life Reminder — 前端逻辑（由 index.html 拆出，无构建工具，直接由 /app.js 提供） */
let S = null; // global state
// API Key: 通过 URL 参数 ?api_key=xxx 设置，或 localStorage 持久化
const API_KEY = (() => {
    const urlParams = new URLSearchParams(window.location.search);
    const fromUrl = urlParams.get('api_key');
    if (fromUrl) { localStorage.setItem('reminder_api_key', fromUrl); return fromUrl; }
    return localStorage.getItem('reminder_api_key') || '';
})();
function apiHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (API_KEY) headers['X-API-Key'] = API_KEY;
    const token = getToken();
    if (token) headers['X-Auth-Token'] = token;
    return headers;
}

// ─── Auth (多账号) ───
const TOKEN_KEY = 'reminder_token';
let authMode = 'login';
let authStatus = null;
// true = 系统已启用账号体系（必须登录，登录页不可关闭）
// false = 开放模式下用户主动打开注册/登录页（可返回）
let authForced = false;

function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(token) {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
}

async function fetchAuthStatus() {
    try {
        const res = await fetch('/api/auth/status', { headers: apiHeaders() });
        if (!res.ok) return null;
        return await res.json();
    } catch(e) {
        console.error('账号状态获取失败', e);
        return null;
    }
}

function authError(msg) {
    const box = document.getElementById('authError');
    if (!box) return;
    box.textContent = msg || '';
    box.classList.toggle('show', !!msg);
}

function switchAuth(mode) {
    const isRegister = mode === 'register' && authStatus && authStatus.registration_enabled !== false;
    authMode = isRegister ? 'register' : 'login';
    const registering = authMode === 'register';
    document.getElementById('tab-login').classList.toggle('active', !registering);
    document.getElementById('tab-register').classList.toggle('active', registering);
    document.getElementById('authConfirmField').style.display = registering ? 'block' : 'none';
    document.getElementById('authSubmit').textContent = registering ? '注册并登录' : '登录';
    document.getElementById('auth_pass').setAttribute('autocomplete', registering ? 'new-password' : 'current-password');
    paintAuthOptions();
    authError('');
}

function paintAuthOptions() {
    const status = authStatus || {};
    const legacy = status.legacy || { reminders: 0, logs: 0 };
    const hasLegacy = (legacy.reminders || 0) + (legacy.logs || 0) > 0;
    const registering = authMode === 'register';
    const allowed = status.registration_enabled !== false;

    document.getElementById('tab-register').style.display = allowed ? 'block' : 'none';
    const claimRow = document.getElementById('authClaim');
    claimRow.style.display = (registering && hasLegacy) ? 'flex' : 'none';
    document.getElementById('authClaimBox').checked = registering && hasLegacy;

    const subtitle = document.getElementById('authSubtitle');
    if (status.accounts === 0) subtitle.textContent = '首次使用：创建你的账号';
    else subtitle.textContent = registering ? '创建新账号，数据与其他账号隔离' : '登录后查看你的提醒';

    const hint = document.getElementById('authHint');
    if (registering && hasLegacy) hint.textContent = '勾选后可把当前未登录模式下的提醒与历史迁移到新账号';
    else if (allowed) hint.textContent = '账号数据相互隔离，互不可见';
    else hint.textContent = '管理员已关闭自助注册';

    // 强制登录（已有账号）时不允许关闭；开放模式下主动打开可随时返回
    const dismiss = document.getElementById('authDismiss');
    dismiss.style.display = authForced ? 'none' : 'block';
    dismiss.textContent = registering ? '暂不注册，返回首页' : '暂不登录，返回首页';
}

async function openAuth(mode, status, forced) {
    authStatus = status || await fetchAuthStatus() || {
        accounts: 1, login_required: true, registration_enabled: true, legacy: { reminders: 0, logs: 0 }
    };
    authForced = forced !== undefined ? !!forced : !!authStatus.login_required;
    document.getElementById('authScreen').classList.add('show');
    switchAuth(mode || (authStatus.accounts === 0 ? 'register' : 'login'));
}

function openRegister() { openAuth('register', null, false); }

function isAuthVisible() {
    return document.getElementById('authScreen').classList.contains('show');
}

function hideAuth() {
    document.getElementById('authScreen').classList.remove('show');
}

function dismissAuth() {
    // 已有账号时必须登录，不允许跳过
    if (authForced) return;
    hideAuth();
}

async function submitAuth() {
    const username = document.getElementById('auth_user').value.trim();
    const password = document.getElementById('auth_pass').value;
    const confirmPass = document.getElementById('auth_pass2').value;
    const claim = document.getElementById('authClaimBox').checked;
    const registering = authMode === 'register';

    if (!username) return authError('请输入用户名');
    if (!password) return authError('请输入密码');
    if (registering && password !== confirmPass) return authError('两次输入的密码不一致');

    const body = { username, password };
    if (registering) { body.confirm = confirmPass; body.claim_legacy = claim; }

    const btn = document.getElementById('authSubmit');
    btn.disabled = true;
    try {
        const res = await fetch(registering ? '/api/auth/register' : '/api/auth/login', {
            method: 'POST', headers: apiHeaders(), body: JSON.stringify(body)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.token) {
            authError(data.error || '操作失败，请重试');
            return;
        }
        setToken(data.token);
        document.getElementById('auth_pass').value = '';
        document.getElementById('auth_pass2').value = '';
        authStatus = null;
        authForced = false;
        hideAuth();
        await sync();
        if (registering) {
            showToast(data.claimed ? `账号创建成功，已继承 ${data.claimed} 条任务` : '账号创建成功');
        } else {
            showToast('登录成功');
        }
    } catch(e) {
        console.error('账号操作失败', e);
        authError('网络异常，请稍后重试');
    } finally {
        btn.disabled = false;
    }
}

async function logoutAllDevices() {
    if (!confirm('确认退出其他设备？当前设备保持登录，其他设备需要重新登录。')) return;
    try {
        const res = await fetch('/api/auth/logout-all', { method: 'POST', headers: apiHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showToast(data.error || '操作失败', 'times-circle', 'var(--c-red)');
            return;
        }
        if (data.token) setToken(data.token);
        showToast(`已退出其他设备（${data.removed} 个会话）`);
    } catch(e) {
        console.error('退出其他设备失败', e);
        showToast('操作失败', 'times-circle', 'var(--c-red)');
    }
}

async function deleteAccount() {
    const box = document.getElementById('delError');
    const fail = (msg) => { box.textContent = msg; box.classList.add('show'); };
    box.classList.remove('show');

    const confirmName = document.getElementById('del_username').value.trim();
    const password = document.getElementById('del_password').value;
    const currentUser = (S && S.account && S.account.user) || '';
    if (!confirmName) return fail('请输入用户名以确认注销');
    if (confirmName !== currentUser) return fail('用户名与当前账号不一致');
    if (!password) return fail('请输入登录密码');
    if (!confirm('最后确认：账号及其全部提醒与历史都会被永久删除，继续？')) return;

    try {
        const res = await fetch('/api/auth/account', {
            method: 'DELETE', headers: apiHeaders(),
            body: JSON.stringify({ password, confirm_username: confirmName })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) return fail(data.error || '注销失败');

        closeSheet();
        setToken('');
        S = null;
        hideAuth();
        showToast(`账号已注销（删除提醒 ${data.reminders_deleted} 条、记录 ${data.logs_deleted} 条）`, 'user-minus', 'var(--c-red)');
        if (data.remaining_accounts > 0) {
            await openAuth('login');
        } else {
            authStatus = null;
            await sync();
        }
    } catch(e) {
        console.error('注销账号失败', e);
        fail('网络异常，请稍后重试');
    }
}

async function logout() {
    if (!confirm('确认退出当前账号？')) return;
    try {
        await fetch('/api/auth/logout', { method: 'POST', headers: apiHeaders() });
    } catch(e) {
        console.error('退出登录失败', e);
    }
    setToken('');
    S = null;
    hideAuth();
    await openAuth('login');
}

async function saveNickname() {
    const input = document.getElementById('nick_input');
    const value = input.value.trim();
    const box = document.getElementById('nickError');
    const fail = (msg) => { box.textContent = msg; box.classList.add('show'); };
    box.classList.remove('show');

    if (value.length > 20) return fail('昵称不能超过 20 个字符');

    try {
        const res = await fetch('/api/auth/profile', {
            method: 'POST', headers: apiHeaders(), body: JSON.stringify({ nickname: value })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) return fail(data.error || '保存失败');
        closeSheet();
        await sync();
        showToast(value ? '昵称已更新' : '已恢复显示用户名');
    } catch(e) {
        console.error('保存昵称失败', e);
        fail('网络异常，请稍后重试');
    }
}

// ─── Webhook 测试推送 ───
async function testWebhook(channel, inputId, btn) {
    const url = (document.getElementById(inputId).value || '').trim();
    if (!url) {
        showToast('请先填写该渠道的 Webhook 地址', 'triangle-exclamation', '#ff9f0a');
        return;
    }
    const originalText = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '发送中...'; }
    try {
        const res = await fetch('/api/settings/test-webhook', {
            method: 'POST', headers: apiHeaders(), body: JSON.stringify({ channel, url })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showToast(data.error || '测试推送失败', 'times-circle', 'var(--c-red)');
            return;
        }
        showToast(data.message || '测试消息已发送', 'check-circle', 'var(--c-green)');
    } catch(e) {
        console.error('testWebhook failed', e);
        showToast('测试推送失败', 'times-circle', 'var(--c-red)');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = originalText; }
    }
}

// ─── 数据备份 ───
async function exportBackup() {
    try {
        const res = await fetch('/api/export', { headers: apiHeaders() });
        if (!res.ok) {
            showToast('导出失败', 'times-circle', 'var(--c-red)');
            return;
        }
        const blob = await res.blob();
        const link = document.createElement('a');
        const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
        link.href = URL.createObjectURL(blob);
        link.download = `life-reminder-backup-${stamp}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
        showToast('备份已导出');
    } catch(e) {
        console.error('exportBackup failed', e);
        showToast('导出失败', 'times-circle', 'var(--c-red)');
    }
}

async function importBackup(input) {
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    if (!confirm(`确认导入备份文件「${file.name}」？\n\u2022 按「标题+时间+重复」去重后新增\n\u2022 不会覆盖或删除现有数据`)) return;

    try {
        const text = await file.text();
        let payload;
        try {
            payload = JSON.parse(text);
        } catch(parseError) {
            showToast('备份文件不是有效的 JSON', 'times-circle', 'var(--c-red)');
            return;
        }
        const res = await fetch('/api/import', {
            method: 'POST', headers: apiHeaders(),
            body: JSON.stringify({ reminders: payload.reminders })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showToast(data.error || '导入失败', 'times-circle', 'var(--c-red)');
            return;
        }
        await sync();
        showToast(`导入完成：新增 ${data.added} 条，跳过重复 ${data.skipped} 条，忽略无效 ${data.invalid} 条`);
    } catch(e) {
        console.error('importBackup failed', e);
        showToast('导入失败', 'times-circle', 'var(--c-red)');
    }
}

async function claimLegacyData() {
    const legacy = (S && S.account && S.account.legacy) || {};
    const total = (legacy.reminders || 0) + (legacy.logs || 0);
    if (!total) { showToast('没有可导入的遗留数据', 'info-circle', 'var(--c-text3)'); return; }
    if (!confirm(`确认把 ${legacy.reminders || 0} 条遗留提醒与 ${legacy.logs || 0} 条历史记录导入当前账号？`)) return;

    try {
        const res = await fetch('/api/auth/claim-legacy', { method: 'POST', headers: apiHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showToast(data.error || '导入失败', 'times-circle', 'var(--c-red)');
            return;
        }
        await sync();
        showToast(`已导入 ${data.reminders} 条提醒, ${data.logs} 条记录`);
    } catch(e) {
        console.error('导入遗留数据失败', e);
        showToast('导入失败', 'times-circle', 'var(--c-red)');
    }
}

async function changePassword() {
    const oldPass = document.getElementById('pw_old').value;
    const newPass = document.getElementById('pw_new').value;
    const confirmPass = document.getElementById('pw_confirm').value;
    const box = document.getElementById('pwError');
    const fail = (msg) => { box.textContent = msg; box.classList.add('show'); };
    box.classList.remove('show');

    if (!oldPass) return fail('请输入原密码');
    if (!newPass || newPass.length < 6) return fail('新密码至少 6 位');
    if (newPass !== confirmPass) return fail('两次输入的新密码不一致');

    try {
        const res = await fetch('/api/auth/password', {
            method: 'POST', headers: apiHeaders(),
            body: JSON.stringify({ old_password: oldPass, new_password: newPass, confirm: confirmPass })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) return fail(data.error || '修改失败');
        if (data.token) setToken(data.token);
        document.getElementById('pw_old').value = '';
        document.getElementById('pw_new').value = '';
        document.getElementById('pw_confirm').value = '';
        closeSheet();
        showToast('密码已更新，其他设备需重新登录');
        sync();
    } catch(e) {
        console.error('修改密码失败', e);
        fail('网络异常，请稍后重试');
    }
}

// ─── Clock ───
function tickClock() {
    const now = new Date();
    document.getElementById('clock').textContent = now.toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'});
}
setInterval(tickClock, 1000); tickClock();

// ─── Data Sync ───
async function sync() {
    try {
        const res = await fetch('/api/state', { headers: apiHeaders() });
        if (res.status === 401) {
            // 会话失效：清除本地 token 并回到登录界面
            setToken('');
            S = null;
            if (isAuthVisible()) {
                // 登录页已展示：只刷新账号状态，不重建表单（避免清掉用户正在输入的内容）
                authStatus = await fetchAuthStatus();
                authForced = true;
                paintAuthOptions();
            } else {
                await openAuth('login', null, true);
            }
            return;
        }
        const payload = await res.json();
        if (!res.ok) {
            console.error('sync failed', payload);
            return;
        }
        S = payload;
        // 仅在拿到会话（已登录）时收起登录页；开放模式下用户主动打开的注册页不受轮询影响
        if (S.account && S.account.user && isAuthVisible()) hideAuth();
        if (S.version) document.getElementById('appVersion').textContent = S.version;
        
        // Check persistence health
        const warn = document.getElementById('persistWarning');
        if (S.persistence && S.persistence.status !== 'ok') {
            warn.style.display = 'flex';
        } else {
            warn.style.display = 'none';
        }

        paintHome();
        paintData();
        paintLogs();
        paintSettings();
    } catch(e) { console.error('sync failed', e); }
}

// ─── Home View ───
function paintHome() {
    const all = S.db.reminders;
    const pending = all.filter(r => r.status === 'pending').sort((a,b) => a.time.localeCompare(b.time));
    const doneCount = all.filter(r => r.status === 'completed').length;
    const total = all.length;
    const pct = total > 0 ? Math.round(doneCount / total * 100) : 0;

    // Greeting
    const h = new Date().getHours();
    const g = h < 6 ? '夜深了' : h < 9 ? '早上好' : h < 12 ? '上午好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好';
    document.getElementById('greetingText').textContent = g;

    // 多账号：问候语后跟上昵称（未设置昵称时显示用户名，开放模式不显示）
    const account = S.account || {};
    const displayName = account.nickname || account.user || '';
    const nameEl = document.getElementById('greetingName');
    nameEl.textContent = displayName;
    nameEl.classList.toggle('show', !!displayName);

    // Hero
    document.getElementById('heroNext').textContent = pending.length > 0 ? pending[0].title : '今日任务已清空 ✨';
    document.getElementById('heroSub').textContent = `今日 ${doneCount}/${total} 已完成`;
    document.getElementById('progressPct').textContent = pct + '%';
    const circumference = 97.4;
    document.getElementById('progressRing').style.strokeDashoffset = circumference - (circumference * pct / 100);

    // Counters
    document.getElementById('pendingCount').textContent = pending.length;
    document.getElementById('totalCount').textContent = `共 ${total} 项`;

    // 多账号：开放模式提示（已登录或已有账号时隐藏）
    const prompt = document.getElementById('accountPrompt');
    if (prompt) {
        prompt.style.display = (account.login_required === false && !account.user) ? 'flex' : 'none';
    }

    // Task List
    const container = document.getElementById('taskContainer');
    if (all.length === 0) {
        container.innerHTML = '<div class="empty-state"><i class="far fa-circle-check"></i><p>还没有任何任务<br>点击下方 + 创建第一个提醒</p></div>';
        return;
    }

    // Build repeat label
    function repeatLabel(r) {
        const rep = r.repeat || 'daily';
        if (rep === 'daily') return '每天';
        if (rep === 'workday') return '工作日';
        if (rep === 'once') return '仅一次';
        if (rep === 'yearly') return '每年';
        if (rep.startsWith('monthly:')) {
            const dayExpr = rep.split(':')[1];
            return dayExpr === 'last' ? '每月最后一天' : `每月${Number(dayExpr)}日`;
        }
        if (rep.startsWith('lunar:')) {
            const label = lunarLabelFromRepeat(rep);
            return label ? `每年农历${label}` : '每年农历';
        }
        if (rep.startsWith('weekly:')) return '每周' + rep.split(':')[1].split(',').map(d => ({mon:'一',tue:'二',wed:'三',thu:'四',fri:'五',sat:'六',sun:'日'}[d]||d)).join('、');
        return rep;
    }

    const sortMode = localStorage.getItem('taskSortMode') || 'time';
    const sortRev = localStorage.getItem('taskSortRev') === 'true';
    
    // Update Control UI
    const modeNameMap = { time: '按任务时间', prio: '按优先级', created: '按创建时间', manual: '自定义排序' };
    document.getElementById('sortLabel').textContent = modeNameMap[sortMode] || '排序';
    document.getElementById('sortIcon').className = sortMode === 'manual' ? 'fas fa-fingerprint' : (sortRev ? 'fas fa-arrow-up-wide-short' : 'fas fa-arrow-down-short-wide');

    document.querySelectorAll('.sort-item').forEach(item => {
        const isActive = item.dataset.mode === sortMode;
        item.classList.toggle('active', isActive);
        const icon = item.querySelector('i');
        if (isActive) {
            if (sortMode === 'manual') icon.className = 'fas fa-fingerprint';
            else icon.className = sortRev ? 'fas fa-arrow-up-wide-short' : 'fas fa-arrow-down-short-wide';
        } else {
            if (item.dataset.mode === 'manual') icon.className = 'fas fa-fingerprint';
            else icon.className = 'fas fa-arrows-up-down';
        }
    });

    const sorted = all.slice().sort((a,b) => {
        if (a.status === 'completed' && b.status !== 'completed') return 1;
        if (a.status !== 'completed' && b.status === 'completed') return -1;
        
        let res = 0;
        if (sortMode === 'time') res = a.time.localeCompare(b.time);
        else if (sortMode === 'created') res = (a.created_at || '').localeCompare(b.created_at || '');
        else if (sortMode === 'prio') {
            const pm = { 'high': 3, 'mid': 2, 'low': 1 };
            res = (pm[b.priority] || 1) - (pm[a.priority] || 1);
            if (res === 0) res = a.time.localeCompare(b.time);
        }
        else if (sortMode === 'manual') {
            const manualOrder = JSON.parse(localStorage.getItem('taskManualOrder') || '[]');
            const idxA = manualOrder.indexOf(a.id);
            const idxB = manualOrder.indexOf(b.id);
            if (idxA !== -1 && idxB !== -1) res = idxA - idxB;
            else if (idxA !== -1) res = -1;
            else if (idxB !== -1) res = 1;
            else res = a.time.localeCompare(b.time);
        }

        return sortRev ? -res : res;
    });

    container.innerHTML = sorted.map((r, idx) => `
        <div class="task pri-${r.priority || 'low'} ${r.status==='completed'?'done':''}"
             id="task-${r.id}" data-id="${r.id}" data-idx="${idx}">
            <div class="drag-handle" style="touch-action:none"><i class="fas fa-grip-vertical"></i></div>
            <div class="task-body">
                <div class="task-title">${r.title}</div>
                <div class="task-sub">
                    <i class="far fa-clock"></i> ${r.time}
                    <span style="color:var(--c-${r.priority==='high'?'red':r.priority==='mid'?'orange':'green'}); font-weight:600;">
                        ${r.priority==='high'?'紧急':r.priority==='mid'?'重要':'普通'}
                    </span>
                    · ${repeatLabel(r)}
                </div>
            </div>
            <div class="task-actions">
                <button class="act-btn check ${r.status==='completed'?'checked':''}" onclick="toggleStatus('${r.id}','${r.status}')">
                    <i class="fas fa-${r.status==='completed'?'rotate-left':'check'}"></i>
                </button>
                <button class="act-btn edit" onclick="editTask('${r.id}')"><i class="fas fa-pen"></i></button>
                <button class="act-btn delete" onclick="doAction('${r.id}','delete')"><i class="fas fa-trash-can"></i></button>
            </div>
        </div>
    `).join('');

    if (window.newTaskId) {
        setTimeout(() => {
            const el = document.getElementById('task-' + window.newTaskId);
            if (el) {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                el.style.transition = 'all 0.5s';
                el.style.background = 'var(--c-surface2)';
                el.style.transform = 'scale(1.02)';
                setTimeout(() => { el.style.background = ''; el.style.transform = ''; }, 1200);
            }
            window.newTaskId = undefined;
        }, 150);
    }
    
    // Setup Sortable
    if (window.taskSortableInst) window.taskSortableInst.destroy();
    if (sortMode === 'manual' && typeof Sortable !== 'undefined') {
        window.taskSortableInst = new Sortable(container, {
            animation: 200,
            delay: 200,
            delayOnTouchOnly: true,
            handle: '.task', // Allow tapping anywhere to drag
            ghostClass: 'dragging',
            onEnd: function () {
                const order = Array.from(container.children).map(c => c.dataset.id).filter(id => id);
                localStorage.setItem('taskManualOrder', JSON.stringify(order));
                showToast('排序已保存', 'check', 'var(--c-purple)');
            }
        });
    }
}

function toggleSortMenu(e) {
    e.stopPropagation();
    document.getElementById('sortMenu').classList.toggle('show');
}

// Global click to close menu
document.addEventListener('click', () => {
    const menu = document.getElementById('sortMenu');
    if (menu) menu.classList.remove('show');
});

function applySort(mode) {
    let current = localStorage.getItem('taskSortMode') || 'time';
    let rev = localStorage.getItem('taskSortRev') === 'true';

    if (current === mode) {
        localStorage.setItem('taskSortRev', (!rev).toString());
    } else {
        localStorage.setItem('taskSortMode', mode);
        localStorage.setItem('taskSortRev', 'false');
    }

    if (mode === 'manual' && !localStorage.getItem('taskManualOrder')) {
        const order = Array.from(document.getElementById('taskContainer').children).map(c => c.dataset.id).filter(id => id);
        localStorage.setItem('taskManualOrder', JSON.stringify(order));
    }
    paintHome();
}
function dragEnd(e) { e.currentTarget.classList.remove('dragging'); dragSrcId = null; }

// ─── Toggle Complete / Uncomplete (需求3) ───
async function toggleStatus(id, currentStatus) {
    const r = S.db.reminders.find(x => x.id === id);
    if (!r) return;
    const newStatus = currentStatus === 'completed' ? 'pending' : 'completed';
    await fetch(`/api/reminders/${id}`, {
        method: 'PUT',
        headers: apiHeaders(),
        body: JSON.stringify({
            title: r.title,
            time: r.time,
            repeat: r.repeat,
            priority: r.priority,
            status: newStatus
        })
    });
    sync();
}

// ─── Edit Task (需求2) ───
function editTask(id) {
    const r = S.db.reminders.find(x => x.id === id);
    if (!r) return;
    document.getElementById('f_editId').value = r.id;
    document.getElementById('f_title').value = r.title;
    document.getElementById('f_time').value = r.time.includes(' ') ? r.time.split(' ')[1] : r.time;
    document.getElementById('f_prio').value = r.priority || 'low';
    document.getElementById('addSheetTitle').textContent = '编辑任务';
    document.querySelector('#sheet-add .btn-submit').textContent = '保存修改';

    // Restore repeat mode
    const rep = r.repeat || 'daily';
    document.querySelectorAll('#repeatMode .chip').forEach(c => c.classList.remove('active'));
    const existingDate = r.time.includes(' ') ? r.time.split(' ')[0] : '';

    if (rep.startsWith('lunar:')) {
        document.querySelector('#repeatMode .chip[data-val="lunar"]').classList.add('active');
        const lunarDate = solarDateFromLunarRepeat(rep);
        const label = lunarLabelFromRepeat(rep);
        document.getElementById('weekdayField').style.display = 'none';
        document.getElementById('monthdayField').style.display = 'none';
        document.getElementById('dateField').style.display = 'block';
        document.getElementById('f_date').value = lunarDate;
        document.getElementById('dateFieldLabel').textContent = '提醒日期';
        document.getElementById('calendarPicker').style.display = 'none';
        document.getElementById('dateValStr').textContent = label ? `农历${label}` : lunarDate;
        document.getElementById('selectedDateDisplay').style.display = 'flex';
    } else if (rep === 'yearly') {
        document.querySelector('#repeatMode .chip[data-val="yearly"]').classList.add('active');
        document.getElementById('weekdayField').style.display = 'none';
        document.getElementById('monthdayField').style.display = 'none';
        document.getElementById('dateField').style.display = 'block';
        document.getElementById('f_date').value = existingDate;
        document.getElementById('dateFieldLabel').textContent = '提醒日期';
        document.getElementById('calendarPicker').style.display = 'none';
        document.getElementById('dateValStr').textContent = existingDate
            ? `${existingDate} · 每年 ${Number(existingDate.slice(5, 7))} 月 ${Number(existingDate.slice(8, 10))} 日`
            : '';
        document.getElementById('selectedDateDisplay').style.display = 'flex';
    } else if (rep.startsWith('monthly:')) {
        document.querySelector('#repeatMode .chip[data-val="monthly"]').classList.add('active');
        initMonthdayOptions();
        document.getElementById('f_monthday').value = rep.split(':')[1] || '1';
        document.getElementById('weekdayField').style.display = 'none';
        document.getElementById('dateField').style.display = 'none';
        document.getElementById('monthdayField').style.display = 'block';
    } else if (rep === 'daily' || rep === 'workday' || rep === 'once') {
        document.querySelector(`#repeatMode .chip[data-val="${rep}"]`).classList.add('active');
        document.getElementById('weekdayField').style.display = 'none';
        document.getElementById('monthdayField').style.display = 'none';
        document.getElementById('dateField').style.display = rep === 'once' ? 'block' : 'none';
        if (rep === 'once') {
            document.getElementById('f_date').value = existingDate;
            document.getElementById('dateFieldLabel').textContent = '提醒日期';
            document.getElementById('calendarPicker').style.display = 'none';
            document.getElementById('dateValStr').textContent = document.getElementById('f_date').value;
            document.getElementById('selectedDateDisplay').style.display = 'flex';
        }
    } else if (rep.startsWith('weekly:')) {
        document.querySelector('#repeatMode .chip[data-val="weekly"]').classList.add('active');
        document.getElementById('weekdayField').style.display = 'block';
        document.getElementById('dateField').style.display = 'none';
        document.getElementById('monthdayField').style.display = 'none';
        const days = rep.split(':')[1].split(',');
        document.querySelectorAll('#weekdayPicker .chip').forEach(c => {
            c.classList.toggle('active', days.includes(c.dataset.val));
        });
    }

    openSheet('add');
}

// ─── Data View ───
function paintData() {
    const allLogs = S.logs || [];

    // 历史统计：优先使用后端全量统计，缺失时按当前列表兜底计算
    const stats = S.log_stats || null;
    const todayKey = dayKey(new Date());
    document.getElementById('histToday').textContent = stats
        ? stats.today
        : allLogs.filter(l => dayKey(parseLogDate(l)) === todayKey).length;
    document.getElementById('histTotal').textContent = stats ? stats.total : allLogs.length;
    document.getElementById('histDone').textContent = stats
        ? stats.completed
        : allLogs.filter(l => l.completed_at).length;

    // Log List with action buttons (需求1)
    const logC = document.getElementById('logContainer');
    const logs = allLogs.slice().sort((a, b) => parseLogDate(b) - parseLogDate(a));
    if (logs.length === 0) {
        logC.innerHTML = '<div class="empty-state"><i class="far fa-bell-slash"></i><p>暂无通知记录<br>提醒触发后会在这里留下历史</p></div>';
        return;
    }

    // 按日期分组渲染历史记录
    let html = '';
    let lastKey = null;
    logs.forEach(l => {
        const d = parseLogDate(l);
        const key = dayKey(d);
        if (key !== lastKey) {
            lastKey = key;
            const groupCount = logs.filter(x => dayKey(parseLogDate(x)) === key).length;
            html += `<div class="log-group-head"><span class="bar"></span>${dayLabel(d)}<span class="cnt">${groupCount}</span></div>`;
        }
        html += `
        <div class="log-entry ${l.hidden ? 'hidden-log' : ''}" id="log-${l.id}">
            <div class="log-icon ${l.completed_at ? 'completed' : 'triggered'}">
                <i class="fas fa-${l.completed_at ? 'check' : 'bell'}"></i>
            </div>
            <div class="log-body">
                <h4>${l.title}</h4>
                <p>${timeLabel(d)} · <span class="log-status ${l.completed_at ? 'done' : 'pending'}">${l.completed_at ? '已处理' : '已通知'}</span></p>
            </div>
            <div class="log-actions">
                <button class="act-btn check ${l.completed_at ? 'checked' : ''}" title="${l.completed_at ? '取消已处理' : '标记已处理'}" onclick="toggleLogComplete('${l.id}')"><i class="fas fa-${l.completed_at ? 'rotate-left' : 'check'}"></i></button>
                <button class="act-btn edit" title="稍后提醒（10 分钟后）" onclick="snoozeLog('${l.id}')"><i class="fas fa-clock"></i></button>
                <button class="act-btn" title="隐藏" onclick="hideLog('${l.id}')"><i class="fas fa-eye-slash"></i></button>
                <button class="act-btn" title="复用" onclick="reuseLog('${l.title}')"><i class="fas fa-copy"></i></button>
                <button class="act-btn delete" title="删除" onclick="deleteLog('${l.id}')"><i class="fas fa-trash-can"></i></button>
            </div>
        </div>`;
    });
    if (stats && stats.total > logs.length) {
        html += `<div class="log-more">仅展示最近 ${logs.length} 条，共 ${stats.total} 条历史记录</div>`;
    }
    logC.innerHTML = html;
}

// ─── History Helpers ───
function parseLogDate(l) {
    const d = new Date(l && l.triggered_at ? l.triggered_at : Date.now());
    return isNaN(d.getTime()) ? new Date() : d;
}
function dayKey(d) {
    return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}
function dayLabel(d) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const target = new Date(d); target.setHours(0, 0, 0, 0);
    const diff = Math.round((today - target) / 86400000);
    if (diff === 0) return '今天';
    if (diff === 1) return '昨天';
    if (diff === 2) return '前天';
    const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()];
    const md = `${d.getMonth() + 1}月${d.getDate()}日`;
    return d.getFullYear() === today.getFullYear() ? `${md} ${week}` : `${d.getFullYear()}年${md}`;
}
function timeLabel(d) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// ─── Log Actions ───
async function toggleLogComplete(id) {
    try {
        const res = await fetch(`/api/logs/complete/${id}`, { method: 'POST', headers: apiHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showToast(data.error || '操作失败', 'times-circle', 'var(--c-red)');
            return;
        }
        await sync();
        showToast(data.completed ? '已标记为已处理' : '已取消已处理');
    } catch(e) {
        console.error('toggleLogComplete failed', e);
        showToast('操作失败', 'times-circle', 'var(--c-red)');
    }
}

async function snoozeLog(id) {
    try {
        const res = await fetch('/api/reminders/snooze', {
            method: 'POST', headers: apiHeaders(), body: JSON.stringify({ log_id: id, minutes: 10 })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showToast(data.error || '创建稍后提醒失败', 'times-circle', 'var(--c-red)');
            return;
        }
        await sync();
        showToast(`已创建稍后提醒：${data.time}`, 'clock', 'var(--c-blue)');
    } catch(e) {
        console.error('snoozeLog failed', e);
        showToast('创建稍后提醒失败', 'times-circle', 'var(--c-red)');
    }
}

async function hideLog(id) {
    try {
        await fetch(`/api/logs/hide/${id}`, { method: 'POST', headers: apiHeaders() });
    } catch(e) { console.error('hideLog failed', e); }
    sync();
}
function reuseLog(title) {
    document.getElementById('f_editId').value = '';
    document.getElementById('f_title').value = title;
    openSheet('add');
    document.getElementById('addSheetTitle').textContent = '复用任务';
    document.querySelector('#sheet-add .btn-submit').textContent = '创建提醒';
}
async function deleteLog(id) {
    if (!confirm('确认删除该记录？')) return;
    try {
        await fetch(`/api/logs/${id}`, { method: 'DELETE', headers: apiHeaders() });
    } catch(e) { console.error('deleteLog failed', e); }
    sync();
}

// ─── Toggle Hidden Logs (需求1-补充) ───
let showHidden = false;
function toggleHiddenLogs() {
    showHidden = !showHidden;
    const container = document.getElementById('logContainer');
    const btn = document.getElementById('toggleHiddenBtn');
    if (showHidden) {
        container.classList.add('show-hidden');
        btn.classList.add('on');
        btn.textContent = '隐藏';
    } else {
        container.classList.remove('show-hidden');
        btn.classList.remove('on');
        btn.textContent = '显示已隐藏';
    }
}

// ─── System Logs (汉化) ───
function paintLogs() {
    const c = document.getElementById('termContainer');
    if (S.syslogs.length === 0) {
        c.innerHTML = '<div style="color:var(--c-text3); opacity:0.5; padding:20px; text-align:center;">等待系统输出...</div>';
        return;
    }
    const levelMap = { 'INFO': '信息', 'WARNING': '警告', 'ERROR': '错误', 'DEBUG': '调试', 'CRITICAL': '严重' };
    c.innerHTML = S.syslogs.map(l => {
        let localized = l;
        Object.entries(levelMap).forEach(([en, zh]) => {
            localized = localized.replace(` - ${en} - `, ` · ${zh} · `);
        });
        return `<div class="line">${localized}</div>`;
    }).join('');
    c.scrollTop = 0;
}

// ─── Settings ───
function paintSettings() {
    const dark = S.db.settings.dark_mode !== false;
    document.body.setAttribute('data-theme', dark ? '' : 'light');
    document.getElementById('darkToggle').className = 'toggle' + (dark ? ' on' : '');
    document.getElementById('darkDesc').textContent = dark ? '当前已开启' : '当前已关闭';

    // 多账号：当前登录账号卡片
    const account = S.account || {};
    const acctCard = document.getElementById('acctCard');
    if (account.user) {
        acctCard.style.display = 'flex';
        const displayName = account.nickname || account.user;
        document.getElementById('acctAvatar').textContent = displayName.slice(0, 1).toUpperCase();
        document.getElementById('acctName').textContent = displayName;
        const profile = account.profile || {};
        const prefix = account.nickname ? `@${account.user} · ` : '';
        document.getElementById('acctMeta').textContent =
            `${prefix}${profile.reminders || 0} 项任务 · ${profile.pending || 0} 项待办`;
    } else {
        acctCard.style.display = 'none';
    }

    // 昵称入口：仅登录后可用
    const nicknameGroup = document.getElementById('nicknameGroup');
    if (account.user) {
        nicknameGroup.style.display = 'block';
        document.getElementById('nicknameDesc').textContent =
            account.nickname ? `当前：${account.nickname}（留空可恢复用户名）` : '未设置（显示用户名）';
    } else {
        nicknameGroup.style.display = 'none';
    }

    // 未归属的遗留数据：允许登录后导入当前账号
    const legacy = account.legacy || {};
    const legacyTotal = (legacy.reminders || 0) + (legacy.logs || 0);
    const legacyGroup = document.getElementById('legacyGroup');
    if (account.user && legacyTotal > 0) {
        legacyGroup.style.display = 'block';
        document.getElementById('legacyDesc').textContent =
            `${legacy.reminders || 0} 条提醒 · ${legacy.logs || 0} 条历史记录`;
    } else {
        legacyGroup.style.display = 'none';
    }

    const wh = S.db.settings.webhooks || {};
    document.getElementById('w_wecom').value = wh.wecom || '';
    document.getElementById('w_ding').value = wh.dingtalk || '';
    document.getElementById('w_lark').value = wh.lark || '';
    document.getElementById('w_sms_phone').value = wh.sms_phone || '';
    document.getElementById('w_sms_api').value = wh.sms_api || '';
    document.getElementById('w_voice_api').value = wh.voice_api || '';

    // 安全状态：只展示账号登录保护状态（API Key 状态可通过容器日志查看）
    const accountProtected = account.login_required === true;
    const authEl = document.getElementById('authStatus');
    if (authEl) {
        if (accountProtected) {
            authEl.innerHTML = '<i class="fas fa-shield-halved" style="color:var(--c-green)"></i> <span style="color:var(--c-green)">账号保护已启用</span>';
        } else {
            authEl.innerHTML = '<i class="fas fa-triangle-exclamation" style="color:var(--c-orange)"></i> <span style="color:var(--c-orange)">尚未启用登录保护，建议注册账号</span>';
        }
    }
}

// ─── Actions ───
async function clearCompletedTasks() {
    const completed = (S.db.reminders || []).filter(r => r.status === 'completed');
    if (completed.length === 0) {
        showToast('没有已完成的任务', 'info-circle', 'var(--c-text3)');
        return;
    }
    if (!confirm(`确认删除所有 ${completed.length} 条已完成任务？此操作不可撤销。`)) return;
    try {
        const res = await fetch('/api/reminders/clear-completed', {
            method: 'POST',
            headers: apiHeaders()
        });
        const data = await res.json();
        await sync();
        showToast(`已删除 ${data.deleted} 条任务, ${data.logs_deleted} 条日志`);
    } catch(e) {
        console.error('clearCompletedTasks failed', e);
        showToast('操作失败', 'times-circle', 'var(--c-red)');
    }
}

async function doAction(id, type) {
    // 目前仅用于删除任务（完成/恢复由 toggleStatus 处理）
    if (type !== 'delete') return;
    if (!confirm('确认删除该任务？')) return;
    await fetch(`/api/reminders/${id}`, { method: 'DELETE', headers: apiHeaders() });
    sync();
}

// ─── Repeat Mode Toggle (需求5) ───
function pickRepeat(el) {
    el.parentElement.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    const val = el.dataset.val;
    const needDate = val === 'once' || val === 'yearly' || val === 'lunar';
    // 每年/农历每年只需月日，允许选择过去的日期
    calAllowPast = (val === 'yearly' || val === 'lunar');
    document.getElementById('weekdayField').style.display = val === 'weekly' ? 'block' : 'none';
    document.getElementById('monthdayField').style.display = val === 'monthly' ? 'block' : 'none';
    document.getElementById('dateField').style.display = needDate ? 'block' : 'none';
    if (val === 'monthly') initMonthdayOptions();
    if (needDate) {
        document.getElementById('dateFieldLabel').textContent =
            val === 'once' ? '选择日期'
                : (val === 'lunar' ? '选择农历日期（按农历月/日重复）' : '选择日期（每年按该月/日提醒）');
        document.getElementById('calendarPicker').style.display = 'block';
        document.getElementById('selectedDateDisplay').style.display = 'none';
        renderCalendar();
    }
}

// ─── 农历 / 每月 辅助 ───
function initMonthdayOptions() {
    const sel = document.getElementById('f_monthday');
    if (sel.options.length > 0) return;
    for (let d = 1; d <= 31; d++) {
        sel.innerHTML += `<option value="${d}">${d} 日</option>`;
    }
    sel.innerHTML += '<option value="last">最后一天</option>';
}

function lunarInfoFromDate(dateStr) {
    if (typeof Lunar === 'undefined' || !dateStr) return null;
    const parts = dateStr.split('-').map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) return null;
    const lunar = Lunar.fromDate(new Date(parts[0], parts[1] - 1, parts[2]));
    return {
        month: lunar.getMonth(),
        day: lunar.getDay(),
        label: (lunar.getMonth() < 0 ? '闰' : '') + lunar.getMonthInChinese() + '月' + lunar.getDayInChinese()
    };
}

function lunarRepeatFromDate(dateStr) {
    const info = lunarInfoFromDate(dateStr);
    if (!info) return null;
    const mm = String(Math.abs(info.month)).padStart(2, '0');
    const dd = String(info.day).padStart(2, '0');
    return info.month < 0 ? `lunar:-${mm}-${dd}` : `lunar:${mm}-${dd}`;
}

function lunarLabelFromRepeat(rep) {
    const matched = /^lunar:(-?\d{1,2})-(\d{1,2})$/.exec(rep || '');
    if (!matched || typeof Lunar === 'undefined') return '';
    const month = parseInt(matched[1], 10);
    const day = parseInt(matched[2], 10);
    const lunar = Lunar.fromYmd(new Date().getFullYear(), month, day);
    return (month < 0 ? '闰' : '') + lunar.getMonthInChinese() + '月' + lunar.getDayInChinese();
}

function solarDateFromLunarRepeat(rep) {
    const matched = /^lunar:(-?\d{1,2})-(\d{1,2})$/.exec(rep || '');
    if (!matched || typeof Lunar === 'undefined') return '';
    const month = parseInt(matched[1], 10);
    const day = parseInt(matched[2], 10);
    const solar = Lunar.fromYmd(new Date().getFullYear(), month, day).getSolar();
    return `${solar.getYear()}-${String(solar.getMonth()).padStart(2, '0')}-${String(solar.getDay()).padStart(2, '0')}`;
}

// ─── Time Picker (需求1，2) ───
function initTimePicker() {
    const hSelect = document.getElementById('tp_hour');
    const mSelect = document.getElementById('tp_min');
    if (hSelect.options.length === 0) {
        for (let i = 0; i < 24; i++) hSelect.innerHTML += `<option value="${String(i).padStart(2,'0')}">${String(i).padStart(2,'0')}</option>`;
        for (let i = 0; i < 60; i++) mSelect.innerHTML += `<option value="${String(i).padStart(2,'0')}">${String(i).padStart(2,'0')}</option>`;
    }
}
function toggleTimePicker() {
    const box = document.getElementById('timePickerBox');
    if (box.style.display === 'block') {
        box.style.display = 'none';
    } else {
        initTimePicker();
        const parts = document.getElementById('f_time').value.split(':');
        document.getElementById('tp_hour').value = parts[0] || '09';
        document.getElementById('tp_min').value = parts[1] || '00';
        box.style.display = 'block';
        // Auto scroll to make selected visible
        setTimeout(() => {
            document.getElementById('tp_hour').querySelector('option:checked')?.scrollIntoView({block:'center'});
            document.getElementById('tp_min').querySelector('option:checked')?.scrollIntoView({block:'center'});
        }, 10);
    }
}
function confirmTime() {
    const h = document.getElementById('tp_hour').value;
    const m = document.getElementById('tp_min').value;
    document.getElementById('f_time').value = `${h}:${m}`;
    document.getElementById('timePickerBox').style.display = 'none';
}

// ─── Calendar Picker (需求3) ───
let calYear, calMonth, calSelectedDate = null;
let calAllowPast = false;   // 每年/农历每年模式只需月日，允许选择过去的日期

function renderYearPicker() {
    const container = document.getElementById('calendarPicker');
    if (!container) return;

    let html = `<div class="cal-wrap">`;
    html += `<div class="cal-header" style="justify-content: center;">`;
    html += `<span>选择年份 (当前: ${calYear}年)</span>`;
    html += `</div>`;
    html += `<div class="cal-year-grid">`;
    
    const now = new Date();
    const currentYear = now.getFullYear();
    for (let y = currentYear; y <= 2100; y++) {
        html += `<div class="year-item ${y === calYear ? 'active' : ''}" onclick="renderCalendar(${y}, calMonth)">${y}</div>`;
    }
    
    html += `</div>`;
    html += `<div class="cal-actions" style="margin-top:14px;">`;
    html += `<button class="cal-btn-cancel" style="flex:1" onclick="renderCalendar(calYear, calMonth)">返回</button>`;
    html += `</div></div>`;
    
    container.innerHTML = html;
    
    // Scroll to active year
    setTimeout(() => {
        const active = container.querySelector('.year-item.active');
        if (active) active.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }, 50);
}

function renderCalendar(y, m) {
    const now = new Date();
    const baseYear = y !== undefined ? y : (calYear || now.getFullYear());
    const baseMonth = m !== undefined ? m : (calMonth !== undefined ? calMonth : now.getMonth());
    const normalizedDate = new Date(baseYear, baseMonth, 1);
    const maxDate = new Date(2100, 11, 1);
    const finalDate = normalizedDate > maxDate ? maxDate : normalizedDate;
    calYear = finalDate.getFullYear();
    calMonth = finalDate.getMonth();

    const firstDay = new Date(calYear, calMonth, 1).getDay(); // 0=Sun
    const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
    const daysInPrev = new Date(calYear, calMonth, 0).getDate();
    const startOffset = firstDay === 0 ? 6 : firstDay - 1; // Monday-first

    const monthNames = ['一月','二月','三月','四月','五月','六月','七月','八月','九月','十月','十一月','十二月'];
    const nextDisabled = calYear === 2100 && calMonth === 11;

    let html = `<div class="cal-wrap">`;
    html += `<div class="cal-header">`;
    html += `<button class="cal-nav" onclick="renderCalendar(${calYear},${calMonth - 1})"><i class="fas fa-chevron-left"></i></button>`;
    html += `<span onclick="renderYearPicker()">${calYear}年 ${monthNames[calMonth]}</span>`;
    html += `<button class="cal-nav"${nextDisabled ? ' disabled' : ` onclick="renderCalendar(${calYear},${calMonth + 1})"`}><i class="fas fa-chevron-right"></i></button>`;
    html += `</div>`;
    html += `<div class="cal-grid">`;
    ['一','二','三','四','五','六','日'].forEach(d => html += `<div class="cal-dow">${d}</div>`);

    // Previous month fill
    for (let i = startOffset - 1; i >= 0; i--) {
        html += `<div class="cal-day other disabled">${daysInPrev - i}</div>`;
    }
    // Current month
    const today = new Date();
    today.setHours(0,0,0,0);
    const tomorrow = new Date(today.getTime() + 86400000);
    const postTomorrow = new Date(today.getTime() + 86400000 * 2);

    for (let d = 1; d <= daysInMonth; d++) {
        const dObj = new Date(calYear, calMonth, d);
        const dateStr = `${calYear}-${String(calMonth+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        const isToday = dObj.getTime() === today.getTime();
        const isSelected = dateStr === calSelectedDate;
        const isPast = !calAllowPast && dObj < today;
        
        let relLabel = "";
        if (isToday) relLabel = "今天";
        else if (dObj.getTime() === tomorrow.getTime()) relLabel = "明天";
        else if (dObj.getTime() === postTomorrow.getTime()) relLabel = "后天";

        let lunarText = d;
        if (typeof Lunar !== 'undefined') {
            const l = Lunar.fromDate(dObj);
            lunarText = l.getDayInChinese();
            if (lunarText === '初一') lunarText = l.getMonthInChinese() + '月';
        }

        html += `
            <div class="cal-day${isToday ? ' today' : ''}${isSelected ? ' selected' : ''}${isPast ? ' disabled' : ''}" 
                 onclick="selectCalDay('${dateStr}')" style="position:relative">
                <div class="cal-day-box">
                    <span>${d}</span>
                    <span class="lunar">${lunarText}</span>
                </div>
                ${relLabel ? `<span class="cal-rel-label">${relLabel}</span>` : ''}
            </div>`;
    }
    // Next month fill
    const totalCells = startOffset + daysInMonth;
    const remaining = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
    for (let i = 1; i <= remaining; i++) {
        html += `<div class="cal-day other disabled">${i}</div>`;
    }
    html += `</div>`;
    html += `<div class="cal-actions">`;
    html += `<button class="cal-btn-cancel" onclick="cancelCalendar()">取消</button>`;
    html += `<button class="cal-btn-confirm" onclick="confirmCalendar()">确定</button>`;
    html += `</div></div>`;

    document.getElementById('calendarPicker').innerHTML = html;
}

function selectCalDay(dateStr) {
    calSelectedDate = dateStr;
    renderCalendar(calYear, calMonth);
}
function cancelCalendar() {
    calSelectedDate = null;
    calAllowPast = false;
    document.getElementById('f_date').value = '';
    showToast('已取消', 'times-circle', '#ff9f0a');
    // Switch back to daily
    document.querySelectorAll('#repeatMode .chip').forEach(c => c.classList.remove('active'));
    document.querySelector('#repeatMode .chip[data-val="daily"]').classList.add('active');
    document.getElementById('dateField').style.display = 'none';
}
function confirmCalendar() {
    if (!calSelectedDate) return;
    document.getElementById('f_date').value = calSelectedDate;
    document.getElementById('calendarPicker').style.display = 'none';
    document.getElementById('dateFieldLabel').textContent = '提醒日期';
    const mode = document.querySelector('#repeatMode .active').dataset.val;
    let labelText = calSelectedDate;
    if (mode === 'lunar') {
        const info = lunarInfoFromDate(calSelectedDate);
        if (info) labelText = `${calSelectedDate} · 农历${info.label}`;
    } else if (mode === 'yearly') {
        labelText = `${calSelectedDate} · 每年 ${Number(calSelectedDate.slice(5, 7))} 月 ${Number(calSelectedDate.slice(8, 10))} 日`;
    }
    document.getElementById('dateValStr').textContent = labelText;
    document.getElementById('selectedDateDisplay').style.display = 'flex';
}

function reopenCalendar() {
    document.getElementById('calendarPicker').style.display = 'block';
    document.getElementById('selectedDateDisplay').style.display = 'none';
    document.getElementById('dateFieldLabel').textContent = '选择日期';
    renderCalendar(calYear, calMonth);
}

// ─── Create / Update Task ───
async function createTask() {
    const editId = document.getElementById('f_editId').value;
    const title = document.getElementById('f_title').value.trim();
    const time = document.getElementById('f_time').value;
    const prio = document.getElementById('f_prio').value;

    if (!title) { document.getElementById('f_title').style.borderColor = 'var(--c-red)'; return; }

    const timePickerBox = document.getElementById('timePickerBox');
    if (timePickerBox.style.display === 'block') {
        const pendingTime = `${document.getElementById('tp_hour').value || '09'}:${document.getElementById('tp_min').value || '00'}`;
        if (pendingTime !== time) {
            showToast('请先点击时间选择器底部的“确定”按钮', 'triangle-exclamation', '#ff9f0a');
            return;
        }
    }

    // Build repeat string and resolve time
    const mode = document.querySelector('#repeatMode .active').dataset.val;
    let repeat = mode;
    let finalTime = time;
    if (mode === 'weekly') {
        const days = Array.from(document.querySelectorAll('#weekdayPicker .active')).map(c => c.dataset.val);
        repeat = days.length > 0 ? 'weekly:' + days.join(',') : 'daily';
    } else if (mode === 'monthly') {
        initMonthdayOptions();
        repeat = 'monthly:' + (document.getElementById('f_monthday').value || '1');
    } else if (mode === 'yearly' || mode === 'lunar') {
        const dateVal = document.getElementById('f_date').value;
        if (document.getElementById('calendarPicker').style.display === 'block' && calSelectedDate && calSelectedDate !== dateVal) {
            showToast('请先点击日期选择器底部的“确定”按钮', 'triangle-exclamation', '#ff9f0a');
            return;
        }
        if (!dateVal) {
            showToast('请选择日期', 'triangle-exclamation', '#ff9f0a');
            return;
        }
        if (mode === 'yearly') {
            // 每年：日期仅用于提供月/日
            finalTime = `${dateVal} ${time}`;
        } else {
            const lunarRepeat = lunarRepeatFromDate(dateVal);
            if (!lunarRepeat) {
                showToast('农历换算失败，请重新选择日期', 'times-circle', 'var(--c-red)');
                return;
            }
            repeat = lunarRepeat;
        }
    } else if (mode === 'once') {
        const dateVal = document.getElementById('f_date').value;
        if (document.getElementById('calendarPicker').style.display === 'block' && calSelectedDate && calSelectedDate !== dateVal) {
            showToast('请先点击日期选择器底部的“确定”按钮', 'triangle-exclamation', '#ff9f0a');
            return;
        }
        if (dateVal) {
            finalTime = `${dateVal} ${time}`;
        }
    } else if (mode === 'workday') {
        repeat = 'workday';
    }

    if (editId) {
        // Update existing
        const res = await fetch(`/api/reminders/${editId}`, {
            method: 'PUT',
            headers: apiHeaders(),
            body: JSON.stringify({ title, time: finalTime, priority: prio, repeat })
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showToast(data.error || '保存失败，请检查输入', 'times-circle', 'var(--c-red)');
            return;
        }
        window.newTaskId = editId;
    } else {
        // Create new
        const res = await fetch('/api/reminders', {
            method: 'POST',
            headers: apiHeaders(),
            body: JSON.stringify({ title, time: finalTime, priority: prio, repeat })
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showToast(data.error || '创建失败，请检查输入', 'times-circle', 'var(--c-red)');
            return;
        }
        const created = await res.json();
        window.newTaskId = created.id;
    }

    // Reset form
    document.getElementById('f_title').value = '';
    document.getElementById('f_title').style.borderColor = '';
    document.getElementById('f_editId').value = '';
    closeSheet();
    await sync();
    showToast('保存成功');
    // 需求6: 创建后跳转到首页
    goTo('home', document.querySelector('.dock-btn'));
}

async function saveWebhooks() {
    await fetch('/api/settings', {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
            webhooks: {
                wecom: document.getElementById('w_wecom').value,
                dingtalk: document.getElementById('w_ding').value,
                lark: document.getElementById('w_lark').value,
                sms_phone: document.getElementById('w_sms_phone').value,
                sms_api: document.getElementById('w_sms_api').value,
                voice_api: document.getElementById('w_voice_api').value
            }
        })
    });
    closeSheet(); sync();
    showToast('配置已保存');
}

function toggleDark() {
    const isDark = document.body.getAttribute('data-theme') !== 'light';
    fetch('/api/settings', { method: 'POST', headers: apiHeaders(), body: JSON.stringify({dark_mode: !isDark}) });
    document.body.setAttribute('data-theme', isDark ? 'light' : '');
    document.getElementById('darkToggle').className = 'toggle' + (!isDark ? ' on' : '');
    document.getElementById('darkDesc').textContent = !isDark ? '当前已开启' : '当前已关闭';
}

// ─── Navigation ───
function goTo(id, el) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.dock-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('v-' + id).classList.add('active');
    if (el) el.classList.add('active');
    document.querySelector('.screen').scrollTop = 0;
}

// ─── Sheets ───
let toastTmr;
function showToast(msg, icon='check-circle', color='#30d158') {
    let t = document.getElementById('globalToast');
    if(!t) {
        t = document.createElement('div'); t.id = 'globalToast'; t.className = 'toast-msg';
        document.body.appendChild(t);
    }
    t.innerHTML = `<i class="fas fa-${icon}" style="color:${color}"></i> ${msg}`;
    t.classList.add('show');
    clearTimeout(toastTmr);
    toastTmr = setTimeout(() => t.classList.remove('show'), 2000);
}

function openSheet(id) {
    // Reset add sheet to "create" mode when opening fresh
    if (id === 'add' && !document.getElementById('f_editId').value) {
        document.getElementById('addSheetTitle').textContent = '新建任务';
        document.querySelector('#sheet-add .btn-submit').textContent = '创建提醒';
        // Reset repeat chips
        document.querySelectorAll('#repeatMode .chip').forEach(c => c.classList.remove('active'));
        document.querySelector('#repeatMode .chip[data-val="daily"]').classList.add('active');
        document.getElementById('weekdayField').style.display = 'none';
        document.getElementById('monthdayField').style.display = 'none';
        document.getElementById('dateField').style.display = 'none';
        calAllowPast = false;
        document.querySelectorAll('#weekdayPicker .chip').forEach(c => c.classList.remove('active'));
        document.getElementById('timePickerBox').style.display = 'none';
    }
    // 修改密码面板：打开时清空上次输入与错误提示
    if (id === 'password') {
        document.getElementById('pwError').classList.remove('show');
        document.getElementById('pw_old').value = '';
        document.getElementById('pw_new').value = '';
        document.getElementById('pw_confirm').value = '';
    }
    // 昵称面板：打开时带出当前昵称
    if (id === 'nickname') {
        document.getElementById('nickError').classList.remove('show');
        document.getElementById('nick_input').value = (S && S.account && S.account.nickname) || '';
    }
    // 注销账号面板：清空上次输入
    if (id === 'deleteAccount') {
        document.getElementById('delError').classList.remove('show');
        document.getElementById('del_username').value = '';
        document.getElementById('del_password').value = '';
    }
    document.getElementById('overlay').style.display = 'block';
    document.getElementById('sheet-' + id).style.display = 'block';
}

function openAbout() {
    const currentVer = S.version || 'unknown';
    const versionHistory = [
        { version: 'v3.2.30', changes: ['移除半成品的微信小程序登录接口 /api/wxlogin', '文档修正：极空间兼容策略始终启用（ZSPACE_COMPAT 为占位项）', 'README 新增 v3.2.19 → v3.2.30 升级说明'] },
        { version: 'v3.2.29', changes: ['前端结构重构：样式与脚本拆分为 app.css / app.js（无构建工具）', 'config.json 新增 schema_version 结构版本字段，便于后续迁移'] },
        { version: 'v3.2.28', changes: ['新增：退出其他设备（当前设备保持登录）', '新增：注销账号（密码 + 用户名二次确认，数据一并删除）'] },
        { version: 'v3.2.27', changes: ['新增：Webhook 测试推送按钮（配置后立即验证）', '新增：历史记录一键「稍后提醒」（10 分钟后）', '新增：历史记录「标记已处理」开关', '新增：数据导出 / 导入备份（去重合并，不覆盖现有数据）', '修复：删除最后一条提醒不被落盘（重启复活）的问题'] },
        { version: 'v3.2.26', changes: ['新增「每月」提醒（指定日期或每月最后一天）', '新增「每年」提醒（生日、纪念日等）', '新增「农历每年」提醒（支持农历生日、闰月）', '修正通知文案中每周提醒被显示为「每天」的问题'] },
        { version: 'v3.2.25', changes: ['修复：删除全部通知记录后未落盘（重启会恢复）的问题', '修复：非法时间/不存在日期会被静默保存的问题，改为明确提示', '通知记录改为按保留期安全清理，兼容历史时间格式', '新增 LOG_RETENTION_DAYS 环境变量（默认 30 天）'] },
        { version: 'v3.2.24', changes: ['页脚仅保留账号保护状态，移除 API Key 相关提示'] },
        { version: 'v3.2.23', changes: ['优化设置页安全状态：账号保护已启用时不再显示「API 未认证」警告'] },
        { version: 'v3.2.22', changes: ['新增账号昵称：首页问候语显示', '设置页可修改昵称（留空恢复显示用户名），账号卡片同步显示'] },
        { version: 'v3.2.21', changes: ['修复开放模式下注册/登录页被 12 秒轮询强制关闭的问题', '登录页仅在拿到登录态时自动收起；增加「暂不注册，返回首页」入口'] },
        { version: 'v3.2.20', changes: ['历史统计条改为后端全量统计，不再受 100 条列表上限影响', '历史记录超出展示上限时提示「仅展示最近 N 条」'] },
        { version: 'v3.2.19', changes: ['多账号：自助注册 / 登录 / 登出 / 改密，账号数据完全隔离', '账号安全：PBKDF2 密码哈希、会话 token 摘要存储、登录失败锁定', 'UI 改版：全新设计令牌、卡片与 Dock 视觉升级、浅色模式优化', '数据页去除柱状图，改为按日期分组的历史记录 + 统计条', '开放模式遗留数据可在设置页一键导入账号'] },
        { version: 'v3.2.18', changes: ['节假日库启动年检 + 容器自动升级', 'chinese_calendar 升级至 >=1.11.0，支持 2026 年'] },
        { version: 'v3.2.17', changes: ['升级 chinese_calendar 至 >=1.11.0，支持 2026 年中国法定节假日'] },
        { version: 'v3.2.16', changes: ['一键清空已完成任务（含关联日志清理）', '修复切换完成状态验证失败', '按钮移至数据页通知记录右侧'] },
        { version: 'v3.2.15', changes: ['代码全面重构：模块化拆分', '修复工作日模式绕过中国法定节假日检查', '短信/电话 Webhook 通知支持', 'API Key 认证中间件', '服务端输入校验', '日志持久化删除', 'XSS 防护增强', '依赖版本锁定与升级'] },
        { version: 'v3.2.14', changes: ['仅一次日期选择范围扩展并限制至2100年', '补充时间和日期未确认时的创建提醒拦截'] },
        { version: 'v3.2.13', changes: ['补充关于页缺失的v3.2.11版本历史'] },
        { version: 'v3.2.12', changes: ['更新企业微信配置说明文案', '补充关于页版本历史展示并保留v3.2.4条目'] },
        { version: 'v3.2.11', changes: ['同步VERSION至v3.2.11', '修正版本历史顺序并补全v3.2.9'] },
        { version: 'v3.2.10', changes: ['修复模板应用时weekly类型repeat参数处理'] },
        { version: 'v3.2.9', changes: ['安全漏洞修复与多线程稳定性改进', '添加线程安全锁保护全局状态访问', '修复一次性任务未从调度器移除的问题'] },
        { version: 'v3.2.8', changes: ['优化底部菜单栏适配', '新增提醒模板功能'] },
        { version: 'v3.2.7', changes: ['同步VERSION至v3.2.7'] },
        { version: 'v3.2.6', changes: ['修复一次性任务字段不匹配(once vs none)', '同步VERSION至v3.2.6'] },
        { version: 'v3.2.5', changes: ['修复REMINDERS_FILE未定义导致删除失败'] },
        { version: 'v3.2.4', changes: ['同步VERSION至v3.2.4'] },
        { version: 'v3.2.3', changes: ['修复一次性任务触发后无法删除的问题', '删除重复的关于标签'] },
        { version: 'v3.2.2', changes: ['修复ZoneInfo时区转换错误', '一次性任务触发后自动从列表删除', '优化容器权限配置'] },
        { version: 'v3.2.1', changes: ['优化数据持久化，原子写入防止数据损坏', '增强错误处理和诊断日志', '优化首页UI，改进任务卡片布局'] },
        { version: 'v3.2.0', changes: ['交付专业排序循环逻辑', '全功能农历语义日历', '智能日期语义化标签（今天/明天/后天）'] }
    ];
    const historyHtml = versionHistory.map(item => `
            <div style="background: var(--c-surface2); border-radius: 12px; padding: 16px; margin-bottom: 12px;">
                <div style="font-weight: 700; color: var(--c-text1); margin-bottom: 8px;">${item.version}</div>
                <ul style="margin: 0; padding-left: 20px; font-size: 0.85rem; color: var(--c-text2); line-height: 1.8;">
                    ${item.changes.map(change => `<li>${change}</li>`).join('')}
                </ul>
            </div>
    `).join('');
    const aboutContent = `
        <div style="padding: 20px; max-height: 70vh; overflow-y: auto;">
            <h2 style="margin-bottom: 20px; text-align: center;">📋 版本历史</h2>
            <div style="background: var(--c-surface2); border-radius: 12px; padding: 16px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; color: var(--c-blue);">${currentVer}</span>
                    <span style="font-size: 0.75rem; color: var(--c-green);">当前版本</span>
                </div>
            </div>
            ${historyHtml}
            <p style="text-align: center; margin-top: 20px; font-size: 0.8rem; color: var(--c-text3);">
                Made with ♥ by <a href="https://github.com/mygaga2024" style="color: var(--c-blue);">mygaga2024</a>
            </p>
        </div>
    `;
    document.getElementById('overlay').style.display = 'block';
    document.getElementById('sheet-about').style.display = 'block';
    document.getElementById('sheet-about').querySelector('.sheet-content').innerHTML = aboutContent;
}
function closeSheet() {
    document.getElementById('overlay').style.display = 'none';
    document.querySelectorAll('.sheet-panel').forEach(s => s.style.display = 'none');
    document.getElementById('f_editId').value = '';
}

// ─── Bootstrap ───
(async function bootstrap() {
    authStatus = await fetchAuthStatus();
    if (authStatus && authStatus.login_required && !getToken()) {
        await openAuth(authStatus.accounts === 0 ? 'register' : 'login', authStatus, true);
        return;
    }
    await sync();
})();
setInterval(() => { if (S) sync(); }, 12000);
