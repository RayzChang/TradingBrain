const API = "";
const BRAIN_API = `http://${window.location.hostname}:8888/api`;

const ENV_FIELDS = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_TESTNET",
    "RELAX_VETO_ON_TESTNET",
    "TRADING_MODE",
    "TRADING_INITIAL_BALANCE",
    "MARGIN_TYPE",
    "DEFAULT_LEVERAGE",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "DASHBOARD_USERNAME",
    "DASHBOARD_PASSWORD",
];

window.lastLauncherState = "stopped";
window.brainAuth = "";

function $(id) {
    return document.getElementById(id);
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function switchTab(tabId) {
    document.querySelectorAll(".tab-content").forEach((el) => el.classList.remove("active"));
    document.querySelectorAll(".tab-btn").forEach((el) => el.classList.remove("active"));
    $(`tab-${tabId}`)?.classList.add("active");
    document.querySelector(`[data-tab="${tabId}"]`)?.classList.add("active");
}

function setBadge(element, text, stateClass) {
    if (!element) {
        return;
    }
    element.textContent = text;
    element.className = `${element.classList.contains("setup-status-badge") ? "setup-status-badge" : "brain-status-badge"} ${stateClass}`.trim();
}

function setStatusDot(state) {
    const dot = $("statusDot");
    if (!dot) {
        return;
    }
    dot.className = "status-indicator";
    if (state) {
        dot.classList.add(state);
    }
}

function formatMode(mode) {
    if (mode === "live") {
        return "Live";
    }
    if (mode === "paper") {
        return "Paper";
    }
    return mode || "未設定";
}

function formatTestnet(flag) {
    return flag === "true" ? "啟用 Demo / Testnet" : "正式環境";
}

function updateInfoPanel(data) {
    $("infoMode").textContent = formatMode(data.TRADING_MODE);
    $("infoTestnet").textContent = formatTestnet(data.BINANCE_TESTNET);
    $("infoBalance").textContent = data.TRADING_INITIAL_BALANCE ? `${data.TRADING_INITIAL_BALANCE} U` : "未設定";
    $("infoLeverage").textContent = data.DEFAULT_LEVERAGE ? `${data.DEFAULT_LEVERAGE}x` : "未設定";

    if (data.DASHBOARD_USERNAME && data.DASHBOARD_PASSWORD) {
        window.brainAuth = btoa(`${data.DASHBOARD_USERNAME}:${data.DASHBOARD_PASSWORD}`);
    } else {
        window.brainAuth = "";
    }
}

async function loadEnv() {
    try {
        const res = await fetch(`${API}/api/env`);
        const data = await res.json();
        ENV_FIELDS.forEach((field) => {
            const el = $(field);
            if (el && data[field] !== undefined) {
                el.value = data[field];
            }
        });
        updateInfoPanel(data);
    } catch (error) {
        console.error("Failed to load env:", error);
        $("saveFeedback").textContent = "讀取設定失敗，請確認 launcher server 已啟動。";
        $("saveFeedback").className = "save-feedback error";
    }
}

async function saveEnv(event) {
    event.preventDefault();

    const payload = {};
    ENV_FIELDS.forEach((field) => {
        const el = $(field);
        payload[field] = el ? el.value : "";
    });

    const feedback = $("saveFeedback");
    try {
        const res = await fetch(`${API}/api/env`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        await res.json();
        updateInfoPanel(payload);
        feedback.textContent = "設定已儲存。";
        feedback.className = "save-feedback success";
        setTimeout(() => {
            feedback.textContent = "";
        }, 3000);
    } catch (error) {
        console.error("Failed to save env:", error);
        feedback.textContent = `儲存失敗：${error.message}`;
        feedback.className = "save-feedback error";
    }
}

function togglePassword(fieldId) {
    const input = $(fieldId);
    if (!input) {
        return;
    }
    input.type = input.type === "password" ? "text" : "password";
}

async function runSetup() {
    const button = $("btnSetup");
    const message = $("setupMessage");
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner"></span> 執行中';
    }
    if (message) {
        message.textContent = "正在執行 setup_testnet.py...";
    }

    try {
        await fetch(`${API}/api/setup`, { method: "POST" });
    } catch (error) {
        console.error("Setup failed:", error);
        if (message) {
            message.textContent = `Setup 啟動失敗：${error.message}`;
        }
    }
}

async function startBrain() {
    const button = $("btnStart");
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner"></span> 啟動中';
    }
    setBadge($("brainBadge"), "啟動中", "badge-starting");
    $("statusText").textContent = "啟動中";
    setStatusDot("starting");

    try {
        await fetch(`${API}/api/brain/start`, { method: "POST" });
    } catch (error) {
        console.error("Start brain failed:", error);
        $("brainError").textContent = `啟動失敗：${error.message}`;
    }
}

async function stopBrain() {
    const button = $("btnStop");
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner"></span> 停止中';
    }
    setBadge($("brainBadge"), "停止中", "badge-stopping");
    $("statusText").textContent = "停止中";
    setStatusDot("stopping");

    try {
        await fetch(`${API}/api/brain/stop`, { method: "POST" });
    } catch (error) {
        console.error("Stop brain failed:", error);
        $("brainError").textContent = `停止失敗：${error.message}`;
    }
}

function renderBrainStatus(data) {
    const startButton = $("btnStart");
    const stopButton = $("btnStop");
    const errorEl = $("brainError");

    window.lastLauncherState = data.brain_status || "stopped";
    errorEl.textContent = data.brain_error || "";

    if (data.brain_status === "running") {
        if (startButton) {
            startButton.disabled = true;
            startButton.innerHTML = '<span class="btn-icon">▶</span> 已啟動';
        }
        if (stopButton) {
            stopButton.disabled = false;
            stopButton.innerHTML = '<span class="btn-icon">■</span> 停止';
        }
        setBadge($("brainBadge"), "運行中", "badge-running");
        $("statusText").textContent = "運行中";
        setStatusDot("running");
        return;
    }

    if (data.brain_status === "starting") {
        if (startButton) {
            startButton.disabled = true;
            startButton.innerHTML = '<span class="spinner"></span> 啟動中';
        }
        if (stopButton) {
            stopButton.disabled = true;
            stopButton.innerHTML = '<span class="btn-icon">■</span> 停止';
        }
        setBadge($("brainBadge"), "啟動中", "badge-starting");
        $("statusText").textContent = "啟動中";
        setStatusDot("starting");
        return;
    }

    if (data.brain_status === "stopping") {
        if (startButton) {
            startButton.disabled = true;
            startButton.innerHTML = '<span class="btn-icon">▶</span> 啟動';
        }
        if (stopButton) {
            stopButton.disabled = true;
            stopButton.innerHTML = '<span class="spinner"></span> 停止中';
        }
        setBadge($("brainBadge"), "停止中", "badge-stopping");
        $("statusText").textContent = "停止中";
        setStatusDot("stopping");
        return;
    }

    if (data.brain_status === "error") {
        if (startButton) {
            startButton.disabled = false;
            startButton.innerHTML = '<span class="btn-icon">▶</span> 重新啟動';
        }
        if (stopButton) {
            stopButton.disabled = true;
            stopButton.innerHTML = '<span class="btn-icon">■</span> 停止';
        }
        setBadge($("brainBadge"), "錯誤", "badge-error");
        $("statusText").textContent = "錯誤";
        setStatusDot("error");
        return;
    }

    if (startButton) {
        startButton.disabled = false;
        startButton.innerHTML = '<span class="btn-icon">▶</span> 啟動';
    }
    if (stopButton) {
        stopButton.disabled = true;
        stopButton.innerHTML = '<span class="btn-icon">■</span> 停止';
    }
    setBadge($("brainBadge"), "未啟動", "badge-stopped");
    $("statusText").textContent = "未啟動";
    setStatusDot("");
}

function renderSetupStatus(data) {
    const button = $("btnSetup");
    const badge = $("setupBadge");
    const message = $("setupMessage");

    if (data.setup_status === "running") {
        if (button) {
            button.disabled = true;
            button.innerHTML = '<span class="spinner"></span> 執行中';
        }
        setBadge(badge, "執行中", "badge-starting");
        message.textContent = data.setup_message || "正在準備測試環境...";
        return;
    }

    if (button) {
        button.disabled = false;
        button.innerHTML = '<span class="btn-icon">⚙</span> 執行 Setup';
    }

    if (data.setup_status === "success") {
        setBadge(badge, "已完成", "badge-success");
        message.textContent = data.setup_message || "Setup 已完成。";
        return;
    }

    if (data.setup_status === "error") {
        setBadge(badge, "失敗", "badge-error");
        message.textContent = data.setup_message || "Setup 失敗。";
        return;
    }

    setBadge(badge, "待命", "badge-idle");
    message.textContent = data.setup_message || "尚未執行 setup。";
}

async function pollStatus() {
    try {
        const res = await fetch(`${API}/api/status`);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        renderBrainStatus(data);
        renderSetupStatus(data);
    } catch (error) {
        console.error("Status poll failed:", error);
        $("brainError").textContent = `Launcher 連線失敗：${error.message}`;
        setBadge($("brainBadge"), "離線", "badge-error");
        $("statusText").textContent = "Launcher 離線";
        setStatusDot("error");
    }
}

async function pollLogs() {
    try {
        const res = await fetch(`${API}/api/logs?n=100`);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const logs = await res.json();
        const container = $("logContainer");
        if (!container) {
            return;
        }

        const isAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;
        container.innerHTML = logs.length
            ? logs.map((line) => {
                let cls = "log-line level-info";
                if (line.includes("| ERROR")) {
                    cls = "log-line level-error";
                } else if (line.includes("| WARNING")) {
                    cls = "log-line level-warning";
                } else if (line.includes("| SUCCESS")) {
                    cls = "log-line level-success";
                }
                return `<div class="${cls}">${escapeHtml(line)}</div>`;
            }).join("")
            : '<div class="log-empty">目前沒有可顯示的 launcher 日誌。</div>';

        if (isAtBottom) {
            container.scrollTop = container.scrollHeight;
        }
    } catch (_error) {
        // Ignore repeated log fetch errors to keep the UI quiet.
    }
}

async function fetchBrainAPI(endpoint) {
    if (!window.brainAuth) {
        return null;
    }

    try {
        const res = await fetch(`${BRAIN_API}${endpoint}`, {
            headers: { Authorization: `Basic ${window.brainAuth}` },
        });
        if (!res.ok) {
            return null;
        }
        return await res.json();
    } catch (_error) {
        return null;
    }
}

function formatVNTime(isoString, assumeUtc = false) {
    if (!isoString) {
        return "—";
    }

    const normalized = assumeUtc && !String(isoString).endsWith("Z") ? `${isoString}Z` : isoString;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) {
        return "—";
    }

    return date.toLocaleString("zh-TW", {
        timeZone: "Asia/Ho_Chi_Minh",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
    });
}

function renderTrades(trades) {
    const tbody = document.querySelector("#tradesTable tbody");
    if (!tbody) {
        return;
    }

    if (!Array.isArray(trades) || trades.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="4">今天還沒有交易紀錄。</td></tr>';
        return;
    }

    const ordered = [...trades].sort((a, b) => new Date(b.opened_at || 0) - new Date(a.opened_at || 0));
    tbody.innerHTML = ordered.slice(0, 15).map((trade) => {
        const side = trade.side || trade.direction || "—";
        const sideClass = side === "LONG" ? "text-long" : "text-short";
        const pnl = trade.pnl !== null && trade.pnl !== undefined ? Number(trade.pnl) : null;
        const status = (trade.status || "").toUpperCase();
        let pnlText = "—";
        let pnlClass = "";

        if (status === "OPEN") {
            pnlText = "進行中";
        } else if (pnl !== null) {
            pnlText = `${pnl > 0 ? "+" : ""}${pnl.toFixed(2)} U`;
            pnlClass = pnl > 0 ? "text-green" : pnl < 0 ? "text-red" : "";
        }

        return `
            <tr>
                <td>${escapeHtml(formatVNTime(trade.opened_at, true))}</td>
                <td style="font-weight:600;">${escapeHtml((trade.symbol || "").replace("USDT", ""))}</td>
                <td><span class="${sideClass}">${escapeHtml(side)}</span></td>
                <td class="${pnlClass}">${escapeHtml(pnlText)}</td>
            </tr>
        `;
    }).join("");
}

function renderSignals(signals) {
    const tbody = document.querySelector("#signalsTable tbody");
    if (!tbody) {
        return;
    }

    if (!Array.isArray(signals) || signals.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="5">目前沒有新的信號。</td></tr>';
        return;
    }

    tbody.innerHTML = signals.slice(0, 15).map((signal) => {
        const side = signal.signal_type || "—";
        const sideClass = side === "LONG" ? "text-long" : "text-short";
        const strength = signal.strength !== null && signal.strength !== undefined
            ? `${(Number(signal.strength) * 100).toFixed(0)}%`
            : "—";
        return `
            <tr>
                <td>${escapeHtml(formatVNTime(signal.created_at, true))}</td>
                <td style="font-weight:600;">${escapeHtml((signal.symbol || "").replace("USDT", ""))}</td>
                <td>${escapeHtml(signal.timeframe || "—")}</td>
                <td><span class="${sideClass}">${escapeHtml(side)}</span></td>
                <td>${escapeHtml(strength)}</td>
            </tr>
        `;
    }).join("");
}

async function pollDashboardData() {
    if (window.lastLauncherState !== "running") {
        renderTrades([]);
        renderSignals([]);
        return;
    }

    const statusData = await fetchBrainAPI("/system/status");
    if (statusData) {
        $("valExBalance").textContent = statusData.exchange_balance !== undefined && statusData.exchange_balance !== null
            ? `${Number(statusData.exchange_balance).toFixed(2)} U`
            : "讀取中";
        $("valInitBalance").textContent = `${Number(statusData.initial_balance || 0).toFixed(2)} U`;

        const pnl = Number(statusData.daily_pnl || 0);
        const pnlEl = $("valDailyPnl");
        pnlEl.textContent = `${pnl > 0 ? "+" : ""}${pnl.toFixed(2)} U`;
        pnlEl.className = "wallet-val";
        if (pnl > 0) {
            pnlEl.classList.add("text-green");
        } else if (pnl < 0) {
            pnlEl.classList.add("text-red");
        }

        $("valOpenPositions").textContent = String(statusData.open_positions_count || 0);
    }

    renderTrades(await fetchBrainAPI("/trades/today"));
    renderSignals(await fetchBrainAPI("/signals"));
}

function clearLogs() {
    const container = $("logContainer");
    if (container) {
        container.innerHTML = '<div class="log-empty">已清空畫面上的日誌內容，背景輪詢仍會持續載入新訊息。</div>';
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadEnv();
    pollStatus();
    pollLogs();
    pollDashboardData();

    setInterval(pollStatus, 1500);
    setInterval(pollLogs, 1500);
    setInterval(pollDashboardData, 2500);
});
