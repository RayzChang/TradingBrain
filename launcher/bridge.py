"""
Launcher Bridge — 啟動器後端邏輯

提供 .env 管理、setup_testnet 執行、TradingBrain 啟停控制、日誌擷取。
"""

import asyncio
import os
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any

from loguru import logger

# 專案根目錄
ROOT_DIR = Path(__file__).resolve().parent.parent

# 確保專案根目錄在 sys.path
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class LogCapture:
    """攔截 loguru 日誌到環形佇列，供前端輪詢"""

    def __init__(self, max_lines: int = 500) -> None:
        self._buffer: deque[str] = deque(maxlen=max_lines)
        self._sink_id: int | None = None

    def start(self) -> None:
        self._sink_id = logger.add(self._sink, format="{time:HH:mm:ss} | {level:<7} | {message}", level="DEBUG")

    def stop(self) -> None:
        if self._sink_id is not None:
            logger.remove(self._sink_id)
            self._sink_id = None

    def _sink(self, message: Any) -> None:
        self._buffer.append(str(message).rstrip())

    def get_lines(self, last_n: int = 100) -> list[str]:
        lines = list(self._buffer)
        return lines[-last_n:] if len(lines) > last_n else lines

    def clear(self) -> None:
        self._buffer.clear()


class LauncherBridge:
    """
    啟動器核心邏輯。

    管理 .env 讀寫、testnet 設定、TradingBrain 生命週期。
    """

    def __init__(self) -> None:
        self._brain = None
        self._brain_thread: threading.Thread | None = None
        self._brain_loop: asyncio.AbstractEventLoop | None = None
        self._status = "stopped"  # stopped | starting | running | stopping | error
        self._error_msg = ""
        self._setup_status = "idle"  # idle | running | success | error
        self._setup_message = ""
        self.log_capture = LogCapture()
        self.log_capture.start()

    # ─── .env 管理 ────────────────────────────────────────

    def load_env(self) -> dict[str, str]:
        """讀取 .env 檔案，回傳 key-value dict"""
        env_path = ROOT_DIR / ".env"
        if not env_path.exists():
            # 複製 .env.example
            example = ROOT_DIR / ".env.example"
            if example.exists():
                env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                env_path.write_text("", encoding="utf-8")

        result = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
        return result

    def save_env(self, data: dict[str, str]) -> dict[str, Any]:
        """將 dict 寫入 .env 檔案，保留註解結構"""
        env_path = ROOT_DIR / ".env"

        # 讀取現有內容保留註解和空行
        existing_lines = []
        if env_path.exists():
            existing_lines = env_path.read_text(encoding="utf-8").splitlines()

        updated_keys = set()
        new_lines = []

        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in data:
                    new_lines.append(f"{key}={data[key]}")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # 附加新的 key（不在原檔案中的）
        for key, value in data.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}")

        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        # 強制重新載入環境變數到 os.environ
        for k, v in data.items():
            os.environ[k] = v

        logger.info(f"已儲存 .env ({len(data)} 個設定)")
        return {"success": True, "message": "設定已儲存"}

    # ─── Setup Testnet ────────────────────────────────────

    def run_setup(self) -> None:
        """背景執行 setup_testnet"""
        if self._setup_status == "running":
            return
        self._setup_status = "running"
        self._setup_message = "正在設定交易所..."
        threading.Thread(target=self._run_setup_thread, daemon=True).start()

    def _run_setup_thread(self) -> None:
        try:
            # 重新載入 settings 以套用最新 .env
            self._reload_settings()

            from setup_testnet import main as setup_main
            loop = asyncio.new_event_loop()
            loop.run_until_complete(setup_main())
            loop.close()
            self._setup_status = "success"
            self._setup_message = "交易所設定完成！"
            logger.info("Setup Testnet 執行成功")
        except Exception as e:
            self._setup_status = "error"
            self._setup_message = f"設定失敗: {str(e)}"
            logger.error(f"Setup Testnet 失敗: {e}")

    # ─── TradingBrain 控制 ────────────────────────────────

    def start_brain(self) -> dict[str, str]:
        """在子線程啟動 TradingBrain"""
        if self._status in ("running", "starting"):
            return {"status": self._status, "message": "交易大腦已在運行中"}

        self._status = "starting"
        self._error_msg = ""
        self._brain_thread = threading.Thread(target=self._brain_thread_fn, daemon=True)
        self._brain_thread.start()
        logger.info("正在啟動交易大腦...")
        return {"status": "starting", "message": "正在啟動..."}

    def _brain_thread_fn(self) -> None:
        """在獨立線程運行 TradingBrain 的 asyncio 事件循環"""
        try:
            # 重新載入 settings 以套用最新 .env
            self._reload_settings()

            from main import TradingBrain
            self._brain_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._brain_loop)

            self._brain = TradingBrain()
            self._status = "running"
            self._brain_loop.run_until_complete(self._brain.run())
        except Exception as e:
            self._status = "error"
            self._error_msg = str(e)
            logger.error(f"交易大腦錯誤: {e}")
        finally:
            if self._status != "error":
                self._status = "stopped"
            if self._brain_loop and not self._brain_loop.is_closed():
                self._brain_loop.close()
            self._brain_loop = None
            self._brain = None

    def stop_brain(self) -> dict[str, str]:
        """安全停止 TradingBrain"""
        if self._status not in ("running", "starting"):
            return {"status": self._status, "message": "交易大腦未在運行"}

        self._status = "stopping"
        logger.info("正在停止交易大腦...")

        if self._brain:
            self._brain.running = False

        return {"status": "stopping", "message": "正在安全關閉..."}

    # ─── 狀態查詢 ─────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """取得系統完整狀態"""
        return {
            "brain_status": self._status,
            "brain_error": self._error_msg,
            "setup_status": self._setup_status,
            "setup_message": self._setup_message,
            "dashboard_available": self._status == "running",
        }

    def get_logs(self, last_n: int = 80) -> list[str]:
        """取得最近 N 行日誌"""
        return self.log_capture.get_lines(last_n)

    # ─── 儀表板 ──────────────────────────────────────────

    def open_dashboard(self) -> dict[str, Any]:
        """在瀏覽器中開啟儀表板"""
        if self._status != "running":
            return {"success": False, "message": "請先啟動交易大腦，儀表板才能使用"}
        url = "http://localhost:8888"
        webbrowser.open(url)
        return {"success": True, "message": f"已開啟 {url}"}

    # ─── 內部工具 ─────────────────────────────────────────

    @staticmethod
    def _reload_settings() -> None:
        """強制重新載入 config.settings（讓新 .env 生效）"""
        from dotenv import load_dotenv
        load_dotenv(ROOT_DIR / ".env", override=True)
        # 重新載入 settings 模組
        if "config.settings" in sys.modules:
            import importlib
            importlib.reload(sys.modules["config.settings"])
