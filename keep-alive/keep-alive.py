#!/usr/bin/env python3
"""
keep-alive: 保活守护进程
负责定时发送 ICMP ping 和执行微小键鼠操作，防止系统判定为空闲。
配置通过 JSON 文件 /root/.keep-alive/config.json 管理。
"""

import json
import os
import subprocess
import sys
import time
import signal
import threading

CONFIG_DIR = "/root/.keep-alive"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PID_FILE = os.path.join(CONFIG_DIR, "daemon.pid")
LOG_FILE = os.path.join(CONFIG_DIR, "daemon.log")

DEFAULT_CONFIG = {
    "enabled": False,
    "ping": {
        "targets": [],
        "interval": 30,
        "timeout": 3,
        "count": 1
    },
    "mouse": {
        "enabled": True,
        "interval": 60,
        "dx": 1,
        "dy": 1,
        "return_to_origin": True
    },
    "keyboard": {
        "enabled": True,
        "interval": 120,
        "keys": ["shift"]
    }
}


def load_config():
    """加载配置文件，不存在则创建默认配置。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        # 合并缺失的默认键
        merged = DEFAULT_CONFIG.copy()
        _deep_merge(merged, cfg)
        return merged
    except (json.JSONDecodeError, IOError):
        return DEFAULT_CONFIG.copy()


def save_config(cfg):
    """保存配置到 JSON 文件。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _deep_merge(base, override):
    """递归合并字典，override 覆盖 base。"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def log(msg):
    """写入日志。"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except IOError:
        pass
    print(line, end="")


def ping_target(target, timeout=3, count=1):
    """使用 ping 命令发送 ICMP 包。"""
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), target],
            capture_output=True,
            timeout=timeout + 5
        )
        success = result.returncode == 0
        status = "OK" if success else "FAIL"
        log(f"PING {target}: {status}")
        return success
    except subprocess.TimeoutExpired:
        log(f"PING {target}: TIMEOUT")
        return False
    except Exception as e:
        log(f"PING {target}: ERROR ({e})")
        return False


def mouse_move(dx, dy, return_to_origin):
    """使用 xdotool 执行微小鼠标移动。"""
    try:
        subprocess.run(["xdotool", "mousemove_relative", "--", str(dx), str(dy)],
                        capture_output=True, timeout=5)
        if return_to_origin:
            subprocess.run(["xdotool", "mousemove_relative", "--", str(-dx), str(-dy)],
                            capture_output=True, timeout=5)
        log(f"MOUSE: move ({dx},{dy}) return={return_to_origin}")
        return True
    except Exception as e:
        log(f"MOUSE: ERROR ({e})")
        return False


def key_press(key):
    """使用 xdotool 执行微小键盘操作。"""
    try:
        subprocess.run(["xdotool", "key", key],
                        capture_output=True, timeout=5)
        log(f"KEY: press {key}")
        return True
    except Exception as e:
        log(f"KEY: ERROR ({e})")
        return False


class KeepAliveDaemon:
    """保活守护进程主类。"""

    def __init__(self):
        self.running = False
        self.config = load_config()
        self._stop_event = threading.Event()

    def reload_config(self):
        """重新加载配置。"""
        self.config = load_config()
        log("Config reloaded")

    def stop(self):
        """停止守护进程。"""
        self.running = False
        self._stop_event.set()
        log("Daemon stopping...")

    def run(self):
        """主循环。"""
        self.running = True
        log("Daemon started")

        # 写入 PID 文件
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        mouse_thread = threading.Thread(target=self._mouse_loop, daemon=True)
        key_thread = threading.Thread(target=self._key_loop, daemon=True)

        ping_thread.start()
        mouse_thread.start()
        key_thread.start()

        # 主线程等待停止信号
        self._stop_event.wait()

        # 清理 PID 文件
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        log("Daemon stopped")

    def _ping_loop(self):
        """定时 ping 循环。"""
        while self.running:
            cfg = load_config()
            targets = cfg.get("ping", {}).get("targets", [])
            interval = cfg.get("ping", {}).get("interval", 30)
            timeout = cfg.get("ping", {}).get("timeout", 3)
            count = cfg.get("ping", {}).get("count", 1)

            if targets:
                for target in targets:
                    ping_target(target, timeout, count)

            self._stop_event.wait(interval if targets else 5)

    def _mouse_loop(self):
        """定时鼠标移动循环。"""
        while self.running:
            cfg = load_config()
            mouse_cfg = cfg.get("mouse", {})
            if not mouse_cfg.get("enabled", True):
                self._stop_event.wait(5)
                continue

            interval = mouse_cfg.get("interval", 60)
            dx = mouse_cfg.get("dx", 1)
            dy = mouse_cfg.get("dy", 1)
            return_to_origin = mouse_cfg.get("return_to_origin", True)

            mouse_move(dx, dy, return_to_origin)
            self._stop_event.wait(interval)

    def _key_loop(self):
        """定时键盘操作循环。"""
        while self.running:
            cfg = load_config()
            key_cfg = cfg.get("keyboard", {})
            if not key_cfg.get("enabled", True):
                self._stop_event.wait(5)
                continue

            interval = key_cfg.get("interval", 120)
            keys = key_cfg.get("keys", ["shift"])

            for key in keys:
                key_press(key)
            self._stop_event.wait(interval)


def is_daemon_running():
    """检查守护进程是否正在运行。"""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        # 检查进程是否存在
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, ProcessLookupError):
        # PID 文件过期，清理
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False


def start_daemon():
    """以子进程方式启动守护进程。"""
    if is_daemon_running():
        print("Daemon is already running.")
        return False

    # 使用 subprocess 启动，与父进程脱离
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--daemon"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print(f"Daemon started with PID {proc.pid}")
    return True


def stop_daemon():
    """停止守护进程。"""
    if not is_daemon_running():
        print("Daemon is not running.")
        return False

    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Daemon (PID {pid}) stopped.")
        return True
    except ProcessLookupError:
        print("Daemon process not found.")
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        # 作为守护进程运行
        daemon = KeepAliveDaemon()
        # 设置信号处理
        signal.signal(signal.SIGTERM, lambda s, f: daemon.stop())
        signal.signal(signal.SIGINT, lambda s, f: daemon.stop())
        signal.signal(signal.SIGUSR1, lambda s, f: daemon.reload_config())
        daemon.run()
    elif "--start" in sys.argv:
        start_daemon()
    elif "--stop" in sys.argv:
        stop_daemon()
    elif "--status" in sys.argv:
        if is_daemon_running():
            with open(PID_FILE, "r") as f:
                pid = f.read().strip()
            print(f"Daemon is running (PID {pid})")
        else:
            print("Daemon is not running.")
    else:
        print("Usage: keep-alive.py [--daemon|--start|--stop|--status]")
