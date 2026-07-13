中文 | [**English**](README.en.md)

# Docker-aTrust（Ubuntu GUI + Chromium）

本仓库基于 [docker-easyconnect](https://github.com/docker-easyconnect/docker-easyconnect) 开发，构建一个带图形界面的 Ubuntu 容器，在容器内安装并运行图形界面版 aTrust，并将默认浏览器与 aTrust 的跳转浏览器统一设为 Chromium，便于完成 aTrust 浏览器登录页面的跳转。

容器同时提供：

- VNC 桌面（端口 `5901`，密码固定为 `password`）。
- SOCKS5 代理（默认端口 `1080`，推荐用于 Clash Verge 分流）。
- HTTP 代理（默认端口 `8888`，必选）。
- aTrust 本地 Web 登录端口（端口 `54631`，用于 aTrust 拉起浏览器的登录流程）。

> **端口可自定义。** SOCKS5 和 HTTP 代理的宿主机端口可通过环境变量 `SOCKS_PORT` 和 `HTTP_PORT` 调整（参见[运行容器](#2-运行容器)），容器内服务始终监听 `1080` / `8888`。

> **外网代理与本仓库无关。** 如果你同时使用公网代理工具（如 Clash Verge，默认监听 `7897`），可通过 Clash Verge 全局扩展脚本将内网流量指向 Docker 容器代理，并让其他流量继续按原订阅或公网代理规则处理。本仓库不涉及外网代理配置。

## 0. 前置条件

- 已安装 Docker Desktop（macOS / Windows）或 Docker Engine（Linux）。
- 已安装任意 VNC 客户端（macOS 可用系统自带"屏幕共享"；Windows 可用 RealVNC / TightVNC；Linux 可用 TigerVNC Viewer / Remmina）。
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
  $(cat build-args/atrust-arm64.txt) \
  --build-arg CHROMIUM=1 \
  .
```

### 1.2 Intel / AMD（amd64 / x86_64）

```bash
cd Docker-aTrust
docker build -t atrust-ubuntu:chromium \
  --platform linux/amd64 \
  -f Dockerfile.ubuntu \
  $(cat build-args/atrust-amd64.txt) \
  --build-arg CHROMIUM=1 \
  .
```

说明：

- `--build-arg CHROMIUM=1` 用于在镜像内安装 Chromium。
- `build-args/` 下也提供了多个版本的 aTrust build args，你可以按需替换。

## 2. 运行容器

### 端口配置

宿主机暴露的 SOCKS5 和 HTTP 代理端口可通过环境变量自定义（默认 `1080` / `8888`）：

```bash
# 可选：自定义端口（默认值如下，无需修改即可直接使用）
export SOCKS_PORT=${SOCKS_PORT:-1080}
export HTTP_PORT=${HTTP_PORT:-8888}
```

### 启动命令

```bash
docker run -d --name atrust-ubuntu \
  --device /dev/net/tun \
  --cap-add NET_ADMIN \
  --sysctl net.ipv4.conf.default.route_localnet=1 \
  --shm-size=512m \
  -e PASSWORD=password \
  -e CHROMIUM=1 \
  -e URLWIN=1 \
  -p 5901:5901 \
  -p ${SOCKS_PORT:-1080}:1080 \
  -p ${HTTP_PORT:-8888}:8888 \
  -p 54631:54631 \
  -v $HOME/.atrust-data:/root \
  atrust-ubuntu:chromium
```

<details>
<summary>Windows PowerShell 版本</summary>

```powershell
docker run -d --name atrust-ubuntu `
  --device /dev/net/tun `
  --cap-add NET_ADMIN `
  --sysctl net.ipv4.conf.default.route_localnet=1 `
  --shm-size=512m `
  -e PASSWORD=password `
  -e CHROMIUM=1 `
  -e URLWIN=1 `
  -p 5901:5901 `
  -p "${env:SOCKS_PORT ?? 1080}:1080" `
  -p "${env:HTTP_PORT ?? 8888}:8888" `
  -p 54631:54631 `
  -v "$env:USERPROFILE\.atrust-data:/root" `
  atrust-ubuntu:chromium
```

> PowerShell 不支持 `${VAR:-default}` 语法，可在运行前手动设置 `$env:SOCKS_PORT = "1080"` 等，或直接硬编码端口号。

</details>

关键点解释：

- `--device /dev/net/tun` + `--cap-add NET_ADMIN`：aTrust 需要创建并配置 TUN 设备。
- `--sysctl net.ipv4.conf.default.route_localnet=1`：用于让 aTrust 的 DNS 分流生效（Docker Desktop 下无法在容器内可靠设置该 sysctl，必须在 `docker run` 时传入）。
- `--shm-size=512m`：避免 Chromium 因 `/dev/shm` 过小而"闪退"。
- `-e PASSWORD=password`：固定 VNC 密码为 `password`（你也可以自行改成别的值，但本仓库默认建议固定为 `password`）。
- `-e CHROMIUM=1`：启用容器内 Chromium 自动拉起与跳转处理（包括 aTrust 的登录跳转）。
- `-e URLWIN=1`：当 aTrust 试图打开 URL 时，额外弹窗提示并把 URL 写入剪贴板（排障时很有用）。
- `-v $HOME/.atrust-data:/root`：持久化 `/root`（包括 aTrust 登录信息、Chromium 配置等）。
- `-p ${HTTP_PORT:-8888}:8888`：`8888` 为必选 HTTP 代理端口，若 tinyproxy 启动失败或运行中丢失监听，容器会退出。

## 3. 通过 VNC 打开桌面并登录 aTrust

1. 使用 VNC 连接到：`127.0.0.1:5901`。
2. 密码：`password`。
3. 桌面上会有三个图标：`aTrust`、`Chromium` 与 `Keep Alive`。
4. 双击 `aTrust`，按你的组织或服务端配置登录。
5. aTrust 需要网页认证时会自动拉起 Chromium 打开对应的认证页面。

> **请从桌面图标启动 `aTrust`。** 仓库内置的桌面入口会先补起 `aTrustDaemon`，再打开 `Tray`。如果你直接运行 `/usr/share/sangfor/aTrust/aTrustTray`，可能会看到 “The core service was started，causing some functions to be abnormal” 之类的提示。

> **不要依赖软件内的 `Restart Service` 按钮。** 这个容器不运行 `systemd`，而 `aTrust` 安装包默认尝试通过 `systemctl` 管理后台服务；因此在容器环境里，按钮本身不能作为可靠的恢复手段。正确做法是重新从桌面图标启动，或在容器内手动执行 `/usr/share/sangfor/aTrust/resources/shell/aTrustDaemon.sh start`。

如果你仍然需要手动复制 URL，优先检查：

- 运行容器时是否设置了 `-e CHROMIUM=1`。
- 是否使用了本仓库构建出来的新镜像（不要混用旧镜像）。

## 4. 在宿主机使用 Clash Verge 做分流（推荐）

容器内 aTrust 建立连接后，会在宿主机暴露代理端口：

- **SOCKS5 代理**：`127.0.0.1:${SOCKS_PORT}`（默认 `1080`）。
- **HTTP 代理**：`127.0.0.1:${HTTP_PORT}`（默认 `8888`）。

### 4.1 添加全局扩展脚本

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

### 4.2 调整分流规则

请按你的实际环境修改脚本中的域名和内网网段：

- 域名规则：将 `internal.example.com` 替换成实际需要走 aTrust 的内网域名后缀。
- 网段规则：仅保留你的 aTrust 服务端实际下发或需要访问的内网网段。
- 规则顺序：脚本会把 `atrustRules` 放到订阅规则之前，因此这些内网规则会优先生效。
- 端口配置：如果运行容器时修改了 `SOCKS_PORT`，同步修改脚本里的 `port`。

提示：

- 内网域名经常依赖 aTrust 下发的"内网 DNS"才能解析。用 Clash Verge 将域名请求转发到 Docker 容器的 SOCKS5 代理后，解析过程更容易落在 aTrust 侧，避免宿主机本地 DNS 直接返回 `NXDOMAIN`。
- 即便 aTrust 已生效，容器内仍然可能可以访问外网域名，这通常是分流（Split Tunnel）的结果，并不必然代表 aTrust 没有接管流量。

## 5. 保活程序（Keep Alive）

本仓库在容器内新增了一个保活程序，用于防止系统因长时间空闲而断开连接或判定为不活跃。

### 5.1 功能说明

保活程序包含以下功能：

- **定时 ICMP Ping**：按配置的间隔，向指定服务器发送 ICMP 包（支持多个目标地址）。
- **鼠标微操作**：定时将鼠标移动若干像素后返回原位，模拟微小活动。
- **键盘微操作**：定时按下指定按键（如 `shift`、`ctrl`），不产生实际输入。

### 5.2 使用方式

保活程序**不会自动启动**，需要手动操作：

1. 通过 VNC 连接到桌面。
2. 双击桌面上的 `Keep Alive` 图标，打开设置界面。
3. 在设置界面中配置参数：
   - **Ping 目标**：填写需要保活的目标 IP 或域名（每行一个）。
   - **Ping 间隔**：发送 ping 的频率（默认 30 秒）。
   - **鼠标/键盘操作**：可单独启用或禁用，可调整间隔和幅度。
4. 点击 **"保存配置"** 保存设置。
5. 点击 **"▶ 启动"** 启动守护进程（状态栏会显示运行状态和 PID）。
6. 需要停止时点击 **"■ 停止"**。

> 配置文件存储在 `/root/.keep-alive/config.json`，由于 `/root` 目录通过 Docker volume 挂载持久化，重启容器后配置会自动保留，但守护进程仍需手动启动。

### 5.3 命令行操作

也可以在容器内通过命令行管理保活程序：

```bash
# 启动守护进程
docker exec atrust-ubuntu python3 /usr/local/bin/keep-alive.py --start

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
  "ping": {
    "targets": [],
    "interval": 30,
    "timeout": 3,
    "count": 1
  },
  "mouse": {
    "enabled": true,
    "interval": 60,
    "dx": 1,
    "dy": 1,
    "return_to_origin": true
  },
  "keyboard": {
    "enabled": true,
    "interval": 120,
    "keys": ["shift"]
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `ping.targets` | Ping 目标列表，每项为 IP 或域名 |
| `ping.interval` | Ping 间隔秒数（最小 5） |
| `ping.timeout` | 单次 Ping 超时秒数 |
| `ping.count` | 每次 Ping 发送的包数 |
| `mouse.enabled` | 是否启用鼠标微移动 |
| `mouse.interval` | 鼠标操作间隔秒数 |
| `mouse.dx/dy` | 鼠标偏移像素数 |
| `mouse.return_to_origin` | 移动后是否返回原位 |
| `keyboard.enabled` | 是否启用键盘微操作 |
| `keyboard.interval` | 键盘操作间隔秒数 |
| `keyboard.keys` | 按键名称列表（如 `shift`、`ctrl`、`alt`） |

## 6. 常见问题与自检

### 6.1 Chromium 点击就闪退

优先确认运行参数包含 `--shm-size=512m`。其次确认你是通过桌面图标或 `chromium-launcher` 启动（本仓库已统一加上 `--no-sandbox` 与 `--disable-dev-shm-usage`）。

### 6.2 aTrust 已登录但访问不了内网域名

先在容器内检查域名解析是否走到内网 DNS：

```bash
docker exec atrust-ubuntu dig service.internal.example.com +short
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

## 免责声明

aTrust 为 Sangfor 的商业软件。本仓库仅提供容器化与运行环境的配置与脚本示例，不对 aTrust 软件本体作任何修改或分发承诺。请确保你的使用符合相关许可与合规要求。
