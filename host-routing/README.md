# host-routing —— aTrust 容器 NAT 网关化（宿主机 SSH 跳板）

## 目标

去除对容器内 danted(SOCKS5)/tinyproxy(HTTP) 代理的依赖：让 aTrust 容器充当 NAT 网关，
宿主机通过路由镜像直达 VPN 下发的内网网段，进而作为 SSH 跳板机供内网其他客户端
（如 Tailscale 组网设备）使用。

> 本文档所有 IP / 用户名 / 主机名均为示例占位，部署时替换为实际值；
> 请勿在公开仓库中提交真实内网拓扑、地址或凭证。

## 原理

容器镜像 `start.sh` 已自带三个关键配置（无需改动镜像）：

1. 容器内 `net.ipv4.ip_forward=1`；
2. `iptables -t nat -A POSTROUTING -o utun7 -j MASQUERADE`（`config_vpn_iptables()`）；
3. `ip rule add iif utun7 table 2` 回程策略路由（`detect-route.sh`）。

因此只需把 aTrust 下发的 utun7 分时路由（若干 /32 与小掩码网段，形如
`198.51.100.10/31`）镜像到宿主机路由表：`ip route replace <dst> via <容器IP>`。
流量路径：客户端 → 宿主机 → 容器 veth → 容器内 FORWARD +
MASQUERADE(源改写为 2.0.0.1) → utun7 隧道 → VPN 内网目标。

198.18.0.0/15 是 aTrust 的 DNS 假 IP 段（benchmark 保留网段），脚本不镜像。

## 宿主机部署内容

| 文件（宿主机路径） | 来源 | 说明 |
|---|---|---|
| `/usr/local/bin/atrust-host-routes.sh` | `atrust-host-routes.sh` | 幂等同步脚本：动态解析容器 IP、镜像 utun7 路由、容器内补 MSS clamp、清理失效路由 |
| `/etc/systemd/system/atrust-host-routes.service` | 同名 | oneshot |
| `/etc/systemd/system/atrust-host-routes.timer` | 同名 | 开机 45s 后首跑，之后每 60s 一跑（跟踪 aTrust 重连后的路由变化） |
| `/etc/ssh/sshd_config.d/00-enable-forwarding.conf` | — | `AllowTcpForwarding yes`。部分 NAS 固件在 `sshd_config.d/` 里固化了 `AllowTcpForwarding no`，ProxyJump 必需；本文件按字典序更靠前覆盖（sshd 取首个出现的值） |
| `<compose 项目目录>/docker-compose.yml` | `docker-compose.host-routing-example.yml` | 增加 `net.ipv4.ip_forward=1` sysctl 与固定容器 IP（可选）；修改后需 `docker compose up -d` 重建生效，VPN 可能需重新登录 |

跳板机侧另需：客户端公钥装入宿主机 `authorized_keys`（ProxyJump 免密）。

## 验证要点

- 宿主机本机裸 TCP 内网目标 22 端口 → 应返回 `SSH-2.0-...` 横幅（无代理）；
- 客户端 `ssh -J <jump-user>@<跳板机IP>:<端口> <target-user>@<内网目标>` → 免代理免密连通。

## 建议的客户端配置（~/.ssh/config）

```
Host jump
    HostName <跳板机IP>
    Port <SSH端口>
    User <jump-user>
    IdentityFile ~/.ssh/id_ed25519

Host intranet-target
    HostName <内网目标IP>
    User <target-user>
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ProxyJump jump        # 替换原 SOCKS ProxyCommand
```

## 回退

- `sudo systemctl disable --now atrust-host-routes.timer` 并删除 service/timer；
- `for d in $(cat /run/atrust-host-routes.list); do sudo ip route del $d; done`；
- sshd：删除 `/etc/ssh/sshd_config.d/00-enable-forwarding.conf` 后 `systemctl restart ssh`；
- danted(1080)/tinyproxy(8888) 保留未动，可随时切回 SOCKS 方案。

## 注意

- 若 aTrust 重连后下发了新的分时路由，脚本会在 60s 内自动同步；同步周期内新目标
  短暂不可达属正常。
- 内网域名解析不在本方案范围（IP 直连为主）；如需域名，可将内网 DNS IP 加入
  aTrust 分时资源后由脚本自动镜像，再配置宿主机的 systemd-resolved per-link DNS。
- 安全提醒：公开仓库不要提交真实内网地址、服务器用户名/密码、`.workbuddy/` 记忆
  文件与 `.env`（均已列入 `.gitignore`）。
