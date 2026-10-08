#!/usr/bin/env python3
"""
keep-alive-gui: 保活程序设置界面 (Wayland 原生机版)
GTK3 图形界面，可配置网络目标、间隔、键鼠操作参数，启停 systemd 用户服务。

适配 Pop!_OS 24.04 / COSMIC (Wayland):
- 配置路径改为 ~/.keep-alive (运行用户主目录)
- 启停从直接调用守护脚本改为 systemctl --user
- Wayland 下 GUI 通过 XDG_SESSION_TYPE 自动判断
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

# 配置路径（与 daemon 共享，随运行用户主目录）
HOME_DIR = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME_DIR, ".keep-alive")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
RUNTIME_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "keep-alive")
PID_FILE = os.path.join(RUNTIME_DIR, "daemon.pid")

KEEP_ALIVE_SCRIPT = "/usr/local/bin/keep-alive-wayland.py"
SYSTEMD_UNIT = "keep-alive.service"

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


def load_config():
    """加载配置。"""
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


def systemctl_user(*args):
    """执行 systemctl --user 命令并返回 (成功, 输出)。"""
    result = subprocess.run(
        ["systemctl", "--user", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
    )
    return result.returncode == 0, result.stdout.decode().strip()


def read_daemon_pid():
    """读取守护进程 PID(systemd 服务)。"""
    ok, out = systemctl_user("show", SYSTEMD_UNIT, "-p", "MainPID", "--value")
    if ok and out.strip().isdigit() and int(out.strip()) > 0:
        return int(out.strip())
    return None


def is_daemon_running():
    """检查守护进程状态。"""
    ok, out = systemctl_user("is-active", SYSTEMD_UNIT)
    return ok and out == "active"


class KeepAliveGUI(Gtk.Window):
    """保活程序设置主窗口。"""

    def __init__(self):
        super().__init__(title="Keep Alive 设置")
        self.set_default_size(680, 700)
        self.set_border_width(10)

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

        # 开机自启开关
        boot_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        main_box.pack_start(boot_box, False, False, 0)
        self.autostart_check = Gtk.CheckButton(label="登录桌面后自动启动")
        self.autostart_check.set_active(self._unit_is_enabled())
        self.autostart_check.connect("toggled", self.on_autostart_toggled)
        boot_box.pack_start(self.autostart_check, False, False, 0)

        # 分隔线
        main_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # 网络保活配置 (三种探针)
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

        # 键鼠活动保活配置
        activity_cfg = self.config.get("activity", {})
        activity_frame = Gtk.Frame(label="键鼠活动保活")
        activity_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        activity_box.set_border_width(6)
        activity_frame.add(activity_box)
        main_box.pack_start(activity_frame, False, False, 0)

        self.activity_enabled_check = Gtk.CheckButton(label="启用键鼠活动保活")
        self.activity_enabled_check.set_active(activity_cfg.get("enabled", True))
        activity_box.pack_start(self.activity_enabled_check, False, False, 0)

        activity_timing_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        activity_box.pack_start(activity_timing_box, False, False, 0)
        activity_timing_box.pack_start(Gtk.Label(label="动作周期 (秒):"), False, False, 0)
        self.interval_spin = Gtk.SpinButton()
        self.interval_spin.set_adjustment(Gtk.Adjustment(
            value=activity_cfg.get("interval", 60), lower=10, upper=3600,
            step_increment=10
        ))
        activity_timing_box.pack_start(self.interval_spin, False, False, 0)

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
            "<small>每周期执行: 鼠标移动并 50ms 后返回(XWayland XTEST) + "
            "Scroll Lock 按下/释放两轮(ydotool 内核注入)。</small>"
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

        refresh_btn = Gtk.Button(label="🔄 刷新状态")
        refresh_btn.connect("clicked", self.on_refresh_clicked)
        bottom_box.pack_start(refresh_btn, False, False, 0)

        # 定时刷新状态
        GLib.timeout_add_seconds(2, self.update_status)
        self.update_status()

    def _unit_is_enabled(self):
        ok, out = systemctl_user("is-enabled", SYSTEMD_UNIT)
        return ok

    def on_autostart_toggled(self, check):
        if check.get_active():
            systemctl_user("enable", SYSTEMD_UNIT)
            self.status_label.set_text("已设置登录桌面后自启动")
        else:
            systemctl_user("disable", SYSTEMD_UNIT)
            self.status_label.set_text("已取消自启动")

    def update_status(self):
        """更新守护进程状态显示。"""
        running = is_daemon_running()
        if running:
            pid = read_daemon_pid()
            if pid:
                self.status_label.set_markup(f"<b>状态: 运行中</b> (PID {pid})")
            else:
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
        self._save_current_config(enabled=True)
        ok, out = systemctl_user("start", SYSTEMD_UNIT)
        if ok:
            self.update_status()
        else:
            self.status_label.set_text(f"启动失败: {out}")

    def on_stop_clicked(self, btn):
        """停止守护进程。"""
        ok, out = systemctl_user("stop", SYSTEMD_UNIT)
        if ok:
            self.config = load_config()
            self.update_status()
        else:
            self.status_label.set_text(f"停止失败: {out}")

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
                "interval": self.interval_spin.get_value_as_int(),
                "idle_threshold": self.config.get("activity", {}).get("idle_threshold", 4500),
                "trigger_margin": self.config.get("activity", {}).get("trigger_margin", 60),
                "check_interval": self.config.get("activity", {}).get("check_interval", 1800),
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
            pid = read_daemon_pid()
            if pid:
                try:
                    os.kill(pid, signal.SIGUSR1)  # 通知重新加载
                except (OSError, ValueError):
                    pass
        self.status_label.set_text("配置已保存")


if __name__ == "__main__":
    win = KeepAliveGUI()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

