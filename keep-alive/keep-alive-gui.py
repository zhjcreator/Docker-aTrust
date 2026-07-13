#!/usr/bin/env python3
"""
keep-alive-gui: 保活程序设置界面
GTK3 图形界面，可配置 ping 目标、间隔、键鼠操作参数，手动启动/停止守护进程。
"""

import json
import os
import subprocess
import sys
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

# 配置路径（与 daemon 共享）
CONFIG_DIR = "/root/.keep-alive"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PID_FILE = os.path.join(CONFIG_DIR, "daemon.pid")

KEEP_ALIVE_SCRIPT = "/usr/local/bin/keep-alive.py"

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
    """加载配置。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        _deep_merge(merged, cfg)
        return merged
    except (json.JSONDecodeError, IOError):
        return DEFAULT_CONFIG.copy()


def save_config(cfg):
    """保存配置。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _deep_merge(base, override):
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def is_daemon_running():
    """检查守护进程状态。"""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, ProcessLookupError):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False


class KeepAliveGUI(Gtk.Window):
    """保活程序设置主窗口。"""

    def __init__(self):
        super().__init__(title="Keep Alive 设置")
        self.set_default_size(520, 600)
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

        # Ping 配置区域
        ping_frame = Gtk.Frame(label="ICMP Ping 配置")
        ping_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ping_frame.add(ping_box)
        main_box.pack_start(ping_frame, True, True, 0)

        # 目标列表
        targets_label = Gtk.Label(label="Ping 目标地址 (每行一个 IP 或域名):")
        targets_label.set_halign(Gtk.Align.START)
        ping_box.pack_start(targets_label, False, False, 0)

        targets_scroll = Gtk.ScrolledWindow()
        targets_scroll.set_min_content_height(80)
        targets_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.targets_view = Gtk.TextView()
        self.targets_buffer = self.targets_view.get_buffer()
        targets_text = "\n".join(self.config.get("ping", {}).get("targets", []))
        self.targets_buffer.set_text(targets_text)
        targets_scroll.add(self.targets_view)
        ping_box.pack_start(targets_scroll, True, True, 0)

        # Ping 间隔
        interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        ping_box.pack_start(interval_box, False, False, 0)

        interval_label = Gtk.Label(label="Ping 间隔 (秒):")
        interval_box.pack_start(interval_label, False, False, 0)

        adj = Gtk.Adjustment(value=self.config.get("ping", {}).get("interval", 30),
                             lower=5, upper=3600, step_increment=5)
        self.ping_interval_spin = Gtk.SpinButton()
        self.ping_interval_spin.set_adjustment(adj)
        self.ping_interval_spin.set_numeric(True)
        interval_box.pack_start(self.ping_interval_spin, False, False, 0)

        # Ping 超时
        timeout_label = Gtk.Label(label="超时 (秒):")
        interval_box.pack_start(timeout_label, False, False, 0)

        adj2 = Gtk.Adjustment(value=self.config.get("ping", {}).get("timeout", 3),
                              lower=1, upper=30, step_increment=1)
        self.ping_timeout_spin = Gtk.SpinButton()
        self.ping_timeout_spin.set_adjustment(adj2)
        self.ping_timeout_spin.set_numeric(True)
        interval_box.pack_start(self.ping_timeout_spin, False, False, 0)

        # Ping 次数
        count_label = Gtk.Label(label="每次包数:")
        interval_box.pack_start(count_label, False, False, 0)

        adj3 = Gtk.Adjustment(value=self.config.get("ping", {}).get("count", 1),
                              lower=1, upper=10, step_increment=1)
        self.ping_count_spin = Gtk.SpinButton()
        self.ping_count_spin.set_adjustment(adj3)
        self.ping_count_spin.set_numeric(True)
        interval_box.pack_start(self.ping_count_spin, False, False, 0)

        # 分隔线
        main_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # 鼠标操作配置
        mouse_frame = Gtk.Frame(label="鼠标微操作配置")
        mouse_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        mouse_frame.add(mouse_box)
        main_box.pack_start(mouse_frame, False, False, 0)

        self.mouse_enabled_check = Gtk.CheckButton(label="启用鼠标微移动")
        self.mouse_enabled_check.set_active(self.config.get("mouse", {}).get("enabled", True))
        mouse_box.pack_start(self.mouse_enabled_check, False, False, 0)

        mouse_params_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mouse_box.pack_start(mouse_params_box, False, False, 0)

        dx_label = Gtk.Label(label="X 像素:")
        mouse_params_box.pack_start(dx_label, False, False, 0)
        adj_dx = Gtk.Adjustment(value=self.config.get("mouse", {}).get("dx", 1),
                                lower=0, upper=50, step_increment=1)
        self.mouse_dx_spin = Gtk.SpinButton()
        self.mouse_dx_spin.set_adjustment(adj_dx)
        mouse_params_box.pack_start(self.mouse_dx_spin, False, False, 0)

        dy_label = Gtk.Label(label="Y 像素:")
        mouse_params_box.pack_start(dy_label, False, False, 0)
        adj_dy = Gtk.Adjustment(value=self.config.get("mouse", {}).get("dy", 1),
                                lower=0, upper=50, step_increment=1)
        self.mouse_dy_spin = Gtk.SpinButton()
        self.mouse_dy_spin.set_adjustment(adj_dy)
        mouse_params_box.pack_start(self.mouse_dy_spin, False, False, 0)

        mouse_interval_label = Gtk.Label(label="间隔 (秒):")
        mouse_params_box.pack_start(mouse_interval_label, False, False, 0)
        adj_mi = Gtk.Adjustment(value=self.config.get("mouse", {}).get("interval", 60),
                                lower=10, upper=3600, step_increment=10)
        self.mouse_interval_spin = Gtk.SpinButton()
        self.mouse_interval_spin.set_adjustment(adj_mi)
        mouse_params_box.pack_start(self.mouse_interval_spin, False, False, 0)

        self.mouse_return_check = Gtk.CheckButton(label="移动后返回原位")
        self.mouse_return_check.set_active(self.config.get("mouse", {}).get("return_to_origin", True))
        mouse_box.pack_start(self.mouse_return_check, False, False, 0)

        # 分隔线
        main_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # 键盘操作配置
        key_frame = Gtk.Frame(label="键盘微操作配置")
        key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        key_frame.add(key_box)
        main_box.pack_start(key_frame, False, False, 0)

        self.key_enabled_check = Gtk.CheckButton(label="启用键盘微操作")
        self.key_enabled_check.set_active(self.config.get("keyboard", {}).get("enabled", True))
        key_box.pack_start(self.key_enabled_check, False, False, 0)

        key_params_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        key_box.pack_start(key_params_box, False, False, 0)

        key_label = Gtk.Label(label="按键 (逗号分隔):")
        key_params_box.pack_start(key_label, False, False, 0)

        keys_str = ",".join(self.config.get("keyboard", {}).get("keys", ["shift"]))
        self.key_entry = Gtk.Entry()
        self.key_entry.set_text(keys_str)
        self.key_entry.set_placeholder_text("shift,ctrl,alt")
        key_params_box.pack_start(self.key_entry, True, True, 0)

        key_interval_label = Gtk.Label(label="间隔 (秒):")
        key_params_box.pack_start(key_interval_label, False, False, 0)
        adj_ki = Gtk.Adjustment(value=self.config.get("keyboard", {}).get("interval", 120),
                                lower=10, upper=3600, step_increment=10)
        self.key_interval_spin = Gtk.SpinButton()
        self.key_interval_spin.set_adjustment(adj_ki)
        key_params_box.pack_start(self.key_interval_spin, False, False, 0)

        # 提示
        hint_label = Gtk.Label()
        hint_label.set_markup("<small>支持的按键名称: shift, ctrl, alt, super, menu, caps_lock 等\n"
                              "按键仅触发 press+release，不会输入任何字符</small>")
        hint_label.set_margin_top(4)
        key_box.pack_start(hint_label, False, False, 0)

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
                with open(PID_FILE, "r") as f:
                    pid = f.read().strip()
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
        self._save_current_config()
        try:
            subprocess.run([sys.executable, KEEP_ALIVE_SCRIPT, "--start"],
                           capture_output=True, timeout=10)
            self.update_status()
        except Exception as e:
            self.status_label.set_text(f"启动失败: {e}")

    def on_stop_clicked(self, btn):
        """停止守护进程。"""
        try:
            subprocess.run([sys.executable, KEEP_ALIVE_SCRIPT, "--stop"],
                           capture_output=True, timeout=10)
            self.update_status()
        except Exception as e:
            self.status_label.set_text(f"停止失败: {e}")

    def on_refresh_clicked(self, btn):
        """手动刷新状态。"""
        self.update_status()

    def _save_current_config(self):
        """将当前界面配置写入配置文件。"""
        targets_text = self.targets_buffer.get_text(
            self.targets_buffer.get_start_iter(),
            self.targets_buffer.get_end_iter(),
            True
        )
        targets = [t.strip() for t in targets_text.split("\n") if t.strip()]

        cfg = {
            "enabled": True,
            "ping": {
                "targets": targets,
                "interval": self.ping_interval_spin.get_value_as_int(),
                "timeout": self.ping_timeout_spin.get_value_as_int(),
                "count": self.ping_count_spin.get_value_as_int()
            },
            "mouse": {
                "enabled": self.mouse_enabled_check.get_active(),
                "interval": self.mouse_interval_spin.get_value_as_int(),
                "dx": self.mouse_dx_spin.get_value_as_int(),
                "dy": self.mouse_dy_spin.get_value_as_int(),
                "return_to_origin": self.mouse_return_check.get_active()
            },
            "keyboard": {
                "enabled": self.key_enabled_check.get_active(),
                "interval": self.key_interval_spin.get_value_as_int(),
                "keys": [k.strip() for k in self.key_entry.get_text().split(",") if k.strip()]
            }
        }
        save_config(cfg)

    def on_save_clicked(self, btn):
        """保存配置按钮。"""
        self._save_current_config()
        # 如果守护进程正在运行，通知其重新加载配置
        if is_daemon_running():
            try:
                with open(PID_FILE, "r") as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGUSR1)  # 通知重新加载
            except (OSError, ValueError):
                pass
        self.status_label.set_text("配置已保存")


if __name__ == "__main__":
    import signal

    win = KeepAliveGUI()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
