// ─── TradingBrain Launcher – Frontend Logic ───

const API = '';  // same origin
window.lastLauncherState = 'stopped';

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

    const modeEl = document.getElementById('infoMode');
    const testnetEl = document.getElementById('infoTestnet');
    const balanceEl = document.getElementById('infoBalance');
    const leverageEl = document.getElementById('infoLeverage');

    if (modeEl) modeEl.textContent = mode === 'live' ? '🔴 Live' : '📝 Paper';
    if (testnetEl) testnetEl.textContent = testnet;
    if (balanceEl) balanceEl.textContent = balance;
    if (leverageEl) leverageEl.textContent = leverage;

    if (data.DASHBOARD_USERNAME && data.DASHBOARD_PASSWORD) {
        window.brainAuth = btoa(data.DASHBOARD_USERNAME + ':' + data.DASHBOARD_PASSWORD);
    }
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
        await res.json();
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
    if (el) el.type = el.type === 'password' ? 'text' : 'password';
}

// ─── Setup ──────────────────────────────────────

async function runSetup() {
    const btn = document.getElementById('btnSetup');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> 設定中...';
    }
    try {
        await fetch(API + '/api/setup', { method: 'POST' });
    } catch (e) {
        console.error('Setup failed:', e);
    }
}

// ─── Brain Control ──────────────────────────────

async function startBrain() {
    const btn = document.getElementById('btnStart');
    const badge = document.getElementById('brainBadge');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> 啟動中...';
    }
    if (badge) {
        badge.textContent = '啟動中...';
        badge.className = 'brain-status-badge starting';
    }
    try {
        await fetch(API + '/api/brain/start', { method: 'POST' });
    } catch (e) {
        console.error('Start brain failed:', e);
    }
}

async function stopBrain() {
    const btn = document.getElementById('btnStop');
    const badge = document.getElementById('brainBadge');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> 停止中...';
    }
    if (badge) {
        badge.textContent = '停止中...';
        badge.className = 'brain-status-badge stopping';
    }
    try {
        await fetch(API + '/api/brain/stop', { method: 'POST' });
    } catch (e) {
        console.error('Stop brain failed:', e);
    }
}

// ─── Polling ───────────────────────────────────

async function pollStatus() {
    try {
        const res = await fetch(API + '/api/status');
        if (!res.ok) throw new Error('API Offline');
        const data = await res.json();

        const btnStart = document.getElementById('btnStart');
        const btnStop = document.getElementById('btnStop');
        const badge = document.getElementById('brainBadge');
        const errorEl = document.getElementById('brainError');
        const statusText = document.getElementById('statusText');
        const statusDot = document.getElementById('statusDot');

        if (data.brain_status === 'running') {
            if (btnStart) { btnStart.disabled = true; btnStart.innerHTML = '<span class="btn-icon">▶</span> 啟動'; }
            if (btnStop) { btnStop.disabled = false; btnStop.innerHTML = '<span class="btn-icon">⏹</span> 停止'; }
            if (badge) { badge.textContent = '運行中'; badge.className = 'brain-status-badge running'; }
            if (statusText) statusText.textContent = '運行中';
            if (statusDot) statusDot.className = 'status-indicator running';
            if (errorEl) errorEl.textContent = '';
        } else if (data.brain_status === 'starting') {
            if (btnStart) { btnStart.disabled = true; btnStart.innerHTML = '<span class="spinner"></span> 啟動中...'; }
            if (btnStop) { btnStop.disabled = true; }
            if (badge) { badge.textContent = '啟動中...'; badge.className = 'brain-status-badge starting'; }
            if (statusText) statusText.textContent = '啟動中...';
            if (statusDot) statusDot.className = 'status-indicator starting';
        } else if (data.brain_status === 'error') {
            if (btnStart) { btnStart.disabled = false; btnStart.innerHTML = '<span class="btn-icon">▶</span> 啟動'; }
            if (btnStop) { btnStop.disabled = true; }
            if (badge) { badge.textContent = '錯誤'; badge.className = 'brain-status-badge error'; }
            if (statusText) statusText.textContent = '錯誤';
            if (statusDot) statusDot.className = 'status-indicator error';
            if (errorEl) errorEl.textContent = data.brain_error || '未知錯誤';
        } else {
            if (btnStart) { btnStart.disabled = false; btnStart.innerHTML = '<span class="btn-icon">▶</span> 啟動'; }
            if (btnStop) { btnStop.disabled = true; }
            if (badge) { badge.textContent = '已停止'; badge.className = 'brain-status-badge'; }
            if (statusText) statusText.textContent = '已停止';
            if (statusDot) statusDot.className = 'status-indicator';
            if (errorEl) errorEl.textContent = '';
        }

        const btnSetup = document.getElementById('btnSetup');
        const setupBadge = document.getElementById('setupBadge');
        if (data.setup_status === 'running') {
            if (btnSetup) { btnSetup.disabled = true; btnSetup.innerHTML = '<span class="spinner"></span> 設定中...'; }
            if (setupBadge) { setupBadge.textContent = '設定中'; setupBadge.className = 'setup-status-badge running'; }
        } else if (data.setup_status === 'success') {
            if (btnSetup) { btnSetup.disabled = false; btnSetup.innerHTML = '<span class="btn-icon">🔧</span> 執行設定'; }
            if (setupBadge) { setupBadge.textContent = '設定成功'; setupBadge.className = 'setup-status-badge success'; }
        } else {
            if (btnSetup) { btnSetup.disabled = false; btnSetup.innerHTML = '<span class="btn-icon">🔧</span> 執行設定'; }
            if (setupBadge) { setupBadge.textContent = '待設定'; setupBadge.className = 'setup-status-badge'; }
        }
    } catch (e) {
        console.error('Status poll failed:', e);
    }
}

async function pollLogs() {
    try {
        const res = await fetch(API + '/api/logs?n=100');
        const logs = await res.json();
        const container = document.getElementById('logContainer');
        if (!container) return;

        const isAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;
        container.innerHTML = logs.map(line => {
            let cls = 'log-line';
            if (line.includes('| ERROR   |')) cls += ' level-error';
            if (line.includes('| WARNING |')) cls += ' level-warning';
            if (line.includes('| SUCCESS |')) cls += ' level-success';
            return `<div class="${cls}">${line}</div>`;
        }).join('');
        if (isAtBottom) container.scrollTop = container.scrollHeight;
    } catch (e) { }
}

// ─── Dashboard Data ─────────────────────────────

const BRAIN_API = `http://${window.location.hostname}:8888/api`;

async function fetchBrainAPI(endpoint) {
    if (!window.brainAuth) return null;
    try {
        const res = await fetch(BRAIN_API + endpoint, {
            headers: { 'Authorization': 'Basic ' + window.brainAuth }
        });
        if (!res.ok) return null;
        return await res.json();
    } catch (e) {
        return null;
    }
}

async function pollDashboardData() {
    const badge = document.getElementById('brainBadge');
    if (!badge || badge.textContent === '已停止') return;

    const statusData = await fetchBrainAPI('/system/status');
    if (statusData) {
        const balEl = document.getElementById('valExBalance');
        if (balEl) {
            const eb = statusData.exchange_balance;
            balEl.textContent = (eb !== undefined && eb !== null)
                ? `${Number(eb).toFixed(2)} U` : '同步中...';
        }

        const initEl = document.getElementById('valInitBalance');
        if (initEl) initEl.textContent = `${statusData.initial_balance || 0} U`;

        const pnl = statusData.daily_pnl || 0;
        const pnlEl = document.getElementById('valDailyPnl');
        if (pnlEl) {
            pnlEl.textContent = `${pnl > 0 ? '+' : ''}${Number(pnl).toFixed(2)} U`;
            pnlEl.className = `wallet-val ${pnl > 0 ? 'text-green' : (pnl < 0 ? 'text-red' : '')}`;
        }

        const posEl = document.getElementById('valOpenPositions');
        if (posEl) posEl.textContent = statusData.open_positions_count || 0;
    }

    const tradesData = await fetchBrainAPI('/trades/today');
    const tradesTbody = document.querySelector('#tradesTable tbody');
    if (tradesData && tradesTbody) {
        if (tradesData.length === 0) {
            tradesTbody.innerHTML = '<tr class="empty-row"><td colspan="4">今日尚無交易紀錄</td></tr>';
        } else {
            tradesData.sort((a, b) => {
                if (a.status === 'OPEN' && b.status !== 'OPEN') return -1;
                if (b.status === 'OPEN' && a.status !== 'OPEN') return 1;
                return new Date(b.opened_at || 0) - new Date(a.opened_at || 0);
            });
            tradesTbody.innerHTML = tradesData.slice(0, 15).map(t => {
                const side = t.side || t.direction || '—';
                const sideClass = side === 'LONG' ? 'text-long' : 'text-short';
                const pnl = t.pnl !== null && t.pnl !== undefined ? Number(t.pnl) : 0;
                let pnlStr = '—';
                let pnlClass = '';
                const st = (t.status || '').toUpperCase();
                if (st === 'CLOSED') {
                    pnlStr = `${pnl > 0 ? '+' : ''}${pnl.toFixed(2)} U`;
                    pnlClass = pnl > 0 ? 'text-green' : 'text-red';
                } else if (st === 'OPEN') { pnlStr = '(持有中)'; }

                return `<tr>
                    <td>${formatVNTime(t.opened_at)}</td>
                    <td style="font-weight:600;">${(t.symbol || '').replace('USDT', '')}</td>
                    <td><span class="${sideClass}">${side}</span></td>
                    <td class="${pnlClass}">${pnlStr}</td>
                </tr>`;
            }).join('');
        }
    }

    const signalsData = await fetchBrainAPI('/signals');
    const signalsTbody = document.querySelector('#signalsTable tbody');
    if (signalsData && signalsTbody) {
        if (signalsData.length === 0) {
            signalsTbody.innerHTML = '<tr class="empty-row"><td colspan="5">尚未產生信號</td></tr>';
        } else {
            signalsTbody.innerHTML = signalsData.slice(0, 15).map(s => {
                const sideClass = s.signal_type === 'LONG' ? 'text-long' : 'text-short';
                const str = s.strength !== null && s.strength !== undefined ? (s.strength * 100).toFixed(0) + '%' : '—';
                return `<tr>
                    <td>${formatVNTime(s.created_at)}</td>
                    <td style="font-weight:600;">${(s.symbol || '').replace('USDT', '')}</td>
                    <td>${s.timeframe}</td>
                    <td><span class="${sideClass}">${s.signal_type}</span></td>
                    <td>${str}</td>
                </tr>`;
            }).join('');
        }
    }
}

function formatVNTime(isoString) {
    if (!isoString) return '—';
    const d = new Date(isoString + 'Z');
    return d.toLocaleString('zh-TW', {
        timeZone: 'Asia/Ho_Chi_Minh',
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });
}
function formatVNTimeLocal(isoString) {
    if (!isoString) return '—';
    const d = new Date(isoString);
    return d.toLocaleString('zh-TW', {
        timeZone: 'Asia/Ho_Chi_Minh',
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });
}
function clearLogs() {
    const container = document.getElementById('logContainer');
    if (container) container.innerHTML = '<div class="log-empty">已清除。</div>';
}

// ─── Init ──────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadEnv();
    pollStatus();
    pollLogs();
    setInterval(pollStatus, 1500);
    setInterval(pollLogs, 1500);
    setInterval(pollDashboardData, 2500);
});
