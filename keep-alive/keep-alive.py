#!/usr/bin/env python3
"""
keep-alive: 保活守护进程
负责定时执行网络探测和微小键鼠操作，防止系统判定为空闲。
配置通过 JSON 文件 /root/.keep-alive/config.json 管理。
"""

import copy
import ctypes
import fcntl
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import signal
import threading

CONFIG_DIR = "/root/.keep-alive"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "daemon.log")
RUNTIME_DIR = "/run/keep-alive"
PID_FILE = os.path.join(RUNTIME_DIR, "daemon.pid")
LEGACY_PID_FILE = os.path.join(CONFIG_DIR, "daemon.pid")
RUN_LOCK_FILE = os.path.join(RUNTIME_DIR, "daemon.lock")
START_LOCK_FILE = os.path.join(RUNTIME_DIR, "start.lock")

os.environ.setdefault("DISPLAY", ":1")

DEFAULT_CONFIG = {
    "enabled": False,
    "icmp": {
        "enabled": False,
        "targets": [],
        "interval": 30,
        "timeout": 3,
        "count": 1
    },
    "tcp": {
        "enabled": False,
        "targets": [],
        "interval": 30,
        "timeout": 3,
        "count": 1
    },
    "http": {
        "enabled": False,
        "targets": [],
        "interval": 30,
        "timeout": 3,
        "count": 1,
        "verify_tls": True
    },
    "activity": {
        "enabled": True,
        "idle_threshold": 4500,
        "trigger_margin": 60,
        "check_interval": 1800,
        "mouse_enabled": True,
        "dx": 1,
        "dy": 0,
        "return_to_origin": True,
        "mouse_delay_ms": 50,
        "keyboard_enabled": True,
        "key": "Scroll_Lock",
        "key_repeats": 2,
        "key_delay_ms": 30
    }
}


def load_config():
    """加载配置文件，不存在则创建默认配置。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = migrate_config(json.load(f))
        # 合并缺失的默认键
        merged = copy.deepcopy(DEFAULT_CONFIG)
        _deep_merge(merged, cfg)
        return merged
    except (json.JSONDecodeError, IOError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg):
    """保存配置到 JSON 文件。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".config.", dir=CONFIG_DIR, text=True)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _deep_merge(base, override):
    """递归合并字典，override 覆盖 base。"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def migrate_config(cfg):
    """迁移旧版混合网络目标和独立键鼠配置。"""
    migrated = copy.deepcopy(cfg)
    if "ping" in migrated and not any(
            key in migrated for key in ("icmp", "tcp", "http")):
        legacy = migrated.pop("ping")
        common = {
            "interval": legacy.get("interval", 30),
            "timeout": legacy.get("timeout", 3),
            "count": legacy.get("count", 1)
        }
        targets = {"icmp": [], "tcp": [], "http": []}
        for target in legacy.get("targets", []):
            lower_target = target.lower()
            if lower_target.startswith(("http://", "https://")):
                targets["http"].append(target)
            elif lower_target.startswith("tcp://") or parse_tcp_target(target) is not None:
                targets["tcp"].append(target)
            else:
                targets["icmp"].append(target)

        for probe_type in ("icmp", "tcp", "http"):
            migrated[probe_type] = dict(common)
            migrated[probe_type]["enabled"] = bool(targets[probe_type])
            migrated[probe_type]["targets"] = targets[probe_type]
        migrated["http"]["verify_tls"] = legacy.get("verify_tls", True)

    if "activity" not in migrated and (
            "mouse" in migrated or "keyboard" in migrated):
        mouse_cfg = migrated.pop("mouse", {})
        key_cfg = migrated.pop("keyboard", {})
        migrated["activity"] = {
            "enabled": mouse_cfg.get("enabled", True) or key_cfg.get("enabled", True),
            "idle_threshold": 4500,
            "trigger_margin": 60,
            "check_interval": 1800,
            "mouse_enabled": mouse_cfg.get("enabled", True),
            "dx": mouse_cfg.get("dx", 1),
            "dy": 0,
            "return_to_origin": mouse_cfg.get("return_to_origin", True),
            "mouse_delay_ms": 50,
            "keyboard_enabled": key_cfg.get("enabled", True),
            "key": "Scroll_Lock",
            "key_repeats": 2,
            "key_delay_ms": 30
        }
    return migrated


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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=(timeout + 1) * count + 5
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


def parse_tcp_target(target):
    """解析 host:port 或 tcp://host:port，IPv6 地址需要使用方括号。"""
    value = target[6:] if target.lower().startswith("tcp://") else target
    if value.startswith("["):
        bracket = value.find("]")
        if bracket < 1 or value[bracket + 1:bracket + 2] != ":":
            return None
        host = value[1:bracket]
        port_text = value[bracket + 2:]
    else:
        if value.count(":") != 1:
            return None
        host, separator, port_text = value.rpartition(":")
        if not separator:
            return None

    if not host or not port_text.isdigit():
        return None
    port = int(port_text)
    if not 1 <= port <= 65535:
        return None
    return host, port


def tcp_target(target, timeout=3):
    """直连 TCP 服务；由系统路由决定是否进入 aTrust 隧道。"""
    endpoint = parse_tcp_target(target)
    if endpoint is None:
        log(f"TCP {target}: ERROR (expected host:port)")
        return False

    sock = None
    try:
        sock = socket.create_connection(endpoint, timeout=timeout)
        log(f"TCP {target}: OK")
        return True
    except Exception as e:
        log(f"TCP {target}: FAIL ({e})")
        return False
    finally:
        if sock is not None:
            sock.close()


def http_target(target, timeout=3, verify_tls=True):
    """使用真实 HTTP GET 产生业务流量，不使用代理。"""
    command = [
        "wget", "-q", "-O", "/dev/null", "--no-proxy",
        "--timeout", str(timeout), "--tries", "1",
        "--header", "Cache-Control: no-cache"
    ]
    if not verify_tls:
        command.append("--no-check-certificate")
    command.append(target)

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout + 5
        )
        success = result.returncode == 0
        status = "OK" if success else f"FAIL (wget exit {result.returncode})"
        log(f"HTTP {target}: {status}")
        return success
    except subprocess.TimeoutExpired:
        log(f"HTTP {target}: TIMEOUT")
        return False
    except Exception as e:
        log(f"HTTP {target}: ERROR ({e})")
        return False


class XScreenSaverInfo(ctypes.Structure):
    _fields_ = [
        ("window", ctypes.c_ulong),
        ("state", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("til_or_since", ctypes.c_ulong),
        ("idle", ctypes.c_ulong),
        ("event_mask", ctypes.c_ulong)
    ]


def get_x_idle_seconds():
    """读取当前 X11 会话距最后一次输入的空闲秒数。"""
    xlib = ctypes.CDLL("libX11.so.6")
    xss = ctypes.CDLL("libXss.so.1")
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    xlib.XDefaultRootWindow.restype = ctypes.c_ulong
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xlib.XFree.argtypes = [ctypes.c_void_p]
    xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
    xss.XScreenSaverQueryInfo.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XScreenSaverInfo)
    ]

    display = xlib.XOpenDisplay(None)
    if not display:
        raise RuntimeError(f"cannot open X display {os.environ.get('DISPLAY', '')}")
    info = None
    try:
        info = xss.XScreenSaverAllocInfo()
        if not info:
            raise RuntimeError("cannot allocate XScreenSaverInfo")
        root = xlib.XDefaultRootWindow(display)
        if not xss.XScreenSaverQueryInfo(display, root, info):
            raise RuntimeError("cannot query X11 idle time")
        return info.contents.idle / 1000.0
    finally:
        if info:
            xlib.XFree(ctypes.cast(info, ctypes.c_void_p))
        xlib.XCloseDisplay(display)


def disable_x_blanking():
    """禁用 X11 屏保、黑屏和 DPMS，活动保活负责重置空闲计时。"""
    xlib = ctypes.CDLL("libX11.so.6")
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XSetScreenSaver.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int
    ]
    xlib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]

    display = xlib.XOpenDisplay(None)
    if not display:
        raise RuntimeError(f"cannot open X display {os.environ.get('DISPLAY', '')}")
    try:
        xlib.XSetScreenSaver(display, 0, 0, 0, 0)

        xss = ctypes.CDLL("libXss.so.1")
        xss.XScreenSaverSuspend.argtypes = [ctypes.c_void_p, ctypes.c_int]
        xss.XScreenSaverSuspend(display, 1)

        try:
            xext = ctypes.CDLL("libXext.so.6")
            xext.DPMSDisable.argtypes = [ctypes.c_void_p]
            xext.DPMSDisable.restype = ctypes.c_int
            xext.DPMSDisable(display)
        except (OSError, AttributeError) as e:
            log(f"ACTIVITY: WARNING (cannot disable DPMS: {e})")

        xlib.XSync(display, 0)
        log("ACTIVITY: X11 blanking and screen saver disabled")
    finally:
        xlib.XCloseDisplay(display)


def mouse_move(dx, dy, return_to_origin, delay_ms=50):
    """使用 xdotool 执行微小鼠标移动。"""
    try:
        subprocess.run(["xdotool", "mousemove_relative", "--", str(dx), str(dy)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                       check=True)
        if return_to_origin:
            time.sleep(max(0, delay_ms) / 1000.0)
            subprocess.run(["xdotool", "mousemove_relative", "--", str(-dx), str(-dy)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                           check=True)
        log(f"MOUSE: move ({dx},{dy}) return={return_to_origin}")
        return True
    except Exception as e:
        log(f"MOUSE: ERROR ({e})")
        return False


def key_toggle(key, repeats=2, delay_ms=30):
    """按下并释放指定按键；锁定键重复偶数次后恢复原状态。"""
    try:
        delay = max(0, delay_ms) / 1000.0
        for _ in range(repeats):
            subprocess.run(["xdotool", "keydown", key],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                           check=True)
            time.sleep(delay)
            subprocess.run(["xdotool", "keyup", key],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                           check=True)
            time.sleep(delay)
        log(f"KEY: toggle {key} repeats={repeats}")
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
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        self._lock_file = open(RUN_LOCK_FILE, "w")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Another daemon instance is already running")
            return False

        self.running = True
        log("Daemon started")
        write_pid_file(os.getpid())

        network_threads = [
            threading.Thread(target=self._network_loop, args=(probe_type,), daemon=True)
            for probe_type in ("icmp", "tcp", "http")
        ]
        activity_thread = threading.Thread(target=self._activity_loop, daemon=True)

        for thread in network_threads:
            thread.start()
        activity_thread.start()

        # 主线程等待停止信号
        self._stop_event.wait()

        # 清理 PID 文件
        if read_daemon_pid() == os.getpid():
            remove_pid_files()
        fcntl.flock(self._lock_file, fcntl.LOCK_UN)
        self._lock_file.close()
        log("Daemon stopped")
        return True

    def _network_loop(self, probe_type):
        """运行一种独立的网络保活探针。"""
        while self.running:
            cfg = load_config()
            probe_cfg = cfg.get(probe_type, {})
            if not probe_cfg.get("enabled", False):
                self._stop_event.wait(5)
                continue

            targets = probe_cfg.get("targets", [])
            interval = probe_cfg.get("interval", 30)
            timeout = probe_cfg.get("timeout", 3)
            count = probe_cfg.get("count", 1)

            if targets:
                for target in targets:
                    if probe_type == "icmp":
                        ping_target(target, timeout, count)
                    elif probe_type == "tcp":
                        for _ in range(count):
                            tcp_target(target, timeout)
                    else:
                        verify_tls = probe_cfg.get("verify_tls", True)
                        for _ in range(count):
                            http_target(target, timeout, verify_tls)

            self._stop_event.wait(interval if targets else 5)

    def _activity_loop(self):
        """达到 X11 空闲阈值后执行与桌面 AHK 等价的键鼠活动。"""
        try:
            disable_x_blanking()
        except Exception as e:
            log(f"ACTIVITY: WARNING (cannot disable X11 blanking: {e})")

        while self.running:
            cfg = load_config()
            activity_cfg = cfg.get("activity", {})
            if not activity_cfg.get("enabled", True):
                self._stop_event.wait(5)
                continue

            try:
                idle_seconds = get_x_idle_seconds()
                idle_threshold = activity_cfg.get("idle_threshold", 4500)
                trigger_margin = activity_cfg.get("trigger_margin", 60)
                trigger_at = max(1, idle_threshold - trigger_margin)
                if idle_seconds >= trigger_at:
                    log(
                        f"ACTIVITY: idle={idle_seconds:.0f}s "
                        f"trigger={trigger_at}s threshold={idle_threshold}s"
                    )
                    if activity_cfg.get("mouse_enabled", True):
                        mouse_move(
                            activity_cfg.get("dx", 1),
                            activity_cfg.get("dy", 0),
                            activity_cfg.get("return_to_origin", True),
                            activity_cfg.get("mouse_delay_ms", 50)
                        )
                    if activity_cfg.get("keyboard_enabled", True):
                        key_toggle(
                            activity_cfg.get("key", "Scroll_Lock"),
                            activity_cfg.get("key_repeats", 2),
                            activity_cfg.get("key_delay_ms", 30)
                        )
                    wait_seconds = min(
                        activity_cfg.get("check_interval", 1800), trigger_at
                    )
                else:
                    wait_seconds = min(
                        activity_cfg.get("check_interval", 1800),
                        max(1, trigger_at - idle_seconds)
                    )
            except Exception as e:
                log(f"ACTIVITY: ERROR ({e})")
                wait_seconds = min(activity_cfg.get("check_interval", 1800), 60)

            self._stop_event.wait(wait_seconds)


def process_is_daemon(pid):
    """确认 PID 对应当前 Keep Alive 守护进程。"""
    try:
        os.kill(pid, 0)
        with open("/proc/{}/cmdline".format(pid), "rb") as f:
            args = [arg for arg in f.read().split(b"\0") if arg]
        return (b"--daemon" in args and
                any(arg.endswith(b"/keep-alive.py") for arg in args))
    except (OSError, ProcessLookupError):
        return False


def read_daemon_pid():
    for path in (PID_FILE, LEGACY_PID_FILE):
        try:
            with open(path, "r") as f:
                pid = int(f.read().strip())
            if process_is_daemon(pid):
                return pid
        except (OSError, ValueError):
            pass
    return None


def remove_pid_files():
    for path in (PID_FILE, LEGACY_PID_FILE):
        try:
            os.remove(path)
        except OSError:
            pass


def write_pid_file(pid):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".daemon.", dir=RUNTIME_DIR, text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(str(pid))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, PID_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def is_daemon_running():
    """检查守护进程是否正在运行。"""
    pid = read_daemon_pid()
    if pid is not None:
        return True
    remove_pid_files()
    return False


def start_daemon():
    """以子进程方式启动守护进程。"""
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(START_LOCK_FILE, "w") as start_lock:
        fcntl.flock(start_lock, fcntl.LOCK_EX)
        if is_daemon_running():
            print("Daemon is already running.")
            return True

        cfg = load_config()
        cfg["enabled"] = True
        save_config(cfg)

        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--daemon"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        for _ in range(100):
            if read_daemon_pid() == proc.pid:
                print(f"Daemon started with PID {proc.pid}")
                return True
            if proc.poll() is not None:
                print("Daemon failed to start.")
                return False
            time.sleep(0.05)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        remove_pid_files()
        print("Daemon did not become ready in time.")
        return False


def stop_daemon():
    """停止守护进程。"""
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(START_LOCK_FILE, "w") as lifecycle_lock:
        fcntl.flock(lifecycle_lock, fcntl.LOCK_EX)
        cfg = load_config()
        cfg["enabled"] = False
        save_config(cfg)
        pid = read_daemon_pid()
        if pid is None:
            print("Daemon is not running.")
            return True

        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(100):
                if not process_is_daemon(pid):
                    remove_pid_files()
                    print(f"Daemon (PID {pid}) stopped.")
                    return True
                time.sleep(0.05)
            print(f"Daemon (PID {pid}) did not stop in time.")
            return False
        except ProcessLookupError:
            print("Daemon process not found.")
            remove_pid_files()
            return False


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        # 作为守护进程运行
        daemon = KeepAliveDaemon()
        # 设置信号处理
        signal.signal(signal.SIGTERM, lambda s, f: daemon.stop())
        signal.signal(signal.SIGINT, lambda s, f: daemon.stop())
        signal.signal(signal.SIGUSR1, lambda s, f: daemon.reload_config())
        sys.exit(0 if daemon.run() else 1)
    elif "--start" in sys.argv:
        sys.exit(0 if start_daemon() else 1)
    elif "--stop" in sys.argv:
        sys.exit(0 if stop_daemon() else 1)
    elif "--status" in sys.argv:
        if is_daemon_running():
            pid = read_daemon_pid()
            print(f"Daemon is running (PID {pid})")
        else:
            print("Daemon is not running.")
    else:
        print("Usage: keep-alive.py [--daemon|--start|--stop|--status]")
