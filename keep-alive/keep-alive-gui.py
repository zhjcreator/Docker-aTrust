#!/usr/bin/env python3
"""
keep-alive-gui: 保活程序设置界面
GTK3 图形界面，可配置网络目标、间隔、键鼠操作参数，手动启动/停止守护进程。
"""

import copy
import json
import os
import signal
import subprocess
import sys
import tempfile
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

# 配置路径（与 daemon 共享）
CONFIG_DIR = "/root/.keep-alive"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PID_FILE = "/run/keep-alive/daemon.pid"
LEGACY_PID_FILE = os.path.join(CONFIG_DIR, "daemon.pid")

KEEP_ALIVE_SCRIPT = "/usr/local/bin/keep-alive.py"

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
    """加载配置。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = migrate_config(json.load(f))
        merged = copy.deepcopy(DEFAULT_CONFIG)
        _deep_merge(merged, cfg)
        return merged
    except (json.JSONDecodeError, IOError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg):
    """保存配置。"""
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
            value = target[6:] if lower_target.startswith("tcp://") else target
            host, separator, port = value.rpartition(":")
            if lower_target.startswith(("http://", "https://")):
                targets["http"].append(target)
            elif lower_target.startswith("tcp://") or (
                    value.count(":") == 1 and host and separator and port.isdigit()):
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


def read_daemon_pid():
    for path in (PID_FILE, LEGACY_PID_FILE):
        try:
            with open(path, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            with open("/proc/{}/cmdline".format(pid), "rb") as f:
                args = [arg for arg in f.read().split(b"\0") if arg]
            if (b"--daemon" in args and
                    any(arg.endswith(b"/keep-alive.py") for arg in args)):
                return pid
        except (OSError, ValueError, ProcessLookupError):
            pass
    return None


def is_daemon_running():
    """检查守护进程状态。"""
    return read_daemon_pid() is not None


class KeepAliveGUI(Gtk.Window):
    """保活程序设置主窗口。"""

    def __init__(self):
        super().__init__(title="Keep Alive 设置")
        self.set_default_size(680, 650)
        self.set_border_width(10)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.config = load_config()

        # 主垂直布局
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(main_box)

        # 标题
        title_label = Gtk.Label()
        title_label.set_markup("<b>Keep Alive 保活程序设置</b>")
        title_label.set_margin_bottom(10)
        main_box.pack_start(title_label, False, False, 0)

        # 状态栏 + 启停按钮
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        main_box.pack_start(status_box, False, False, 0)

        self.status_label = Gtk.Label(label="状态: 未运行")
        status_box.pack_start(self.status_label, True, True, 0)

        self.start_btn = Gtk.Button(label="▶ 启动")
        self.start_btn.connect("clicked", self.on_start_clicked)
        status_box.pack_start(self.start_btn, False, False, 0)

        self.stop_btn = Gtk.Button(label="■ 停止")
        self.stop_btn.connect("clicked", self.on_stop_clicked)
        self.stop_btn.set_sensitive(False)
        status_box.pack_start(self.stop_btn, False, False, 0)

        # 分隔线
        main_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # 三种网络保活独立配置，可同时启用并按各自周期运行。
        network_frame = Gtk.Frame(label="网络保活配置")
        network_notebook = Gtk.Notebook()
        network_frame.add(network_notebook)
        main_box.pack_start(network_frame, True, True, 0)
        self.network_widgets = {}

        probe_info = {
            "icmp": ("ICMP", "IP 或域名，每行一个，例如 10.0.0.1"),
            "tcp": ("TCP", "主机:端口，每行一个，例如 internal.example.com:22"),
            "http": ("HTTP", "HTTP(S) URL，每行一个，将执行真实 GET")
        }
        for probe_type in ("icmp", "tcp", "http"):
            tab_name, target_help = probe_info[probe_type]
            probe_cfg = self.config.get(probe_type, {})
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            page.set_border_width(6)

            enabled_check = Gtk.CheckButton(label=f"启用 {tab_name} 保活")
            enabled_check.set_active(probe_cfg.get("enabled", False))
            page.pack_start(enabled_check, False, False, 0)

            targets_label = Gtk.Label(label=target_help)
            targets_label.set_halign(Gtk.Align.START)
            page.pack_start(targets_label, False, False, 0)

            targets_scroll = Gtk.ScrolledWindow()
            targets_scroll.set_min_content_height(70)
            targets_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            targets_view = Gtk.TextView()
            targets_buffer = targets_view.get_buffer()
            targets_buffer.set_text("\n".join(probe_cfg.get("targets", [])))
            targets_scroll.add(targets_view)
            page.pack_start(targets_scroll, True, True, 0)

            params_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            page.pack_start(params_box, False, False, 0)
            params_box.pack_start(Gtk.Label(label="间隔 (秒):"), False, False, 0)
            interval_spin = Gtk.SpinButton()
            interval_spin.set_adjustment(Gtk.Adjustment(
                value=probe_cfg.get("interval", 30), lower=5, upper=3600,
                step_increment=5
            ))
            interval_spin.set_numeric(True)
            params_box.pack_start(interval_spin, False, False, 0)

            params_box.pack_start(Gtk.Label(label="超时 (秒):"), False, False, 0)
            timeout_spin = Gtk.SpinButton()
            timeout_spin.set_adjustment(Gtk.Adjustment(
                value=probe_cfg.get("timeout", 3), lower=1, upper=30,
                step_increment=1
            ))
            timeout_spin.set_numeric(True)
            params_box.pack_start(timeout_spin, False, False, 0)

            params_box.pack_start(Gtk.Label(label="每轮次数:"), False, False, 0)
            count_spin = Gtk.SpinButton()
            count_spin.set_adjustment(Gtk.Adjustment(
                value=probe_cfg.get("count", 1), lower=1, upper=10,
                step_increment=1
            ))
            count_spin.set_numeric(True)
            params_box.pack_start(count_spin, False, False, 0)

            widgets = {
                "enabled": enabled_check,
                "targets": targets_buffer,
                "interval": interval_spin,
                "timeout": timeout_spin,
                "count": count_spin
            }
            if probe_type == "http":
                tls_verify_check = Gtk.CheckButton(label="验证 HTTPS 证书")
                tls_verify_check.set_active(probe_cfg.get("verify_tls", True))
                page.pack_start(tls_verify_check, False, False, 0)
                widgets["verify_tls"] = tls_verify_check

            self.network_widgets[probe_type] = widgets
            network_notebook.append_page(page, Gtk.Label(label=tab_name))

        # 分隔线
        main_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # 达到空闲阈值后一次性执行键鼠活动，与已验证的 AHK 行为一致。
        activity_cfg = self.config.get("activity", {})
        activity_frame = Gtk.Frame(label="空闲活动保活")
        activity_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        activity_box.set_border_width(6)
        activity_frame.add(activity_box)
        main_box.pack_start(activity_frame, False, False, 0)

        self.activity_enabled_check = Gtk.CheckButton(label="启用空闲活动保活")
        self.activity_enabled_check.set_active(activity_cfg.get("enabled", True))
        activity_box.pack_start(self.activity_enabled_check, False, False, 0)

        activity_timing_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        activity_box.pack_start(activity_timing_box, False, False, 0)
        activity_timing_box.pack_start(Gtk.Label(label="空闲阈值 (分钟):"), False, False, 0)
        self.idle_threshold_spin = Gtk.SpinButton()
        self.idle_threshold_spin.set_adjustment(Gtk.Adjustment(
            value=activity_cfg.get("idle_threshold", 4500) / 60,
            lower=1, upper=1440, step_increment=5
        ))
        activity_timing_box.pack_start(self.idle_threshold_spin, False, False, 0)
        activity_timing_box.pack_start(Gtk.Label(label="提前 (秒):"), False, False, 0)
        self.trigger_margin_spin = Gtk.SpinButton()
        self.trigger_margin_spin.set_adjustment(Gtk.Adjustment(
            value=activity_cfg.get("trigger_margin", 60),
            lower=1, upper=600, step_increment=10
        ))
        activity_timing_box.pack_start(self.trigger_margin_spin, False, False, 0)
        activity_timing_box.pack_start(Gtk.Label(label="检查周期 (分钟):"), False, False, 0)
        self.activity_check_spin = Gtk.SpinButton()
        self.activity_check_spin.set_adjustment(Gtk.Adjustment(
            value=activity_cfg.get("check_interval", 1800) / 60,
            lower=1, upper=1440, step_increment=5
        ))
        activity_timing_box.pack_start(self.activity_check_spin, False, False, 0)

        activity_action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        activity_box.pack_start(activity_action_box, False, False, 0)
        self.activity_mouse_check = Gtk.CheckButton(label="鼠标往返")
        self.activity_mouse_check.set_active(activity_cfg.get("mouse_enabled", True))
        activity_action_box.pack_start(self.activity_mouse_check, False, False, 0)
        activity_action_box.pack_start(Gtk.Label(label="X:"), False, False, 0)
        self.activity_dx_spin = Gtk.SpinButton()
        self.activity_dx_spin.set_adjustment(Gtk.Adjustment(
            value=activity_cfg.get("dx", 1), lower=0, upper=50, step_increment=1
        ))
        activity_action_box.pack_start(self.activity_dx_spin, False, False, 0)
        activity_action_box.pack_start(Gtk.Label(label="Y:"), False, False, 0)
        self.activity_dy_spin = Gtk.SpinButton()
        self.activity_dy_spin.set_adjustment(Gtk.Adjustment(
            value=activity_cfg.get("dy", 0), lower=0, upper=50, step_increment=1
        ))
        activity_action_box.pack_start(self.activity_dy_spin, False, False, 0)
        self.activity_key_check = Gtk.CheckButton(label="Scroll Lock 双切换")
        self.activity_key_check.set_active(activity_cfg.get("keyboard_enabled", True))
        activity_action_box.pack_start(self.activity_key_check, False, False, 0)

        activity_hint = Gtk.Label()
        activity_hint.set_markup(
            "<small>在空闲阈值前按提前量触发；检查周期是最大间隔，接近阈值时会自动提前检查。"
            "鼠标移动并在 50 ms 后返回；"
            "Scroll Lock 按下/释放两轮，每步间隔 30 ms。</small>"
        )
        activity_hint.set_halign(Gtk.Align.START)
        activity_hint.set_line_wrap(True)
        activity_box.pack_start(activity_hint, False, False, 0)

        # 分隔线
        main_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # 底部按钮
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        main_box.pack_start(bottom_box, False, False, 0)

        save_btn = Gtk.Button(label="💾 保存配置")
        save_btn.connect("clicked", self.on_save_clicked)
        bottom_box.pack_start(save_btn, True, True, 0)

        # 刷新状态按钮
        refresh_btn = Gtk.Button(label="🔄 刷新状态")
        refresh_btn.connect("clicked", self.on_refresh_clicked)
        bottom_box.pack_start(refresh_btn, False, False, 0)

        # 定时刷新状态
        GLib.timeout_add_seconds(2, self.update_status)

        # 初始化状态
        self.update_status()

    def update_status(self):
        """更新守护进程状态显示。"""
        running = is_daemon_running()
        if running:
            try:
                pid = read_daemon_pid()
                self.status_label.set_markup(f"<b>状态: 运行中</b> (PID {pid})")
            except IOError:
                self.status_label.set_markup("<b>状态: 运行中</b>")
            self.start_btn.set_sensitive(False)
            self.stop_btn.set_sensitive(True)
        else:
            self.status_label.set_text("状态: 未运行")
            self.start_btn.set_sensitive(True)
            self.stop_btn.set_sensitive(False)
        return True  # 继续 GLib timeout

    def on_start_clicked(self, btn):
        """启动守护进程。"""
        # 先保存当前配置
        self._save_current_config(enabled=True)
        try:
            subprocess.run([sys.executable, KEEP_ALIVE_SCRIPT, "--start"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=10, check=True)
            self.update_status()
        except Exception as e:
            self.status_label.set_text(f"启动失败: {e}")

    def on_stop_clicked(self, btn):
        """停止守护进程。"""
        try:
            subprocess.run([sys.executable, KEEP_ALIVE_SCRIPT, "--stop"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=10, check=True)
            self.config = load_config()
            self.update_status()
        except Exception as e:
            self.status_label.set_text(f"停止失败: {e}")

    def on_refresh_clicked(self, btn):
        """手动刷新状态。"""
        self.update_status()

    def _save_current_config(self, enabled=None):
        """将当前界面配置写入配置文件。"""
        if enabled is None:
            enabled = self.config.get("enabled", False)

        cfg = {"enabled": enabled}
        for probe_type, widgets in self.network_widgets.items():
            targets_buffer = widgets["targets"]
            targets_text = targets_buffer.get_text(
                targets_buffer.get_start_iter(), targets_buffer.get_end_iter(), True
            )
            probe_cfg = {
                "enabled": widgets["enabled"].get_active(),
                "targets": [
                    target.strip() for target in targets_text.split("\n")
                    if target.strip()
                ],
                "interval": widgets["interval"].get_value_as_int(),
                "timeout": widgets["timeout"].get_value_as_int(),
                "count": widgets["count"].get_value_as_int()
            }
            if probe_type == "http":
                probe_cfg["verify_tls"] = widgets["verify_tls"].get_active()
            cfg[probe_type] = probe_cfg

        cfg.update({
            "activity": {
                "enabled": self.activity_enabled_check.get_active(),
                "idle_threshold": self.idle_threshold_spin.get_value_as_int() * 60,
                "trigger_margin": self.trigger_margin_spin.get_value_as_int(),
                "check_interval": self.activity_check_spin.get_value_as_int() * 60,
                "mouse_enabled": self.activity_mouse_check.get_active(),
                "dx": self.activity_dx_spin.get_value_as_int(),
                "dy": self.activity_dy_spin.get_value_as_int(),
                "return_to_origin": True,
                "mouse_delay_ms": 50,
                "keyboard_enabled": self.activity_key_check.get_active(),
                "key": "Scroll_Lock",
                "key_repeats": 2,
                "key_delay_ms": 30
            }
        })
        save_config(cfg)
        self.config = cfg

    def on_save_clicked(self, btn):
        """保存配置按钮。"""
        self._save_current_config()
        # 如果守护进程正在运行，通知其重新加载配置
        if is_daemon_running():
            try:
                pid = read_daemon_pid()
                if pid is not None:
                    os.kill(pid, signal.SIGUSR1)  # 通知重新加载
            except (OSError, ValueError):
                pass
        self.status_label.set_text("配置已保存")


if __name__ == "__main__":
    win = KeepAliveGUI()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
