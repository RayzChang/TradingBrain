// ─── TradingBrain Launcher – Frontend Logic ───

const API = '';  // same origin

// ─── Tab Navigation ─────────────────────────────

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + tabId).classList.add('active');
    document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');
}

// ─── Settings (.env) ────────────────────────────

async function loadEnv() {
    try {
        const res = await fetch(API + '/api/env');
        const data = await res.json();
        const fields = [
            'BINANCE_API_KEY', 'BINANCE_API_SECRET', 'BINANCE_TESTNET',
            'RELAX_VETO_ON_TESTNET', 'TRADING_MODE', 'TRADING_INITIAL_BALANCE',
            'MARGIN_TYPE', 'DEFAULT_LEVERAGE',
            'LINE_CHANNEL_ACCESS_TOKEN', 'LINE_USER_ID',
            'DASHBOARD_USERNAME', 'DASHBOARD_PASSWORD'
        ];
        fields.forEach(field => {
            const el = document.getElementById(field);
            if (el && data[field] !== undefined) {
                el.value = data[field];
            }
        });
        // Update info panel
        updateInfoPanel(data);
    } catch (e) {
        console.error('Failed to load env:', e);
    }
}

function updateInfoPanel(data) {
    const mode = data.TRADING_MODE || '—';
    const testnet = data.BINANCE_TESTNET === 'true' ? '✅ 是 (Demo)' : '❌ 否 (實盤)';
    const balance = data.TRADING_INITIAL_BALANCE ? data.TRADING_INITIAL_BALANCE + ' U' : '—';
    const leverage = data.DEFAULT_LEVERAGE ? data.DEFAULT_LEVERAGE + 'x' : '—';

    document.getElementById('infoMode').textContent = mode === 'live' ? '🔴 Live' : '📝 Paper';
    document.getElementById('infoTestnet').textContent = testnet;
    document.getElementById('infoBalance').textContent = balance;
    document.getElementById('infoLeverage').textContent = leverage;
}

async function saveEnv(event) {
    event.preventDefault();
    const form = document.getElementById('envForm');
    const formData = new FormData(form);
    const data = {};
    formData.forEach((value, key) => { data[key] = value; });

    const feedback = document.getElementById('saveFeedback');
    try {
        const res = await fetch(API + '/api/env', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await res.json();
        feedback.textContent = '✅ 設定已儲存！';
        feedback.className = 'save-feedback success';
        updateInfoPanel(data);
        setTimeout(() => { feedback.textContent = ''; }, 3000);
    } catch (e) {
        feedback.textContent = '❌ 儲存失敗: ' + e.message;
        feedback.className = 'save-feedback error';
    }
}

function togglePassword(fieldId) {
    const el = document.getElementById(fieldId);
    el.type = el.type === 'password' ? 'text' : 'password';
}

// ─── Setup Testnet ──────────────────────────────

async function runSetup() {
    const btn = document.getElementById('btnSetup');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> 設定中...';
    try {
        await fetch(API + '/api/setup', { method: 'POST' });
    } catch (e) {
        console.error('Setup failed:', e);
    }
}

// ─── Brain Control ──────────────────────────────

async function startBrain() {
    try {
        await fetch(API + '/api/brain/start', { method: 'POST' });
    } catch (e) {
        console.error('Start brain failed:', e);
    }
}

async function stopBrain() {
    try {
        await fetch(API + '/api/brain/stop', { method: 'POST' });
    } catch (e) {
        console.error('Stop brain failed:', e);
    }
}

// ─── Dashboard ──────────────────────────────────

async function openDashboard() {
    try {
        const res = await fetch(API + '/api/dashboard', { method: 'POST' });
        const data = await res.json();
        if (!data.success) {
            showToast(data.message, 'warning');
        }
    } catch (e) {
        showToast('無法連線到啟動器後端', 'error');
    }
}

function showToast(message, type = 'info') {
    // Remove existing toast
    const existing = document.getElementById('toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast toast-' + type;
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ─── Status Polling ─────────────────────────────

const STATUS_LABELS = {
    stopped: '已停止',
    starting: '啟動中...',
    running: '運行中',
    stopping: '停止中...',
    error: '錯誤'
};

const SETUP_LABELS = {
    idle: '待設定',
    running: '設定中...',
    success: '已完成',
    error: '失敗'
};

async function pollStatus() {
    try {
        const res = await fetch(API + '/api/status');
        const status = await res.json();

        // Brain status
        const brainStatus = status.brain_status;
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        const badge = document.getElementById('brainBadge');
        const btnStart = document.getElementById('btnStart');
        const btnStop = document.getElementById('btnStop');
        const errorEl = document.getElementById('brainError');

        dot.className = 'status-indicator ' + brainStatus;
        text.textContent = STATUS_LABELS[brainStatus] || brainStatus;

        badge.textContent = STATUS_LABELS[brainStatus] || brainStatus;
        badge.className = 'brain-status-badge badge-' + brainStatus;

        btnStart.disabled = brainStatus === 'running' || brainStatus === 'starting' || brainStatus === 'stopping';
        btnStop.disabled = brainStatus !== 'running' && brainStatus !== 'starting';

        errorEl.textContent = status.brain_error || '';

        // Dashboard button state
        const btnDashboard = document.querySelector('.btn-dashboard');
        const dashNote = document.querySelector('.card-note');
        if (btnDashboard) {
            btnDashboard.disabled = !status.dashboard_available;
            if (status.dashboard_available) {
                dashNote.textContent = '✅ 儀表板已就緒，點擊即可開啟';
                dashNote.style.color = 'var(--green)';
            } else {
                dashNote.textContent = '⚠️ 需要先啟動交易大腦才能使用儀表板';
                dashNote.style.color = '';
            }
        }

        // Setup status
        const setupStatus = status.setup_status;
        const setupBadge = document.getElementById('setupBadge');
        const setupMsg = document.getElementById('setupMessage');
        const btnSetup = document.getElementById('btnSetup');

        setupBadge.textContent = SETUP_LABELS[setupStatus] || setupStatus;
        setupBadge.className = 'setup-status-badge badge-' + (setupStatus === 'success' ? 'success' : setupStatus === 'error' ? 'error' : setupStatus === 'running' ? 'starting' : 'idle');

        setupMsg.textContent = status.setup_message || '';

        if (setupStatus !== 'running') {
            btnSetup.disabled = false;
            btnSetup.innerHTML = '<span class="btn-icon">🔧</span> 執行設定';
        }
    } catch (e) {
        // server not responding
    }
}

// ─── Log Polling ────────────────────────────────

let lastLogCount = 0;

async function pollLogs() {
    try {
        const res = await fetch(API + '/api/logs?n=200');
        const logs = await res.json();
        const container = document.getElementById('logContainer');

        if (logs.length === 0) {
            if (lastLogCount === 0) return;
            container.innerHTML = '<div class="log-empty">啟動交易大腦後，日誌會顯示在這裡</div>';
            lastLogCount = 0;
            return;
        }

        if (logs.length !== lastLogCount) {
            const autoScroll = container.scrollTop + container.clientHeight >= container.scrollHeight - 50;
            container.innerHTML = logs.map(line => {
                let cls = 'log-line level-info';
                if (line.includes('WARNING') || line.includes('⚠')) cls = 'log-line level-warning';
                else if (line.includes('ERROR') || line.includes('❌')) cls = 'log-line level-error';
                else if (line.includes('完成') || line.includes('✅') || line.includes('PASS') || line.includes('成功')) cls = 'log-line level-success';
                return `<div class="${cls}">${escapeHtml(line)}</div>`;
            }).join('');

            if (autoScroll) {
                container.scrollTop = container.scrollHeight;
            }
            lastLogCount = logs.length;
        }
    } catch (e) {
        // ignore
    }
}

function clearLogs() {
    document.getElementById('logContainer').innerHTML = '<div class="log-empty">日誌已清除</div>';
    lastLogCount = 0;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ─── Initialize ─────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadEnv();
    pollStatus();
    pollLogs();

    // Poll every 1.5 seconds
    setInterval(pollStatus, 1500);
    setInterval(pollLogs, 1500);
});
