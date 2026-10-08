#!/bin/bash
# atrust-host-routes.sh —— 把 aTrust 容器 utun7 的分时路由镜像到宿主机路由表，
# 使宿主机(以及经宿主 ProxyJump/转发的客户端)无需 SOCKS 代理直达 VPN 下发的内网网段。
# 前置条件(容器镜像 start.sh 已自带): ip_forward=1、POSTROUTING -o utun7 MASQUERADE、
# iif utun7 -> table 2 回程策略路由。
# 幂等，由 atrust-host-routes.timer 周期调用，跟踪 aTrust 重连后的路由变化。
# 2026-10-08 zhj (Docker-aTrust 项目)
set -u

CONTAINER="${ATRUST_CONTAINER:-atrust-ubuntu}"
MARKER="/run/atrust-host-routes.list"
# aTrust DNS 假 IP 段(benchmark 保留网段)不镜像到宿主
FAKEIP_EXCLUDE='^198\.(18|19)\.'

state_running=$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)
[ "$state_running" = "true" ] || exit 0

CIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER")
[ -n "$CIP" ] || exit 0

# 1) 容器内 MSS 钳制(幂等; 防隧道内外 MTU 差导致的 SSH 大包卡死)
for dir_flag in "-o" "-i"; do
	docker exec "$CONTAINER" iptables -C FORWARD $dir_flag utun7 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
	docker exec "$CONTAINER" iptables -A FORWARD $dir_flag utun7 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
done

# 2) 镜像 utun7 分时路由到宿主(经容器 veth 转发, 容器内 MASQUERADE 成 2.0.0.1 出隧道)
new_list=""
for dst in $(docker exec "$CONTAINER" ip -4 route show dev utun7 | awk '{print $1}' | grep -v '^default$'); do
	echo "$dst" | grep -qE "$FAKEIP_EXCLUDE" && continue
	ip route replace "$dst" via "$CIP" 2>/dev/null || { echo "WARN: replace $dst via $CIP failed" >&2; continue; }
	new_list="$new_list $dst"
done

# 3) 清理上次加过、本次已消失的路由(aTrust 重连后分时路由可能变化)
for dst in $(cat "$MARKER" 2>/dev/null); do
	case " $new_list " in
		*" $dst "*) ;;
		*) ip route del "$dst" 2>/dev/null ;;
	esac
done
printf '%s\n' $new_list > "$MARKER"

# 4) 宿主转发开关兜底(docker daemon 通常已置 1)
[ "$(cat /proc/sys/net/ipv4/ip_forward)" = "1" ] || sysctl -w net.ipv4.ip_forward=1 >/dev/null

exit 0
