"""Launcher bridge used by the local control UI."""

import asyncio
import os
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any

from loguru import logger

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class LogCapture:
    """Collect in-memory log lines for the launcher UI."""

    def __init__(self, max_lines: int = 500) -> None:
        self._buffer: deque[str] = deque(maxlen=max_lines)
        self._sink_id: int | None = None

    def start(self) -> None:
        self._sink_id = logger.add(
            self._sink,
            format="{time:HH:mm:ss} | {level:<7} | {message}",
            level="DEBUG",
        )

    def stop(self) -> None:
        if self._sink_id is not None:
            logger.remove(self._sink_id)
            self._sink_id = None

    def _sink(self, message: Any) -> None:
        self._buffer.append(str(message).rstrip())

    def get_lines(self, last_n: int = 100) -> list[str]:
        lines = list(self._buffer)
        return lines[-last_n:] if len(lines) > last_n else lines


class LauncherBridge:
    """Manage env editing, setup, and TradingBrain lifecycle."""

    def __init__(self) -> None:
        self._brain = None
        self._brain_thread: threading.Thread | None = None
        self._brain_loop: asyncio.AbstractEventLoop | None = None
        self._status = "stopped"
        self._error_msg = ""
        self._setup_status = "idle"
        self._setup_message = ""
        self.log_capture = LogCapture()
        self.log_capture.start()

    def load_env(self) -> dict[str, str]:
        """Load the current .env file into a plain dict."""
        env_path = ROOT_DIR / ".env"
        if not env_path.exists():
            example = ROOT_DIR / ".env.example"
            if example.exists():
                env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                env_path.write_text("", encoding="utf-8")

        result: dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()

        result.setdefault("DASHBOARD_USERNAME", "admin")
        result.setdefault("DASHBOARD_PASSWORD", "")
        result.setdefault("TRADING_MODE", "paper")
        return result

    def save_env(self, data: dict[str, str]) -> dict[str, Any]:
        """Persist launcher form values back into .env."""
        env_path = ROOT_DIR / ".env"
        existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

        updated_keys = set()
        new_lines: list[str] = []
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

        for key, value in data.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}")

        env_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
        for key, value in data.items():
            os.environ[key] = value

        logger.info(f"Saved .env ({len(data)} keys)")
        return {"success": True, "message": "Configuration saved."}

    def run_setup(self) -> None:
        """Run setup_testnet.py in a background thread."""
        if self._setup_status == "running":
            return
        self._setup_status = "running"
        self._setup_message = "Running setup..."
        threading.Thread(target=self._run_setup_thread, daemon=True).start()

    def _run_setup_thread(self) -> None:
        try:
            self._reload_settings()
            from setup_testnet import main as setup_main

            loop = asyncio.new_event_loop()
            loop.run_until_complete(setup_main())
            loop.close()
            self._setup_status = "success"
            self._setup_message = "Setup completed successfully."
            logger.info("Setup Testnet completed")
        except Exception as exc:
            self._setup_status = "error"
            self._setup_message = f"Setup failed: {exc}"
            logger.error(f"Setup Testnet failed: {exc}")

    def start_brain(self) -> dict[str, str]:
        """Start TradingBrain in a background thread."""
        if self._status in ("running", "starting"):
            return {"status": self._status, "message": "TradingBrain is already running."}

        self._status = "starting"
        self._error_msg = ""
        self._brain_thread = threading.Thread(target=self._brain_thread_fn, daemon=True)
        self._brain_thread.start()
        logger.info("Starting TradingBrain...")
        return {"status": "starting", "message": "Starting TradingBrain..."}

    def _brain_thread_fn(self) -> None:
        try:
            self._reload_settings()
            from main import TradingBrain

            self._brain_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._brain_loop)
            self._brain = TradingBrain()
            self._status = "running"
            self._brain_loop.run_until_complete(self._brain.run())
        except Exception as exc:
            self._status = "error"
            self._error_msg = str(exc)
            logger.error(f"TradingBrain crashed: {exc}")
        finally:
            if self._status != "error":
                self._status = "stopped"
            if self._brain_loop and not self._brain_loop.is_closed():
                self._brain_loop.close()
            self._brain_loop = None
            self._brain = None

    def stop_brain(self) -> dict[str, str]:
        """Request TradingBrain shutdown."""
        if self._status not in ("running", "starting"):
            return {"status": self._status, "message": "TradingBrain is not running."}

        self._status = "stopping"
        logger.info("Stopping TradingBrain...")
        if self._brain:
            self._brain.running = False
        return {"status": "stopping", "message": "Stopping TradingBrain..."}

    def get_status(self) -> dict[str, Any]:
        """Return current launcher status."""
        return {
            "brain_status": self._status,
            "brain_error": self._error_msg,
            "setup_status": self._setup_status,
            "setup_message": self._setup_message,
            "dashboard_available": self._status == "running",
        }

    def get_logs(self, last_n: int = 80) -> list[str]:
        return self.log_capture.get_lines(last_n)

    @staticmethod
    def _reload_settings() -> None:
        """Reload .env and settings-dependent modules."""
        from dotenv import load_dotenv
        import importlib

        load_dotenv(ROOT_DIR / ".env", override=True)
        if "config.settings" in sys.modules:
            importlib.reload(sys.modules["config.settings"])
        for module_name in ("core.execution.execution_engine", "main"):
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
