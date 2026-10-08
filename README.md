中文 | [**English**](README.en.md)

# Docker-aTrust（Ubuntu GUI + Chromium）

本仓库基于 [docker-easyconnect](https://github.com/docker-easyconnect/docker-easyconnect) 开发，构建一个带图形界面的 Ubuntu 容器，在容器内安装并运行图形界面版 aTrust，并将默认浏览器与 aTrust 的跳转浏览器统一设为 Chromium，便于完成 aTrust 浏览器登录页面的跳转。

容器同时提供：

- VNC 桌面（端口 `5901`，密码由 `PASSWORD` 环境变量设置）。
- noVNC 网页访问（端口 `8080`，浏览器直接打开）。
- SOCKS5 代理（默认端口 `1080`，推荐用于 Clash Verge 分流）。
- HTTP 代理（默认端口 `8888`，必选）。
- aTrust 本地 Web 登录端口（端口 `54631`，用于 aTrust 拉起浏览器的登录流程）。

> **端口可自定义。** SOCKS5 和 HTTP 代理的宿主机端口可通过 `SOCKS_PORT` 和 `HTTP_PORT` 调整，监听地址可通过 `SOCKS_BIND_ADDR` 和 `HTTP_BIND_ADDR` 调整（参见[运行容器](#2-运行容器)）；容器内服务始终监听 `1080` / `8888`。

> **外网代理与本仓库无关。** 如果你同时使用公网代理工具（如 Clash Verge，默认监听 `7897`），可通过 Clash Verge 全局扩展脚本将内网流量指向 Docker 容器代理，并让其他流量继续按原订阅或公网代理规则处理。本仓库不涉及外网代理配置。

## 0. 前置条件

- 已安装 Docker Desktop（macOS / Windows）或 Docker Engine（Linux）。
- （可选）已安装任意 VNC 客户端（macOS 可用系统自带"屏幕共享"；Windows 可用 RealVNC / TightVNC；Linux 可用 TigerVNC Viewer / Remmina）。也可直接使用浏览器访问 noVNC。
- （可选）已安装 Clash Verge（用于在宿主机做分流）。

### 各平台注意事项

| 平台        | 说明                                                                                                                                                                                                                                                                                                               |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **macOS**   | Docker Desktop + 系统自带"屏幕共享"即可。构建命令见下文。                                                                                                                                                                                                                                                          |
| **Windows** | Docker Desktop for Windows + VNC 客户端。`docker run` 命令在 PowerShell 中使用 `` ` `` 换行而非 `\`，`$HOME` 换为 `$env:USERPROFILE`。                                                                                                                                                                             |
| **Linux**   | Docker Engine + VNC 客户端。命令与 macOS 一致。确保 `/dev/net/tun` 设备存在。                                                                                                                                                                                                                                      |
| **WSL 2**   | **推荐直接在 Windows 宿主机运行容器，不在 WSL 内运行。** WSL 2 开启 [Mirrored Networking](https://learn.microsoft.com/en-us/windows/wsl/networking#mirrored-mode-networking) 后，WSL 内的进程可直接通过 `127.0.0.1` 访问 Windows 侧的代理端口，由 Windows 上的 Clash Verge 统一管理分流，无需在 WSL 内单独配置代理。 |

## 1. 构建镜像

本仓库内置了 aTrust 安装包下载地址（Sangfor CDN）对应的 build args，你只需要选择与你的目标架构匹配的文件即可。

### 1.1 Apple Silicon（推荐：arm64）

```bash
cd Docker-aTrust
docker build -t atrust-ubuntu:chromium \
  -f Dockerfile.ubuntu \
  $(cat build-args/atrust-arm64-cn.txt) \
  --build-arg CHROMIUM=1 \
  .
```

### 1.2 Intel / AMD（amd64 / x86_64）

```bash
cd Docker-aTrust
docker build -t atrust-ubuntu:chromium \
  --platform linux/amd64 \
  -f Dockerfile.ubuntu \
  $(cat build-args/atrust-amd64-cn.txt) \
  --build-arg CHROMIUM=1 \
  .
```

说明：

- `--build-arg CHROMIUM=1` 用于在镜像内安装 Chromium。
- `build-args/` 下也提供了多个版本的 aTrust build args，你可以按需替换。

## 2. 运行容器

### 端口配置

Compose 默认将所有端口绑定到 `127.0.0.1`。先复制模板并设置不会被 Git 跟踪的 `.env`：

```bash
cp .env.example .env
chmod 600 .env
```

编辑 `.env` 中的 `VNC_PASSWORD` 后执行 `docker compose up -d`。凭据请保留单引号，例如 `VNC_PASSWORD='random$value'`，避免 Compose 把 `$` 解释成变量。传统 VNC 认证只使用密码前 8 个字符，请使用随机值，但不要依赖 VNC 密码抵御公网攻击。需要从其他受信任设备访问某个服务时，只把对应服务绑定到受信任接口，例如设置 `SOCKS_BIND_ADDR=<trusted-interface-address>`。不要使用 `0.0.0.0`，除非已经配置来源地址防火墙。

### 启动命令

```bash
read -rsp "VNC password: " VNC_PASSWORD && echo
docker run -d --name atrust-ubuntu \
  --device /dev/net/tun \
  --cap-add NET_ADMIN \
  --sysctl net.ipv4.conf.default.route_localnet=1 \
  --shm-size=512m \
  -e PASSWORD="$VNC_PASSWORD" \
  -e CHROMIUM=1 \
  -e URLWIN=1 \
  -e USE_NOVNC=1 \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:5901:5901 \
  -p 127.0.0.1:${SOCKS_PORT:-1080}:1080 \
  -p 127.0.0.1:${HTTP_PORT:-8888}:8888 \
  -p 127.0.0.1:54631:54631 \
  -v $HOME/.atrust-data:/root \
  atrust-ubuntu:chromium
```

<details>
<summary>Windows PowerShell 版本</summary>

```powershell
$SecureVncPassword = Read-Host "VNC password" -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureVncPassword)
try {
  $VncPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
}
$SockPort = if ($env:SOCKS_PORT) { $env:SOCKS_PORT } else { "1080" }
$HttpPort = if ($env:HTTP_PORT) { $env:HTTP_PORT } else { "8888" }

docker run -d --name atrust-ubuntu `
  --device /dev/net/tun `
  --cap-add NET_ADMIN `
  --sysctl net.ipv4.conf.default.route_localnet=1 `
  --shm-size=512m `
  -e "PASSWORD=$VncPassword" `
  -e CHROMIUM=1 `
  -e URLWIN=1 `
  -e USE_NOVNC=1 `
  -p 127.0.0.1:8080:8080 `
  -p 127.0.0.1:5901:5901 `
  -p "127.0.0.1:${SockPort}:1080" `
  -p "127.0.0.1:${HttpPort}:8888" `
  -p 127.0.0.1:54631:54631 `
  -v "$env:USERPROFILE\.atrust-data:/root" `
  atrust-ubuntu:chromium
```

> Windows PowerShell 5.1 不支持 Bash 的 `${VAR:-default}` 或 PowerShell 7 的 `??` 语法，因此示例显式计算默认端口。

</details>

关键点解释：

- `--device /dev/net/tun` + `--cap-add NET_ADMIN`：aTrust 需要创建并配置 TUN 设备。
- `--sysctl net.ipv4.conf.default.route_localnet=1`：用于让 aTrust 的 DNS 分流生效（Docker Desktop 下无法在容器内可靠设置该 sysctl，必须在 `docker run` 时传入）。
- `--shm-size=512m`：避免 Chromium 因 `/dev/shm` 过小而"闪退"。
- `-e PASSWORD="$VNC_PASSWORD"`：设置必填 VNC 密码。传统 VNC 认证只使用前 8 个字符；不要使用示例口令、把真实密码提交到仓库，或将密码视为公网访问保护。
- `-e CHROMIUM=1`：启用容器内 Chromium 自动拉起与跳转处理（包括 aTrust 的登录跳转）。
- `-e URLWIN=1`：当 aTrust 试图打开 URL 时，额外弹窗提示并把 URL 写入剪贴板（排障时很有用）。
- `-e USE_NOVNC=1`：启用 noVNC，通过浏览器访问 `http://<服务器IP>:<宿主机映射端口>/vnc.html` 即可使用 VNC 桌面。
- `-p 127.0.0.1:8080:8080`：noVNC 网页端口（仅在启用 `USE_NOVNC` 时需要）。如需远程访问，仅绑定到受信任的私有接口并配置防火墙或 TLS 反向代理。
- `-v $HOME/.atrust-data:/root`：持久化 `/root`（包括 aTrust 登录信息、Chromium 配置等）。
- `-p ${HTTP_PORT:-8888}:8888`：`8888` 为必选 HTTP 代理端口，若 tinyproxy 启动失败或运行中丢失监听，容器会退出。

## 3. 通过 VNC / noVNC 打开桌面并登录 aTrust

### 方式一：VNC 客户端

1. 使用 VNC 连接到：`127.0.0.1:5901`。
2. 密码：运行容器时设置的 `PASSWORD`。

### 方式二：浏览器（noVNC，推荐用于远程服务器）

1. 在浏览器中打开：`http://<服务器IP>:<NOVNC_PORT>/vnc.html`。此内置服务仅提供 HTTP，不要使用 `https://`；需要 HTTPS 时请在前面配置带证书的反向代理。
2. 输入运行容器时设置的 `PASSWORD`。
3. 点击 Connect 即可进入桌面。

> **远程服务器部署时推荐使用 noVNC。** 不需要开放 5901 或安装 VNC 客户端。请仅将 noVNC 绑定到受信任的私有接口，并通过防火墙、私有覆盖网络或支持 WebSocket 的 TLS 反向代理访问。

### noVNC 剪贴板

noVNC 将远程画面绘制在浏览器 Canvas 中，直接在画面里按 `Ctrl+V` 通常只会把按键事件发送到远程桌面，不会自动读取本机剪贴板。传递纯文本时：

1. 展开 noVNC 左侧工具栏并打开剪贴板面板。
2. 将本机文本粘贴到面板文本框中，然后点击文本框外触发发送。
3. 返回远程应用，按 `Ctrl+V` 粘贴。

也可以从 Docker 宿主机设置或读取远程剪贴板：

```bash
docker exec atrust-ubuntu set-vnc-clip.sh 'text to paste'
docker exec atrust-ubuntu get-vnc-clip.sh
```

VNC 剪贴板主要支持纯文本，中文、图片、文件和富文本不保证完整同步。

### 登录 aTrust

1. 桌面上会有三个图标：`aTrust`、`Chromium` 与 `Keep Alive`。
2. 双击 `aTrust`，按你的组织或服务端配置登录。
3. aTrust 需要网页认证时会自动拉起 Chromium 打开对应的认证页面。

> **请从桌面图标启动 `aTrust`。** 仓库内置的桌面入口会先补起 `aTrustDaemon`，再打开 `Tray`。如果你直接运行 `/usr/share/sangfor/aTrust/aTrustTray`，可能会看到 “The core service was started，causing some functions to be abnormal” 之类的提示。

> **不要依赖软件内的 `Restart Service` 按钮。** 这个容器不运行 `systemd`，而 `aTrust` 安装包默认尝试通过 `systemctl` 管理后台服务；因此在容器环境里，按钮本身不能作为可靠的恢复手段。正确做法是重新从桌面图标启动，或在容器内手动执行 `/usr/share/sangfor/aTrust/resources/shell/aTrustDaemon.sh start`。

如果你仍然需要手动复制 URL，优先检查：

- 运行容器时是否设置了 `-e CHROMIUM=1`。
- 是否使用了本仓库构建出来的新镜像（不要混用旧镜像）。

## 4. 通过容器代理访问 aTrust 内网

容器内 aTrust 建立连接后，会在宿主机暴露代理端口：

- **SOCKS5 代理**：`${SOCKS_BIND_ADDR:-127.0.0.1}:${SOCKS_PORT}`（默认 `127.0.0.1:1080`）。
- **HTTP 代理**：`${HTTP_BIND_ADDR:-127.0.0.1}:${HTTP_PORT}`（默认 `127.0.0.1:8888`）。

以下提供两种用法：需要按域名或网段分流多个应用时使用 Clash Verge；只需要 SSH 时，可以让 OpenSSH 直接使用 SOCKS5，不需要经过 Clash。

### 4.1 Clash Verge：添加全局扩展脚本

Clash Verge 的全局扩展脚本可以在订阅配置生效前追加代理节点和高优先级规则，适合把 aTrust 内网规则集中维护在一个脚本里。

打开 Clash Verge 的全局扩展脚本编辑器，加入类似下面的脚本：

```javascript
function main(config) {
  const atrustProxyName = "Docker-aTrust";
  const atrustProxy = {
    name: atrustProxyName,
    type: "socks5",
    server: "127.0.0.1",
    port: 1080,
    udp: true,
  };

  const atrustRules = [
    "DOMAIN-SUFFIX,internal.example.com,Docker-aTrust",
    "IP-CIDR,10.0.0.0/8,Docker-aTrust,no-resolve",
    "IP-CIDR,172.16.0.0/12,Docker-aTrust,no-resolve",
    "IP-CIDR,192.168.0.0/16,Docker-aTrust,no-resolve",
  ];

  config.proxies = (config.proxies || []).filter((proxy) => proxy.name !== atrustProxyName);
  config.proxies.unshift(atrustProxy);

  const oldRules = config.rules || [];
  config.rules = atrustRules.concat(oldRules.filter((rule) => !atrustRules.includes(rule)));

  return config;
}
```

### 4.2 Clash Verge：调整分流规则

请按你的实际环境修改脚本中的域名和内网网段：

- 域名规则：将 `internal.example.com` 替换成实际需要走 aTrust 的内网域名后缀。
- 网段规则：仅保留你的 aTrust 服务端实际下发或需要访问的内网网段。
- 规则顺序：脚本会把 `atrustRules` 放到订阅规则之前，因此这些内网规则会优先生效。
- 端口配置：如果运行容器时修改了 `SOCKS_PORT`，同步修改脚本里的 `port`。

提示：

- 内网域名经常依赖 aTrust 下发的"内网 DNS"才能解析。用 Clash Verge 将域名请求转发到 Docker 容器的 SOCKS5 代理后，解析过程更容易落在 aTrust 侧，避免宿主机本地 DNS 直接返回 `NXDOMAIN`。
- 即便 aTrust 已生效，容器内仍然可能可以访问外网域名，这通常是分流（Split Tunnel）的结果，并不必然代表 aTrust 没有接管流量。

### 4.3 不使用 Clash：OpenSSH 直接通过 SOCKS5 访问内网

如果只需要 SSH 访问内网，不需要安装或配置 Clash。可以直接在 OpenSSH 中使用 `ProxyCommand`，让 SSH 自动经过 Docker-aTrust 暴露的 SOCKS5 端口：

```text
当前客户端 -> <docker-host>:1080 -> aTrust 容器 -> <internal-host>:22
```

先在客户端验证 SOCKS5 端口和目标 SSH 服务：

```bash
nc -vz <docker-host> 1080
nc -v -w 5 -X 5 -x <docker-host>:1080 <internal-host> 22
```

成功时第二条命令会显示 `SSH-2.0-OpenSSH_...`。如果目标主机已经在客户端的 `~/.ssh/config` 中配置，只需在对应的 `Host` 配置块内增加一行：

```sshconfig
ProxyCommand /usr/bin/nc -X 5 -x <docker-host>:1080 %h %p
```

例如，Docker-aTrust 的宿主机地址是 `<docker-host>:1080`，内网 SSH 目标是 `<internal-host>:22`：

```sshconfig
Host atrust-internal
    HostName <internal-host>
    User <ssh-user>
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ProxyCommand /usr/bin/nc -X 5 -x <docker-host>:1080 %h %p
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

将 `<ssh-user>` 替换为内网目标服务器上的 SSH 用户名后，即可执行：

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/config
ssh atrust-internal
```

其中 `-X 5` 表示使用 SOCKS5，`-x` 后面是 Docker-aTrust 的 SOCKS5 地址，`%h` 和 `%p` 会由 OpenSSH 替换为当前配置块的 `HostName` 和 `Port`。`-x` 后只能跟一个 `主机:端口`，不要在地址前多写 `1`。

macOS 和安装了 OpenBSD `nc` 的 Linux 可使用上述 `ProxyCommand`。如果本机的 `nc` 不支持 `-X/-x`，可安装 Nmap `ncat` 并改用：

```sshconfig
ProxyCommand ncat --proxy <docker-host>:1080 --proxy-type socks5 %h %p
```

> 上述 OpenBSD `nc` 示例按无认证 SOCKS5 编写。远程客户端需要确保容器的 `1080` 端口已绑定到该客户端可访问的宿主机接口，而不只是 `127.0.0.1`。不要把 `1080` 暴露到公网；应使用防火墙限制来源地址，或仅通过可信局域网、SSH 隧道及私有覆盖网络访问。如果必须启用认证，可在 `.env` 中同时设置 `SOCKS_USER` 和 `SOCKS_PASSWD`，并使用支持 SOCKS5 认证的客户端，例如 `ncat --proxy-auth <proxy-user>:<proxy-password>`；不要把真实凭据提交到仓库或可被其他用户读取的 SSH 配置中。

## 5. 保活程序（Keep Alive）

本仓库在容器内新增了一个保活程序，通过真实网络探测和键鼠活动防止系统因长时间空闲而断开连接或判定为不活跃。

### 5.1 功能说明

保活程序包含以下功能：

- **网络保活探测**：ICMP、直连 TCP 和 HTTP GET 可独立配置并同时运行，不依赖 SOCKS5。
- **空闲活动保活**：检测 X11 空闲时间，达到阈值后执行鼠标往返和两次 Scroll Lock 切换。

### 5.2 使用方式

保活程序首次使用时需要手动启动；启动状态写入持久化配置，之后重新启动容器会自动恢复：

1. 通过 VNC 连接到桌面。
2. 双击桌面上的 `Keep Alive` 图标，打开设置界面。
3. 在设置界面中配置参数：
   - **ICMP/TCP/HTTP 标签页**：分别设置启用状态、目标、间隔、超时和每轮次数。
   - **并行运行**：可同时启用任意多个网络保活模块，各自按独立周期运行。
   - **空闲活动保活**：独立设置空闲阈值和检查周期，鼠标与 Scroll Lock 动作可分别启用。
4. 点击 **"保存配置"** 保存设置。
5. 点击 **"▶ 启动"** 启动守护进程（状态栏会显示运行状态和 PID）。
6. 需要停止时点击 **"■ 停止"**。

> 配置文件存储在 `/root/.keep-alive/config.json`。点击启动后，配置和启用状态会随 `/root` volume 持久化；点击停止会同时关闭自动恢复。

三类网络保活分别配置：

| 目标格式 | 探测方式 | 示例 |
| --- | --- | --- |
| IP 或域名 | ICMP Ping | `10.0.0.1` |
| `主机:端口` 或 `tcp://主机:端口` | 直连 TCP | `internal.example.com:22` |
| `http://` 或 `https://` URL | 不使用代理的 HTTP GET | `https://intranet.example/health` |

对于禁用 ICMP 的内网资源，应使用实际开放的 TCP 端口或 HTTP URL。目标必须按容器路由进入 aTrust；日志中的 `OK` 只表示目标可达，是否形成 aTrust 业务流量可结合 `/root/.aTrust/logs/xtunnel/tcpAccess.log` 检查。

### 5.3 命令行操作

也可以在容器内通过命令行管理保活程序：

```bash
# 启动守护进程
docker exec -e DISPLAY=:1 atrust-ubuntu python3 /usr/local/bin/keep-alive.py --start

# 停止守护进程
docker exec atrust-ubuntu python3 /usr/local/bin/keep-alive.py --stop

# 查看运行状态
docker exec atrust-ubuntu python3 /usr/local/bin/keep-alive.py --status

# 查看日志
docker exec atrust-ubuntu tail -n 50 /root/.keep-alive/daemon.log

# 编辑配置（JSON 格式）
docker exec atrust-ubuntu cat /root/.keep-alive/config.json
```

### 5.4 配置示例

`/root/.keep-alive/config.json` 的默认结构：

```json
{
  "enabled": false,
  "icmp": {
    "enabled": false,
    "targets": [],
    "interval": 30,
    "timeout": 3,
    "count": 1
  },
  "tcp": {
    "enabled": true,
    "targets": ["internal.example.com:22"],
    "interval": 30,
    "timeout": 3,
    "count": 1
  },
  "http": {
    "enabled": false,
    "targets": [],
    "interval": 30,
    "timeout": 3,
    "count": 1,
    "verify_tls": true
  },
  "activity": {
    "enabled": true,
    "idle_threshold": 4500,
    "trigger_margin": 60,
    "check_interval": 1800,
    "mouse_enabled": true,
    "dx": 1,
    "dy": 0,
    "return_to_origin": true,
    "mouse_delay_ms": 50,
    "keyboard_enabled": true,
    "key": "Scroll_Lock",
    "key_repeats": 2,
    "key_delay_ms": 30
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `icmp.enabled` / `tcp.enabled` / `http.enabled` | 分别启用三类网络保活，可同时为 `true` |
| `icmp.targets` | ICMP 目标列表，每项为 IP 或域名 |
| `tcp.targets` | TCP 目标列表，每项为 `主机:端口` 或 `tcp://主机:端口` |
| `http.targets` | HTTP(S) URL 列表，每项执行真实 GET |
| `*.interval` | 对应模块的独立探测间隔秒数（最小 5） |
| `*.timeout` | 对应模块的单次探测超时秒数 |
| `*.count` | 对应模块每轮对每个目标执行的次数 |
| `http.verify_tls` | HTTPS GET 是否验证服务器证书 |
| `activity.enabled` | 是否启用基于 X11 空闲时间的活动保活 |
| `activity.idle_threshold` | 触发活动的空闲秒数；默认 `4500`（75 分钟） |
| `activity.trigger_margin` | 在空闲阈值前多少秒触发；默认 60 秒，即第 74 分钟触发 |
| `activity.check_interval` | 最大检查间隔秒数；默认 `1800`，接近阈值时会按剩余时间提前唤醒 |
| `activity.mouse_enabled` | 达到阈值后是否执行鼠标往返 |
| `activity.dx/dy` | 鼠标相对偏移像素；默认 `(1,0)` |
| `activity.mouse_delay_ms` | 鼠标移出后等待多久再返回；默认 50 ms |
| `activity.keyboard_enabled` | 达到阈值后是否执行键盘动作 |
| `activity.key` / `activity.key_repeats` | 默认将 `Scroll_Lock` 按下/释放两轮，使锁定状态恢复原值 |
| `activity.key_delay_ms` | 每次按下或释放后的等待时间；默认 30 ms |

默认活动逻辑基于已验证的 AutoHotkey 脚本，并增加了阈值前保证：平时最多每 30 分钟检查一次，接近阈值时自动按剩余时间唤醒；在 X11 空闲达到 74 分钟时，鼠标向右移动 1 像素，50 ms 后返回，再将 Scroll Lock 按下/释放两轮。守护进程还会禁用 X11 屏保、黑屏和 DPMS；VNC/noVNC 客户端不需要保持连接。

### 5.5 不中断容器的热更新

维护窗口前不方便重建容器时，可以只替换 Keep Alive 脚本。该操作不会重启 aTrust、VNC、noVNC 或代理服务，但会短暂停止 Keep Alive 自身守护进程：

```bash
docker exec atrust-ubuntu python3 /usr/local/bin/keep-alive.py --stop
docker cp keep-alive/keep-alive.py atrust-ubuntu:/usr/local/bin/keep-alive.py
docker cp keep-alive/keep-alive-gui.py atrust-ubuntu:/usr/local/bin/keep-alive-gui.py
docker cp docker-root/usr/local/bin/start.sh atrust-ubuntu:/usr/local/bin/start.sh
docker exec atrust-ubuntu chmod 0755 \
  /usr/local/bin/keep-alive.py \
  /usr/local/bin/keep-alive-gui.py \
  /usr/local/bin/keep-alive-launcher \
  /usr/local/bin/start.sh
docker exec atrust-ubuntu python3 -m py_compile \
  /usr/local/bin/keep-alive.py \
  /usr/local/bin/keep-alive-gui.py
docker exec atrust-ubuntu bash -n /usr/local/bin/start.sh
docker exec -e DISPLAY=:1 atrust-ubuntu \
  python3 /usr/local/bin/keep-alive.py --start
```

关闭并重新打开 Keep Alive 窗口即可载入新代码。也可以直接启动 GUI：

```bash
docker exec -d -e DISPLAY=:1 atrust-ubuntu /usr/local/bin/keep-alive-launcher
```

容器内修改会在重新创建容器时丢失，因此后续仍应重新构建镜像。

## 6. 常见问题与自检

### 6.1 Chromium 点击就闪退

优先确认运行参数包含 `--shm-size=512m`。其次确认你是通过桌面图标或 `chromium-launcher` 启动（本仓库已统一加上 `--no-sandbox` 与 `--disable-dev-shm-usage`）。

### 6.2 aTrust 已登录但访问不了内网域名

先在容器内检查域名解析是否走到内网 DNS：

```bash
docker exec atrust-ubuntu getent hosts service.internal.example.com
```

再确认 aTrust 的 TUN 与策略是否正常：

```bash
docker exec atrust-ubuntu ip route
docker exec atrust-ubuntu sysctl -n net.ipv4.conf.utun7.route_localnet
```

如果 `net.ipv4.conf.utun7.route_localnet` 不是 `1`，几乎可以确定你运行容器时没有加：

- `--sysctl net.ipv4.conf.default.route_localnet=1`。

### 6.3 桌面图标偶尔消失

当你把宿主机目录挂载到 `/root` 时，某些环境下 `~/.cache` 不支持 Unix socket，导致桌面管理器启动失败。本仓库已将 `pcmanfm` 的缓存与运行目录指向 `/tmp`，并做了延迟重试。

你可以用下面命令查看 `pcmanfm` 日志：

```bash
docker exec atrust-ubuntu tail -n 200 /tmp/pcmanfm-desktop.log
```

### 6.4 `8888` 代理不可用导致容器退出

`8888` 是必选代理端口。容器启动时会严格检查 tinyproxy，运行中若 tinyproxy 进程消失或 `8888` 不再监听，容器会主动退出，避免出现"VPN 在线但 HTTP 代理已失效"的假健康状态。

可用以下命令排障：

```bash
docker logs --tail 200 atrust-ubuntu
docker exec atrust-ubuntu ss -lntp | grep ':8888'
docker exec atrust-ubuntu tail -n 200 /var/log/tinyproxy/tinyproxy.log
```

### 6.5 Windows 上 `/dev/net/tun` 不存在

Docker Desktop for Windows 使用 Linux VM 运行容器，`/dev/net/tun` 在 VM 内自动可用。如果报错，确认 Docker Desktop 已启用 WSL 2 后端或 Hyper-V 后端。

### 6.6 noVNC 一直停在加载页面

先检查 JavaScript 模块的响应类型：

```bash
curl -sSI http://<docker-host>:<novnc-port>/app/ui.js
curl -sSI http://<docker-host>:<novnc-port>/app/error-handler.js
```

两个响应都应包含 `Content-Type: application/javascript`。容器日志还应出现：

```text
noVNC MIME override active: .js/.mjs -> application/javascript
```

如果日志没有该标记，说明容器仍在使用旧镜像；重新构建镜像并使用 `docker compose up -d --force-recreate` 创建容器。响应头正确但浏览器仍报旧 MIME 错误时，请清除站点缓存或使用无痕窗口。

`No SSL/TLS support (no cert file)` 是 HTTP 模式的正常提示。直接用 `https://` 访问会产生 `SSL connection but '/self.pem' not found`；需要 HTTPS 时应在 noVNC 前配置支持 WebSocket 的 TLS 反向代理。

### 6.7 Keep Alive 桌面入口无效或启动失败

如果 PCManFM 报 `Invalid desktop entry file`，先检查入口和 launcher 权限：

```bash
docker exec atrust-ubuntu sh -c '
ls -l /root/Desktop/KeepAlive.desktop /usr/local/bin/keep-alive-launcher
test -x /usr/local/bin/keep-alive-launcher
'
```

launcher 必须可执行；旧镜像可临时修复：

```bash
docker exec atrust-ubuntu chmod 0755 /usr/local/bin/keep-alive-launcher
docker exec atrust-ubuntu touch /root/Desktop/KeepAlive.desktop
```

如果界面显示 `init() got an unexpected keyword argument 'capture_output'`，说明旧版脚本使用了 Python 3.7 才支持的参数，而 Ubuntu 18.04 默认是 Python 3.6。请使用当前镜像，或按 5.5 节热更新两个 Keep Alive 脚本。

## 免责声明

aTrust 为 Sangfor 的商业软件。本仓库仅提供容器化与运行环境的配置与脚本示例，不对 aTrust 软件本体作任何修改或分发承诺。请确保你的使用符合相关许可与合规要求。
