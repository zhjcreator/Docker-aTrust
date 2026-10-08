#!/bin/bash
eval "$(detect-iptables.sh)"
eval "$(vpn-config.sh)"
eval "$(detect-route.sh)"

# 修复 /etc 目录权限: 基础镜像的 /etc 是 700(root-only), 导致 aTrustAgent 通过
# su sangfor 启动 aTrustCore 时读不到 /etc/passwd /etc/nsswitch.conf, 进而
# getent+awk 等 NSS 调用 Permission denied, aTrustCore fork 后立即崩溃,
# 客户端反复弹 "The core service was started, causing some functions to be abnormal"。
# 同样的根因也影响任何以非 root 用户运行的子进程。Dockerfile 已尽量修复,
# 此处作为运行期保险, 容器启动时再次修正。
if [ "$(stat -c %a /etc 2>/dev/null)" != "755" ]; then
	chmod 0755 /etc 2>/dev/null || true
fi
[ -r /etc/passwd ] || chmod a+r /etc/passwd 2>/dev/null || true
[ -r /etc/group ] || chmod a+r /etc/group 2>/dev/null || true
[ -r /etc/nsswitch.conf ] || chmod a+r /etc/nsswitch.conf 2>/dev/null || true

ensure_machine_id() {
	# 部分程序（如 Electron/DBus）需要 machine-id。
	if [ ! -s /etc/machine-id ]; then
		if command -v dbus-uuidgen >/dev/null 2>&1; then
			dbus-uuidgen --ensure=/etc/machine-id >/dev/null 2>&1
		else
			cat /proc/sys/kernel/random/uuid | tr -d '-' > /etc/machine-id
		fi
	fi

	mkdir -p /var/lib/dbus
	if [ ! -s /var/lib/dbus/machine-id ]; then
		ln -sf /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null || cp /etc/machine-id /var/lib/dbus/machine-id
	fi
}

ensure_machine_id

forward_ports() {
	if [ -n "$FORWARD" ]; then
		if iptables -t mangle -A PREROUTING -m addrtype --dst-type LOCAL -j MARK --set-mark 2; then
			iptables -t mangle -D PREROUTING -m addrtype --dst-type LOCAL -j MARK --set-mark 2
			iptables -t nat -A POSTROUTING -p tcp -m mark --mark 2 -j MASQUERADE
			ip rule add fwmark 2 table 2
			format_error() { echo Format error in \""$rule"\": "$@" >&2 ; }
			for rule in $FORWARD; do
				array=(${rule//:/ })
				case ${#array[@]} in
					3) src_args="" ;;
					4) src_args="-s ${array[0]}" ;;
					*) format_error; continue ;;
				esac
				dst=${array[-2]}:${array[-1]}
				dport=${array[-3]}
				match_args="$src_args --dport $dport -m addrtype --dst-type LOCAL -i $VPN_TUN"
				iptables -t mangle -A PREROUTING -p tcp $match_args -j MARK --set-mark 2
				iptables -t mangle -A PREROUTING -p udp $match_args -j MARK --set-mark 2
				iptables -t nat -A PREROUTING -p tcp $match_args -j DNAT --to-destination $dst
				iptables -t nat -A PREROUTING -p udp $match_args -j DNAT --to-destination $dst

			done
		else
			echo "Can't append iptables used to forward ports from EasyConnect to host network!" >&2
		fi
	fi
}

start_danted() {
	cp /etc/danted.conf.sample /run/danted.conf

	if [[ -n "$SOCKS_PASSWD" && -n "$SOCKS_USER" ]];then
		id $SOCKS_USER &> /dev/null
		if [ $? -ne 0 ]; then
			useradd $SOCKS_USER
		fi

		echo $SOCKS_USER:$SOCKS_PASSWD | chpasswd
		sed -i 's/socksmethod: none/socksmethod: username/g' /run/danted.conf

		echo "use socks5 auth: $SOCKS_USER:$SOCKS_PASSWD"
	fi

	internals=""
	externals=""
        ipv6=$(ip -6 a)
        if [[ $ipv6 ]]; then
                internals="internal: 0.0.0.0 port = 1080\\ninternal: :: port = 1080"
        else

                internals="internal: 0.0.0.0 port = 1080"
        fi
	for iface in $(ip -o addr | sed -E 's/^[0-9]+: ([^ ]+) .*/\1/' | sort | uniq | grep -v "sit\|vir"); do
		externals="${externals}external: $iface\\n"
	done
	externals="${externals}external: $VPN_TUN\\n"
	sed /^internal:/c"$internals" -i /run/danted.conf
	sed /^external:/c"$externals" -i /run/danted.conf
	open_port 1080
	if ip tuntap add mode tun $VPN_TUN; then
		# eth0 need >1s to be ready
		# refer to https://stackoverflow.com/questions/25226531/dante-sever-fail-to-bind-ip-by-interface-name-in-docker-container
		ip addr add 10.0.0.1/32 dev $VPN_TUN
		sleep 2
		/usr/sbin/danted -D -f /run/danted.conf
		ip tuntap del mode tun $VPN_TUN
	else
		echo 'Failed to create tun interface! Please check whether /dev/net/tun is available.' >&2
		echo 'Also refer to https://github.com/Hagb/docker-easyconnect/blob/master/doc/faq.md.' >&2
		exit 1
	fi
}

tinyproxy_is_listening_8888() {
	if command -v ss >/dev/null 2>&1; then
		ss -lnt 2>/dev/null | grep -qE '[:.]8888[[:space:]]'
		return $?
	fi

	if command -v netstat >/dev/null 2>&1; then
		netstat -lnt 2>/dev/null | grep -qE '[:.]8888[[:space:]]'
		return $?
	fi

	return 1
}

dump_tinyproxy_diagnostics() {
	local tinyproxy_log_dir=/var/log/tinyproxy
	local tinyproxy_run_dir=/var/run/tinyproxy

	ls -ld "$tinyproxy_log_dir" "$tinyproxy_run_dir" 2>/dev/null >&2 || true
	[ -f /etc/tinyproxy.conf ] && grep -nE '^(User|Group|Port|PidFile|LogFile|StartServers|MinSpareServers|MaxSpareServers|MaxClients|LogLevel)' /etc/tinyproxy.conf >&2 || true
	[ -f /var/log/tinyproxy/tinyproxy.log ] && tail -n 80 /var/log/tinyproxy/tinyproxy.log >&2 || true
	ps -ef | grep -E '[t]inyproxy' >&2 || true
	ss -lntp 2>/dev/null | grep -E '[:.]8888[[:space:]]' >&2 || true
}

wait_tinyproxy_ready() {
	local tries=20
	while [ $tries -gt 0 ]; do
		if pgrep -x tinyproxy >/dev/null 2>&1 && tinyproxy_is_listening_8888; then
			return 0
		fi
		tries=$((tries - 1))
		sleep 0.2
	done
	return 1
}

start_tinyproxy() {
	local tinyproxy_log_dir=/var/log/tinyproxy
	local tinyproxy_run_dir=/var/run/tinyproxy
	local rc

	open_port 8888

	mkdir -p "$tinyproxy_log_dir" "$tinyproxy_run_dir" || {
		echo "ERROR: Failed to create tinyproxy runtime directories." >&2
		return 1
	}
	chown daemon:daemon "$tinyproxy_log_dir" "$tinyproxy_run_dir" || {
		echo "ERROR: Failed to set tinyproxy runtime directory owner." >&2
		ls -ld "$tinyproxy_log_dir" "$tinyproxy_run_dir" 2>/dev/null >&2 || true
		return 1
	}

	echo "Starting tinyproxy on port 8888..."
	tinyproxy -c /etc/tinyproxy.conf
	rc=$?
	if [ $rc -ne 0 ]; then
		echo "ERROR: tinyproxy failed to start with /etc/tinyproxy.conf (exit $rc)." >&2
		dump_tinyproxy_diagnostics
		return $rc
	fi

	if ! wait_tinyproxy_ready; then
		echo "ERROR: tinyproxy started but failed readiness checks on port 8888." >&2
		dump_tinyproxy_diagnostics
		killall tinyproxy 2>/dev/null || true
		return 1
	fi

	echo "tinyproxy is ready on port 8888."
	return 0
}

watch_tinyproxy_required() {
	while sleep 2; do
		if ! pgrep -x tinyproxy >/dev/null 2>&1; then
			echo "ERROR: tinyproxy process is missing; port 8888 is mandatory. Stopping container." >&2
			dump_tinyproxy_diagnostics
			kill -TERM 1 2>/dev/null || true
			sleep 1
			kill -KILL 1 2>/dev/null || true
			exit 1
		fi

		if ! tinyproxy_is_listening_8888; then
			echo "ERROR: tinyproxy is not listening on 8888; port 8888 is mandatory. Stopping container." >&2
			dump_tinyproxy_diagnostics
			kill -TERM 1 2>/dev/null || true
			sleep 1
			kill -KILL 1 2>/dev/null || true
			exit 1
		fi
	done
}

config_vpn_iptables() {
	iptables -t nat -A POSTROUTING -o $VPN_TUN -j MASQUERADE
	open_port 4440
	iptables -t nat -N SANGFOR_OUTPUT
	iptables -t nat -A PREROUTING -j SANGFOR_OUTPUT

	# 拒绝 tun 侧主动请求的连接.
	iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
	iptables -A INPUT -i $VPN_TUN -p tcp -j DROP
}

force_open_ports() {
	# 暴露 54530 等用于和浏览器通讯的端口
	tmp_port=20000
	for port in $FORCE_OPEN_PORTS; do
		open_port $port
		open_port $tmp_port
		iptables -t nat -A PREROUTING -p tcp --dport $port -m addrtype --dst-type LOCAL -j REDIRECT --to-port $tmp_port
		socat tcp-listen:$tmp_port,reuseaddr,fork tcp4:127.0.0.1:$port &
		((tmp_port++))
	done
}

	init_vpn_config() {
		if [ "EC_CLI" = "$_VPN_TYPE" ]; then
			ln -fs /usr/share/sangfor/EasyConnect/resources/{conf_${EC_VER},conf}
		fi

	if [ "EC_GUI" = "$_VPN_TYPE" ]; then
		# 登录信息持久化处理
		## 持久化配置文件夹 感谢 @hexid26 https://github.com/Hagb/docker-easyconnect/issues/21
		cp -r /usr/share/sangfor/EasyConnect/resources/conf_backup/. ~/conf/
		rm -f ~/conf/ECDomainFile
		[ -e ~/easy_connect.json ] && mv ~/easy_connect.json ~/conf/easy_connect.json # 向下兼容
		mkdir -p /usr/share/sangfor/EasyConnect/resources/conf/
		cd ~/conf/

		## 不再假定 /root 的文件系统（可能从宿主机挂载）支持 unix sock（用于 ECDomainFile），因此不直接使用
		for file in *; do
			## 通过软链接减小拷贝量
			ln -s ~/conf/"$file" /usr/share/sangfor/EasyConnect/resources/conf/"$file"
		done
		cd -
		[ -n "$DISABLE_PKG_VERSION_XML" ] && ln -fs /dev/null /usr/share/sangfor/EasyConnect/resources/conf/pkg_version.xml

		sync_ec2volume() {
			cd /usr/share/sangfor/EasyConnect/resources/conf/
			[ -n "$DISABLE_PKG_VERSION_XML" ] && rm pkg_version.xml
			for file in *; do
				[ -r "$file" -a ! -L "$file" -a "ECDomainFile" != "$file" ] && cp -r "$file" ~/conf/
			done
			cd ~/conf/
			for file in *; do
				[ ! -e /usr/share/sangfor/EasyConnect/resources/conf/"$file" ] && {
					rm -r "$file"
				}
			done
		}
		## 容器退出时将配置文件同步回 /root/conf。感谢 @Einskai 的点子
		trap "sync_ec2volume; exit;" SIGINT SIGQUIT SIGSTOP SIGTSTP SIGTERM
	else
		trap "exit;" SIGINT SIGQUIT SIGSTOP SIGTSTP SIGTERM
		fi
	}

	wait_for_x() {
		x_ready_once() {
			if command -v xprop >/dev/null 2>&1; then
				DISPLAY="$DISPLAY" xprop -root >/dev/null 2>&1 && return 0
			elif command -v xset >/dev/null 2>&1; then
				DISPLAY="$DISPLAY" xset q >/dev/null 2>&1 && return 0
			else
				return 0
			fi
			return 1
		}

		local tries=50
		while [ $tries -gt 0 ]; do
			x_ready_once && return 0
			tries=$((tries - 1))
			sleep 0.1
		done
		return 1
	}

	cleanup_stale_vnc_display() {
		local display="${DISPLAY:-:1}"
		local display_num="${display#:}"
		local x_lock="/tmp/.X${display_num}-lock"
		local x_sock="/tmp/.X11-unix/X${display_num}"
		local pidfile

		[[ "$display_num" =~ ^[0-9]+$ ]] || return 0

		# 若当前显示已可用，则不要误删真实 socket/lock。
		if wait_for_x >/dev/null 2>&1; then
			return 0
		fi

		if pgrep -af "Xtigervnc ${display}" >/dev/null 2>&1 || pgrep -af "Xvnc ${display}" >/dev/null 2>&1; then
			return 0
		fi

		if [ -e "$x_lock" ] || [ -S "$x_sock" ]; then
			echo "Cleaning stale VNC display artifacts for ${display}..." >&2
			rm -f -- "$x_lock" "$x_sock" 2>/dev/null || true
		fi

		for pidfile in "${HOME:-/root}"/.vnc/*:"${display_num}".pid; do
			[ -e "$pidfile" ] || continue
			echo "Removing stale VNC pidfile: ${pidfile}" >&2
			rm -f -- "$pidfile" 2>/dev/null || true
		done
	}

	setup_desktop_shortcuts() {
		local desktop_dir="${HOME:-/root}/Desktop"
		local desktop_entry
		mkdir -p "$desktop_dir"

		if [ -x /usr/share/sangfor/aTrust/aTrustTray ]; then
			local atrust_launcher="/usr/local/bin/atrust-launcher"
			cat > "$atrust_launcher" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

daemon_bin="/usr/share/sangfor/aTrust/resources/bin/aTrustAgent"
daemon_sh="/usr/share/sangfor/aTrust/resources/shell/aTrustDaemon.sh"
tray_bin="/usr/share/sangfor/aTrust/aTrustTray"

if [ -x "$daemon_sh" ] && [ -x "$daemon_bin" ]; then
	if ! pgrep -f "${daemon_bin} --plugin plugin-daemon" >/dev/null 2>&1; then
		"$daemon_sh" start >/tmp/atrust-daemon-start.log 2>&1 || true
		sleep 2
	fi
fi

exec "$tray_bin" --no-sandbox --disable-gpu "$@"
EOF
			chmod 0755 "$atrust_launcher"

			desktop_entry="$(mktemp "$desktop_dir/.aTrust.desktop.XXXXXX")" || return 1
			cat > "$desktop_entry" <<'EOF'
[Desktop Entry]
Type=Application
Version=1.0
Name=aTrust
Exec=/usr/local/bin/atrust-launcher
Icon=/usr/share/sangfor/aTrust/resources/aTrust.png
Terminal=false
Categories=Network;
EOF
			chmod 0755 "$desktop_entry"
			mv -f "$desktop_entry" "$desktop_dir/aTrust.desktop"

			if [ -f /usr/share/applications/cn.com.sangfor.atrust.desktop ]; then
				sed -i 's#^Exec=.*#Exec=/usr/local/bin/atrust-launcher#' /usr/share/applications/cn.com.sangfor.atrust.desktop
			fi
		fi

		local chromium_cmd=""
		if command -v chromium-launcher >/dev/null 2>&1; then
			chromium_cmd="$(command -v chromium-launcher)"
		elif command -v chromium >/dev/null 2>&1; then
			chromium_cmd="$(command -v chromium) --no-sandbox --disable-gpu --disable-dev-shm-usage"
		elif command -v chromium-browser >/dev/null 2>&1; then
			chromium_cmd="$(command -v chromium-browser) --no-sandbox --disable-gpu --disable-dev-shm-usage"
		fi

		if [ -n "$chromium_cmd" ]; then
			desktop_entry="$(mktemp "$desktop_dir/.Chromium.desktop.XXXXXX")" || return 1
			cat > "$desktop_entry" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Chromium
Exec=$chromium_cmd %U
Icon=/usr/share/pixmaps/chromium-browser.png
Terminal=false
Categories=Network;WebBrowser;
EOF
			chmod 0755 "$desktop_entry"
			mv -f "$desktop_entry" "$desktop_dir/Chromium.desktop"
		fi

		# 保活程序桌面快捷方式
		if command -v keep-alive-launcher >/dev/null 2>&1; then
			desktop_entry="$(mktemp "$desktop_dir/.KeepAlive.desktop.XXXXXX")" || return 1
			cat > "$desktop_entry" <<'EOF'
[Desktop Entry]
Type=Application
Version=1.0
Name=Keep Alive
Comment=Keep Alive settings
TryExec=/usr/local/bin/keep-alive-launcher
Exec=/usr/local/bin/keep-alive-launcher
Icon=preferences-system
Terminal=false
StartupNotify=false
Categories=System;Settings;
EOF
			chmod 0755 "$desktop_entry"
			mv -f "$desktop_entry" "$desktop_dir/KeepAlive.desktop"
		fi
	}

	start_desktop_icons() {
		command -v pcmanfm >/dev/null 2>&1 || return 0
		pidof pcmanfm >/dev/null 2>&1 && return 0

		wait_for_x || true

		# start_tigervncserver 启动后 Xvnc 才会异步往 ~/.Xauthority 写入 cookie; start.sh 把两个函数都 &
		# 并发拉起, 这里必须额外等 Xauthority 文件实际就绪(且非空), 否则 pcmanfm 启动时仍会命中空/旧 cookie 报
		# "Cannot open display"。
		local xauth_file="$HOME/.Xauthority"
		local xauth_tries=50
		while [ $xauth_tries -gt 0 ]; do
			if [ -s "$xauth_file" ]; then
				DISPLAY="$DISPLAY" XAUTHORITY="$xauth_file" xprop -root >/dev/null 2>&1 && break
			fi
			xauth_tries=$((xauth_tries - 1))
			sleep 0.1
		done

		setup_desktop_shortcuts

		# 注意：当 /root 从宿主机挂载（Docker Desktop 的 fakeowner）时，~/.cache 往往不支持 Unix socket。
		# pcmanfm 会在 XDG_CACHE_HOME 下创建 socket；把它指到 /tmp（tmpfs）可避免启动失败导致桌面图标不显示。
		local pcmanfm_cache_dir="/tmp/pcmanfm-cache"
		local pcmanfm_runtime_dir="/tmp/pcmanfm-runtime"
		mkdir -p "$pcmanfm_cache_dir" "$pcmanfm_runtime_dir"
		chmod 0700 "$pcmanfm_cache_dir" "$pcmanfm_runtime_dir" >/dev/null 2>&1 || true

		# 静默 pcmanfm 的无害 WARNING: ~/Templates 不存在; 这里建一个空目录即可,不影响功能。
		mkdir -p "$HOME/Templates"

		XDG_CACHE_HOME="$pcmanfm_cache_dir" XDG_RUNTIME_DIR="$pcmanfm_runtime_dir" \
			DISPLAY="$DISPLAY" XAUTHORITY="$xauth_file" \
			pcmanfm --desktop --display="$DISPLAY" >/tmp/pcmanfm-desktop.log 2>&1 &
		disown >/dev/null 2>&1 || true
	}

	start_desktop_icons_delayed() {
		# 部分环境下 X/认证就绪较慢，pcmanfm 可能会启动失败；这里做简单重试。
		local tries=30
		while [ $tries -gt 0 ]; do
			start_desktop_icons
			pidof pcmanfm >/dev/null 2>&1 && return 0
			tries=$((tries - 1))
			sleep 0.5
		done
		echo "WARNING: pcmanfm desktop icons failed to start after retries." >&2
		[ -f /tmp/pcmanfm-desktop.log ] && tail -n 50 /tmp/pcmanfm-desktop.log >&2 || true
		return 1
	}

start_tigervncserver() {
	local rc

	# 清理过期 X 授权: /root 为持久卷, 每次重启 Xvnc 会向 ~/.Xauthority 追加新 cookie 但不清理旧条目,
	# 导致 Xlib 命中错误 cookie, pcmanfm 等客户端报 "Cannot open display"。删除后由 Xvnc 重新生成单一正确 cookie。
	rm -f "$HOME/.Xauthority"

	# 固定 VNC 密码（默认 password），避免每次重建/重启后随机变化。
		# 如需自定义，显式传入环境变量 PASSWORD。
		local vnc_password="${PASSWORD:-password}"
		mkdir -p ~/.vnc
		printf %s "$vnc_password" | tigervncpasswd -f > ~/.vnc/passwd
		chmod 0600 ~/.vnc/passwd 2>/dev/null || true

	VNC_SIZE="${VNC_SIZE:-1110x620}"

	open_port 5901
	cleanup_stale_vnc_display
	tigervncserver "$DISPLAY" -geometry "$VNC_SIZE" -localhost no -passwd ~/.vnc/passwd -xstartup jwm
	rc=$?
	if [ $rc -ne 0 ]; then
		echo "WARNING: tigervncserver failed to start on ${DISPLAY} (exit ${rc}), retrying after cleanup." >&2
		cleanup_stale_vnc_display
		tigervncserver "$DISPLAY" -geometry "$VNC_SIZE" -localhost no -passwd ~/.vnc/passwd -xstartup jwm
		rc=$?
		if [ $rc -ne 0 ]; then
			echo "ERROR: tigervncserver failed to start on ${DISPLAY} after retry (exit ${rc})." >&2
			ls -l /tmp/.X11-unix /tmp/.X1-lock 2>/dev/null >&2 || true
			ls -l ~/.vnc 2>/dev/null >&2 || true
			tail -n 80 ~/.vnc/*.log 2>/dev/null >&2 || true
			return $rc
		fi
	fi
	# stalonetray 已由 jwm 内置托盘取代, 避免双托盘

	if [ -n "$ECPASSWORD" ]; then
		echo "ECPASSWORD has been deprecated, because of the confusion of its name." >&2
		echo "Use CLIP_TEXT instead." >&2
	fi

	[ -z "$CLIP_TEXT" ] && CLIP_TEXT="$ECPASSWORD"

	# 将 easyconnect 的密码放入粘贴板中，应对密码复杂且无法保存的情况 (eg: 需要短信验证登录)
	# 感谢 @yakumioto https://github.com/Hagb/docker-easyconnect/pull/8
	echo "$CLIP_TEXT" | DISPLAY=:1 xclip -selection c

	# 双向同步 VNC 剪贴板(CLIPBOARD/PRIMARY selections) ↔ X server。
	# noVNC 客户端的剪贴板通过 RFB ServerCutText/ClientCutText 消息传到 Xtigervnc,
	# Xtigervnc 本身不写 X selection, 必须靠桥接进程; 否则 noVNC 复制的文本到 VNC 桌面就丢失。
	# 主用 Python vnc-clip-bridge.py (autocutsel 在 Ubuntu 18.04 + Xtigervnc 1.10 上经常异常退出)。
	if [ -x /usr/local/bin/start-vcb.sh ]; then
		/usr/local/bin/start-vcb.sh || true
	fi
	if command -v autocutsel >/dev/null 2>&1; then
		DISPLAY="$DISPLAY" XAUTHORITY="$HOME/.Xauthority" autocutsel -fork -selection CLIPBOARD -selection PRIMARY >/tmp/autocutsel.log 2>&1 &
		disown >/dev/null 2>&1 || true
	fi

	# 环境变量USE_NOVNC不为空时，启动 easy-novnc
	if [ -n "$USE_NOVNC" ]; then
		open_port 8080
		novnc
	fi

}

keep_pinging() {
	[ -n "$PING_ADDR" ] && while sleep $PING_INTERVAL; do
		busybox ping -c1 -W1 -w1 "$PING_ADDR" >/dev/null 2>/dev/null
	done &
}

# 部分服务器禁ping，用wget一个网页的url代替
keep_pinging_url() {
	[ -n "$PING_ADDR_URL" ] && while sleep $PING_INTERVAL; do
		timeout 10 busybox wget -q --spider "$PING_ADDR_URL" 2>/dev/null
	done &
}

# container 再次运行时清除 /tmp 中的锁，使 container 能够反复使用。
# 感谢 @skychan https://github.com/Hagb/docker-easyconnect/issues/4#issuecomment-660842149
for f in /tmp/* /tmp/.*; do
	[ "/tmp/.X11-unix" != "$f" ] && [ "/tmp/." != "$f" ] && [ "/tmp/.." != "$f" ] && rm -rf -- "$f"
done

ulimit -n 1048576 # https://github.com/Hagb/docker-easyconnect/issues/245 @rikaunite
forward_ports &
start_danted &
if ! start_tinyproxy; then
	echo "ERROR: tinyproxy failed and port 8888 is mandatory." >&2
	exit 1
fi
watch_tinyproxy_required &
config_vpn_iptables &
force_open_ports &
keep_pinging &
keep_pinging_url &
if [ -z "$DISPLAY" ]
then
	export DISPLAY=:1
	start_tigervncserver &
	start_desktop_icons_delayed &
fi

# 环境变量 CHROMIUM 不为空时，删除可能存在的锁，并启动 chromium
if [ -n "$CHROMIUM" ]; then
	if command -v chromium-launcher >/dev/null 2>&1; then
		export BROWSER="$(command -v chromium-launcher)"
		ln -sf "$(command -v chromium-launcher)" /usr/bin/x-www-browser
		ln -sf "$(command -v chromium-launcher)" /usr/bin/www-browser
		ln -sf "$(command -v chromium-launcher)" /usr/bin/gnome-www-browser

		# 等待 X 就绪，避免 Chromium 早于 VNC/X 启动导致闪退或无法弹出窗口。
		wait_for_x || true

		# 尽量只清理锁文件，保留用户配置（若挂载 /root，可持久化登录态）。
		rm -f /root/.config/chromium/SingletonLock /root/.config/chromium/SingletonCookie /root/.config/chromium/SingletonSocket 2>/dev/null || true

		chromium-launcher about:blank >/dev/null 2>&1 &
		disown >/dev/null 2>&1 || true
	else
		echo "WARNING: CHROMIUM is set but chromium-launcher is not found." >&2
	fi
fi

init_vpn_config
wait

[ -n "$EXIT" ] && export MAX_RETRY=0
start-sangfor.sh &
SANGFOR_PID=$!

# ATRUST 模式额外兜底:
# 1) vpn_daemon 只起 aTrustAgent(plugin-daemon), 不起 aTrustTray UI, 也不起 aTrustCore
#    (core 是 daemon 自己 fork 的, 但需要 /etc 可读, 否则反复崩)。
#    上方已修复 /etc 权限, 这里确保 daemon fork 一次 core 不起来时再拉一次。
# 2) UI 需要靠 atrust-launcher 手动拉, 我们在 /etc 修复后由这里接管。
if [ "$VPN_TYPE" = "ATRUST" ] || [ "$_VPN_TYPE" = "ATRUST" ]; then
	# 等 daemon 把 core fork 出来 (最常见在 5 秒内)
	for i in $(seq 1 15); do
		if ss -lnt 2>/dev/null | grep -q '[:.]54631[[:space:]]'; then
			break
		fi
		sleep 1
	done

	# 如果 core 没起来, 重启 daemon 一次
	if ! ss -lnt 2>/dev/null | grep -q '[:.]54631[[:space:]]'; then
		echo "WARNING: aTrustCore 54631 not listening, restarting daemon..." >&2
		bash /usr/share/sangfor/aTrust/resources/shell/aTrustDaemon.sh restart >/dev/null 2>&1 || true
		for i in $(seq 1 15); do
			ss -lnt 2>/dev/null | grep -q '[:.]54631[[:space:]]' && break
			sleep 1
		done
	fi

	# 起 UI (aTrustTray) —— 不影响 daemon
	if [ -x /usr/share/sangfor/aTrust/aTrustTray ] && ! pgrep -x aTrustTray >/dev/null 2>&1; then
		DISPLAY="$DISPLAY" XAUTHORITY="${HOME:-/root}/.Xauthority" \
			nohup /usr/share/sangfor/aTrust/aTrustTray --no-sandbox --disable-gpu \
			>/tmp/atrust-tray.log 2>&1 &
		disown >/dev/null 2>&1 || true
	fi
fi

wait $SANGFOR_PID

if [ "EC_GUI" = "$_VPN_TYPE" ]; then
	sync_ec2volume
fi
