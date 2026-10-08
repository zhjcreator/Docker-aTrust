#!/usr/bin/env python3
"""
keep-alive-wayland: 保活守护进程 (Wayland 原生版)
负责定时执行网络探测和微小键鼠操作，防止系统判定为空闲。

基于 Docker-aTrust 项目 keep-alive.py 移植，适配 Pop!_OS 24.04 / COSMIC (Wayland)：
- 输入模拟: X11 -> xdotool; Wayland -> ydotool (uinput 内核级，与显示协议无关)
- 空闲检测: X11 -> XScreenSaver 扩展; Wayland -> logind IdleHint
- 抑制锁屏: X11 -> XSetScreenSaver/DPMS; Wayland -> 无标准 API，靠周期键鼠动作覆盖

配置通过 JSON 文件 ~/.keep-alive/config.json 管理（运行用户主目录）。
"""

import copy
import ctypes
import fcntl
import json
import os
import shutil
import subprocess
import socket
import sys
import tempfile
import time
import signal
import threading

HOME_DIR = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME_DIR, ".keep-alive")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "daemon.log")
RUNTIME_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "keep-alive")
PID_FILE = os.path.join(RUNTIME_DIR, "daemon.pid")
RUN_LOCK_FILE = os.path.join(RUNTIME_DIR, "daemon.lock")
START_LOCK_FILE = os.path.join(RUNTIME_DIR, "start.lock")

os.environ.setdefault("DISPLAY", ":0")


def autodetect_x_display():
    """探测可用的 XWayland display number, 优先级高于环境变量默认值。

    XWayland 的 display 编号在重启间不稳定(greeter 可能占用 :0/:1)，
    扫描 /tmp/.X11-unix/ 并用 xdotool 验证可连通性。
    """
    import glob
    candidates = []
    # 环境变量指定的优先
    env_display = os.environ.get("DISPLAY")
    if env_display and env_display.startswith(":"):
        candidates.append(env_display)
    for sock in sorted(glob.glob("/tmp/.X11-unix/X*")):
        num = sock.rsplit("X", 1)[-1]
        if f":{num}" not in candidates:
            candidates.append(f":{num}")
    for display in candidates:
        try:
            result = subprocess.run(
                ["xdotool", "getdisplaygeometry", "--display", display],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3
            )
            if result.returncode == 0:
                os.environ["DISPLAY"] = display
                return display
        except Exception:
            continue
    return os.environ.get("DISPLAY", ":0")


X_DISPLAY = None  # 延迟初始化(需要 xdotool 已安装)

# ---------------------------------------------------------------------------
# 后端检测: X11 / Wayland
# ---------------------------------------------------------------------------

def detect_session_type():
    """探测当前会话类型：wayland 或 x11。"""
    xdg_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if xdg_type:
        return xdg_type
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    # 从登录会话推断
    try:
        out = subprocess.run(
            ["loginctl", "show-session", self_session_id(), "-p", "Type", "--value"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
        ).stdout.decode().strip()
        if out:
            return out.lower()
    except Exception:
        pass
    return "x11"


def self_session_id():
    """获取当前进程所在登录会话 ID。"""
    try:
        uid = os.getuid()
        out = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend", "--no-pager"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
        ).stdout.decode().strip()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == str(uid):
                return parts[0]
        return ""
    except Exception:
        return ""


SESSION_TYPE = detect_session_type()


# ---------------------------------------------------------------------------
# 输入模拟后端
# ---------------------------------------------------------------------------

# ydotool 0.1.8 按键键名(与 xdotool 的 keysym 名称不同的常见映射)
X11_TO_YDO_KEY = {
    "Scroll_Lock": "ScrollLock",
    "Caps_Lock": "CapsLock",
    "Num_Lock": "NumLock",
    "Shift_L": "LEFTSHIFT",
    "Shift_R": "RIGHTSHIFT",
    "Ctrl_L": "LEFTCTRL",
    "Ctrl_R": "RIGHTCTRL",
    "Alt_L": "LEFTALT",
    "Alt_R": "RIGHTALT",
    "Super_L": "LEFTMETA",
    "Super_R": "RIGHTMETA",
}

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
        "interval": 60,
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


def ydotool_available():
    """检查 ydotool 与 uinput 是否可用。"""
    if os.path.exists("/dev/uinput") is False:
        return False
    return subprocess.run(
        ["which", "ydotool"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def mouse_move(dx, dy, return_to_origin, delay_ms=50):
    """移动鼠标。优先 XWayland XTEST(真相对移动)；失败退回 ydotool 绝对跳转。"""
    backend = "xdotool"
    try:
        if backend == "xdotool":
            if SESSION_TYPE != "x11":
                _ensure_x_display()
            subprocess.run(["xdotool", "mousemove_relative", "--", str(dx), str(dy)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                           check=True)
            if return_to_origin:
                time.sleep(max(0, delay_ms) / 1000.0)
                subprocess.run(["xdotool", "mousemove_relative", "--", str(-dx), str(-dy)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                               check=True)
        else:
            # ydotool 0.1.8 仅绝对坐标: 跳到 (dx,dy) 再回 (0,0)，抖动对近似原地微动
            move_cmd = lambda x, y: ["ydotool", "mousemove", "--delay", "0", "--", str(x), str(y)]
            subprocess.run(move_cmd(dx, dy),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                           check=True)
            if return_to_origin:
                time.sleep(max(0, delay_ms) / 1000.0)
                subprocess.run(move_cmd(0, 0),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                               check=True)
        log(f"MOUSE: move ({dx},{dy}) return={return_to_origin} backend={backend}")
        return True
    except Exception as e:
        log(f"MOUSE: ERROR ({e}) backend={backend}")
        return False


def key_toggle(key, repeats=2, delay_ms=30):
    """按下并释放指定按键；重复偶数次保证锁定键状态不变。

    Wayland 会话: 键盘注入走 ydotool(uinput)，绕过显示协议限制；
    X11 会话: 走 xdotool XTEST。
    """
    backend = "xdotool" if SESSION_TYPE == "x11" else "ydotool"
    try:
        delay = max(0, delay_ms) / 1000.0
        if backend == "xdotool":
            for _ in range(repeats):
                subprocess.run(["xdotool", "keydown", key],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                               check=True)
                time.sleep(delay)
                subprocess.run(["xdotool", "keyup", key],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                               check=True)
                time.sleep(delay)
        else:
            ydo_key = X11_TO_YDO_KEY.get(key, key)
            for _ in range(repeats):
                # ydotool 0.1.8: 默认 press+release 一对
                subprocess.run(
                    ["ydotool", "key", "--delay", "0", "--key-delay", str(max(1, delay_ms)), ydo_key],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                    check=True)
                time.sleep(delay)
        log(f"KEY: toggle {key} repeats={repeats} backend={backend}")
        return True
    except Exception as e:
        log(f"KEY: ERROR ({e}) backend={backend}")
        return False


def ydo_mouse_available():
    """ydotool 后备可用性(供诊断输出)。"""
    return os.path.exists("/dev/uinput") and shutil.which("ydotool") is not None


# ---------------------------------------------------------------------------
# 空闲检测
# ---------------------------------------------------------------------------

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
    """读取当前 X11 会话空闲秒数。"""
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


def get_logind_idle_seconds():
    """Wayland: 通过 logind 会话 IdleSinceHint 单调时钟差值计算空闲秒数。

    IdleSinceHint 为 0 表示会话从未空闲(hint 不可用)。
    """
    sid = self_session_id()
    if not sid:
        raise RuntimeError("cannot find login session")
    out = subprocess.run(
        ["loginctl", "show-session", sid,
         "-p", "State", "-p", "IdleHint", "-p", "IdleSinceHintMonotonic"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
    ).stdout.decode()
    props = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    if props.get("State") != "active":
        pass  # 后台会话仍可读取
    if props.get("IdleHint") != "yes":
        return 0.0
    since = int(props.get("IdleSinceHintMonotonic", "0"))
    if since <= 0:
        return 0.0
    now_mono = read_monotonic_now()
    return max(0.0, (now_mono - since) / 1e6)


def read_monotonic_now():
    """读取 CLOCK_MONOTONIC 当前值(微秒)。"""
    libc = ctypes.CDLL(None, use_errno=True)
    class timespec(ctypes.Structure):
        _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]
    ts = timespec()
    libc.clock_gettime(1, ctypes.byref(ts))  # CLOCK_MONOTONIC = 1
    return ts.tv_sec * 1_000_000 + ts.tv_nsec // 1000


def get_idle_seconds():
    """统一空闲检测入口：按会话类型分派。"""
    if SESSION_TYPE == "wayland":
        try:
            return get_logind_idle_seconds()
        except Exception:
            return None
    try:
        return get_x_idle_seconds()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 屏保抑制
# ---------------------------------------------------------------------------

def disable_x_blanking():
    """禁用 X11 屏保/黑屏/DPMS（仅 X11 会话有意义）。"""
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


def _ensure_x_display():
    """懒初始化 XWayland display 探测(仅 wayland 会话的鼠标后端需要)。"""
    global X_DISPLAY
    if X_DISPLAY is None:
        X_DISPLAY = autodetect_x_display()
        log(f"XWayland display detected: {X_DISPLAY}")
    return X_DISPLAY


# ---------------------------------------------------------------------------
# 配置管理
# ---------------------------------------------------------------------------

def load_config():
    """加载配置文件，不存在则创建默认配置。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
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


# ---------------------------------------------------------------------------
# 网络探针
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 守护进程
# ---------------------------------------------------------------------------

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
        log(f"Daemon started (session={SESSION_TYPE}, pid={os.getpid()})")
        write_pid_file(os.getpid())

        network_threads = [
            threading.Thread(target=self._network_loop, args=(probe_type,), daemon=True)
            for probe_type in ("icmp", "tcp", "http")
        ]
        activity_thread = threading.Thread(target=self._activity_loop, daemon=True)

        for thread in network_threads:
            thread.start()
        activity_thread.start()

        self._stop_event.wait()

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
        """周期性执行键鼠活动防止空闲；空闲读数仅用于日志。"""
        if SESSION_TYPE == "x11":
            try:
                disable_x_blanking()
            except Exception as e:
                log(f"ACTIVITY: WARNING (cannot disable X11 blanking: {e})")
        else:
            log("ACTIVITY: Wayland session, relying on periodic input")

        while self.running:
            cfg = load_config()
            activity_cfg = cfg.get("activity", {})
            if not activity_cfg.get("enabled", True):
                self._stop_event.wait(5)
                continue

            interval = activity_cfg.get("interval", 60)
            idle_seconds = get_idle_seconds()
            if idle_seconds is not None:
                log(f"ACTIVITY: idle={idle_seconds:.0f}s (periodic every {interval}s)")
            else:
                log("ACTIVITY: idle unavailable, firing input anyway")

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

            self._stop_event.wait(interval)


# ---------------------------------------------------------------------------
# PID 管理
# ---------------------------------------------------------------------------

def process_is_daemon(pid):
    """确认 PID 对应当前 Keep Alive 守护进程。"""
    try:
        os.kill(pid, 0)
        with open("/proc/{}/cmdline".format(pid), "rb") as f:
            args = [arg for arg in f.read().split(b"\0") if arg]
        return (b"--daemon" in args and
                any(arg.endswith(b"/keep-alive-wayland.py") or
                    arg.endswith(b"/keep-alive.py")
                    for arg in args))
    except (OSError, ProcessLookupError):
        return False


def read_daemon_pid():
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        if process_is_daemon(pid):
            return pid
    except (OSError, ValueError):
        pass
    return None


def remove_pid_files():
    try:
        os.remove(PID_FILE)
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
        daemon = KeepAliveDaemon()
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
        print("Usage: keep-alive-wayland.py [--daemon|--start|--stop|--status]")

