# Docker-aTrust (Ubuntu GUI + Chromium)

[**中文文档**](README.md) | English

This repository is based on [docker-easyconnect](https://github.com/docker-easyconnect/docker-easyconnect). It builds an Ubuntu container with a graphical desktop, installs and runs the GUI version of aTrust inside the container, and unifies the default browser and aTrust's redirect browser to Chromium for seamless web-based login flow.

The container provides:

- VNC desktop (port `5901`, password `password`).
- noVNC web access (port `8080`, open in browser directly).
- SOCKS5 proxy (default port `1080`, recommended for Clash Verge routing).
- HTTP proxy (default port `8888`, mandatory).
- aTrust local web login port (`54631`, used for aTrust's browser login redirect).

> **Ports are customizable.** Host-side SOCKS5 and HTTP proxy ports can be adjusted via `SOCKS_PORT` and `HTTP_PORT` environment variables (see [Running the Container](#2-running-the-container)). Services inside the container always listen on `1080` / `8888`.

> **Public internet proxies are unrelated to this repo.** If you also use a public proxy tool (for example, Clash Verge on its default `7897` port), use a Clash Verge global extension script to route internal traffic to the Docker container proxy and leave other traffic to your existing subscription or public proxy rules. This repo does not manage public proxy configuration.

## 0. Prerequisites

- Docker Desktop (macOS / Windows) or Docker Engine (Linux) installed.
- (Optional) A VNC client installed (macOS: built-in "Screen Sharing"; Windows: RealVNC / TightVNC; Linux: TigerVNC Viewer / Remmina). You can also use noVNC directly in a browser.
- (Optional) Clash Verge installed for host-side traffic routing.

### Platform Notes

| Platform    | Notes                                                                                                                                                                                                                                                                                                                                                              |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **macOS**   | Docker Desktop + built-in "Screen Sharing". Build commands below.                                                                                                                                                                                                                                                                                                  |
| **Windows** | Docker Desktop for Windows + VNC client. Use `` ` `` for line continuation instead of `\` in PowerShell; replace `$HOME` with `$env:USERPROFILE`.                                                                                                                                                                                                                  |
| **Linux**   | Docker Engine + VNC client. Commands are the same as macOS. Ensure `/dev/net/tun` device exists.                                                                                                                                                                                                                                                                   |
| **WSL 2**   | **Recommended: run the container on the Windows host, not inside WSL.** With WSL 2 [Mirrored Networking](https://learn.microsoft.com/en-us/windows/wsl/networking#mirrored-mode-networking) enabled, processes inside WSL can access Windows-side proxy ports via `127.0.0.1`, and Clash Verge on Windows manages all routing — no separate WSL proxy config needed. |

## 1. Building the Image

This repo includes aTrust installer download URLs (Sangfor CDN) as build args. Choose the file matching your target architecture.

### 1.1 Apple Silicon (recommended: arm64)

```bash
cd Docker-aTrust
docker build -t atrust-ubuntu:chromium \
  -f Dockerfile.ubuntu \
  $(cat build-args/atrust-arm64.txt) \
  --build-arg CHROMIUM=1 \
  .
```

### 1.2 Intel / AMD (amd64 / x86_64)

```bash
cd Docker-aTrust
docker build -t atrust-ubuntu:chromium \
  --platform linux/amd64 \
  -f Dockerfile.ubuntu \
  $(cat build-args/atrust-amd64.txt) \
  --build-arg CHROMIUM=1 \
  .
```

Notes:

- `--build-arg CHROMIUM=1` installs Chromium inside the image.
- `build-args/` contains multiple aTrust versions — swap as needed.

## 2. Running the Container

### Port Configuration

Host-exposed SOCKS5 and HTTP proxy ports can be customized (defaults: `1080` / `8888`):

```bash
# Optional: customize ports (defaults shown below, no change needed for standard usage)
export SOCKS_PORT=${SOCKS_PORT:-1080}
export HTTP_PORT=${HTTP_PORT:-8888}
```

### Start Command

```bash
docker run -d --name atrust-ubuntu \
  --device /dev/net/tun \
  --cap-add NET_ADMIN \
  --sysctl net.ipv4.conf.default.route_localnet=1 \
  --shm-size=512m \
  -e PASSWORD=password \
  -e CHROMIUM=1 \
  -e URLWIN=1 \
  -e USE_NOVNC=1 \
  -p 8080:8080 \
  -p 5901:5901 \
  -p ${SOCKS_PORT:-1080}:1080 \
  -p ${HTTP_PORT:-8888}:8888 \
  -p 54631:54631 \
  -v $HOME/.atrust-data:/root \
  atrust-ubuntu:chromium
```

<details>
<summary>Windows PowerShell version</summary>

```powershell
docker run -d --name atrust-ubuntu `
  --device /dev/net/tun `
  --cap-add NET_ADMIN `
  --sysctl net.ipv4.conf.default.route_localnet=1 `
  --shm-size=512m `
  -e PASSWORD=password `
  -e CHROMIUM=1 `
  -e URLWIN=1 `
  -e USE_NOVNC=1 `
  -p 8080:8080 `
  -p 5901:5901 `
  -p "${env:SOCKS_PORT ?? 1080}:1080" `
  -p "${env:HTTP_PORT ?? 8888}:8888" `
  -p 54631:54631 `
  -v "$env:USERPROFILE\.atrust-data:/root" `
  atrust-ubuntu:chromium
```

> PowerShell does not support `${VAR:-default}` syntax. Set `$env:SOCKS_PORT = "1080"` manually before running, or hardcode the port numbers.

</details>

Key parameters explained:

- `--device /dev/net/tun` + `--cap-add NET_ADMIN`: aTrust requires TUN device creation.
- `--sysctl net.ipv4.conf.default.route_localnet=1`: enables aTrust DNS routing (cannot be reliably set inside the container on Docker Desktop).
- `--shm-size=512m`: prevents Chromium crashes due to small `/dev/shm`.
- `-e PASSWORD=password`: fixed VNC password (change if desired, but `password` is the default).
- `-e CHROMIUM=1`: enables automatic Chromium launch for aTrust login redirects.
- `-e URLWIN=1`: shows URL popup and copies to clipboard when aTrust opens a URL (useful for debugging).
- `-e USE_NOVNC=1`: enables noVNC — access the VNC desktop via browser at `http://<server-ip>:8080`.
- `-p 8080:8080`: noVNC web port (only needed when `USE_NOVNC` is enabled).
- `-v $HOME/.atrust-data:/root`: persists `/root` (aTrust login data, Chromium config, etc.).
- `-p ${HTTP_PORT:-8888}:8888`: `8888` is the mandatory HTTP proxy port. If tinyproxy fails or stops listening, the container exits.

## 3. VNC / noVNC Desktop Login

### Option A: VNC Client

1. Connect VNC to `127.0.0.1:5901`.
2. Password: `password`.

### Option B: Browser (noVNC, recommended for remote servers)

1. Open `http://<server-ip>:8080` in your browser.
2. Enter password: `password`.
3. Click Connect to enter the desktop.

> **noVNC is recommended for remote server deployments.** No need to open port 5901 or install a VNC client — just open port 8080 for browser access.

### Log into aTrust

1. Three desktop icons: `aTrust`, `Chromium`, and `Keep Alive`.
2. Double-click `aTrust`, log in per your organization's config.
3. aTrust will auto-launch Chromium for the corresponding web authentication pages.

If you still need to manually copy the URL, check:

- Container was started with `-e CHROMIUM=1`.
- You're using the image built from this repo (don't mix with old images).

## 4. Accessing the aTrust Network Through the Container Proxy

After aTrust connects inside the container, proxy ports are exposed on the host:

- **SOCKS5**: `127.0.0.1:${SOCKS_PORT}` (default `1080`).
- **HTTP**: `127.0.0.1:${HTTP_PORT}` (default `8888`).

Two approaches are documented below: use Clash Verge to route multiple applications by domain or network range, or configure OpenSSH to use SOCKS5 directly when only SSH access is needed.

### 4.1 Clash Verge: Add a Global Extension Script

Clash Verge global extension scripts can add proxy nodes and high-priority rules before the subscription rules take effect, which makes them a good place to keep aTrust internal routing rules.

Open the Clash Verge global extension script editor and add a script like this:

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

### 4.2 Clash Verge: Adjust Routing Rules

Adjust the example domains and internal network ranges for your environment:

- Domain rules: replace `internal.example.com` with the internal domain suffix that should go through aTrust.
- Network rules: keep only the internal CIDR ranges that your aTrust server assigns or that you need to access.
- Rule order: the script prepends `atrustRules` before subscription rules, so these internal rules take priority.
- Port configuration: if you changed `SOCKS_PORT` when starting the container, update `port` in the script as well.

Tips:

- Internal domains often require aTrust's internal DNS. Routing domain requests to the Docker container SOCKS5 proxy through Clash Verge makes resolution more likely to happen on the aTrust side, avoiding local-host `NXDOMAIN` responses.
- aTrust containers may still access public internet domains — this is typically split-tunnel behavior and doesn't mean aTrust isn't working.

### 4.3 Without Clash: OpenSSH Directly Through SOCKS5

If SSH is the only required internal service, Clash is not needed. Configure OpenSSH with `ProxyCommand` so that it connects through the SOCKS5 port published by Docker-aTrust:

```text
client -> <docker-host>:1080 -> aTrust container -> <internal-host>:22
```

Verify the SOCKS5 port and target SSH service from the client first:

```bash
nc -vz <docker-host> 1080
nc -v -w 5 -X 5 -x <docker-host>:1080 <internal-host> 22
```

The second command should print an `SSH-2.0-OpenSSH_...` banner. If the target is already defined in the client's `~/.ssh/config`, add only this line to its existing `Host` block:

```sshconfig
ProxyCommand /usr/bin/nc -X 5 -x <docker-host>:1080 %h %p
```

Complete configuration example:

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

Replace `<docker-host>`, `<internal-host>`, and `<ssh-user>` with the actual values, then run:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/config
ssh atrust-internal
```

Here, `-X 5` selects SOCKS5, `-x` specifies the Docker-aTrust SOCKS5 endpoint, and OpenSSH replaces `%h` and `%p` with the `HostName` and `Port` from the current block. The argument after `-x` must be one `host:port` value; do not insert extra arguments before the address.

The example works with macOS and Linux systems using OpenBSD `nc`. If local `nc` does not support `-X/-x`, install Nmap `ncat` and use:

```sshconfig
ProxyCommand ncat --proxy <docker-host>:1080 --proxy-type socks5 %h %p
```

> The OpenBSD `nc` example above assumes SOCKS5 without authentication. A remote client also requires port `1080` to be bound to a host interface reachable by that client, not only to `127.0.0.1`. Do not expose port `1080` to the public internet. Restrict source addresses with a firewall, or access it only through a trusted LAN, SSH tunnel, or private overlay network.

## 5. Keep Alive Program

This repo adds a keep-alive program inside the container to prevent the system from disconnecting or marking the session as idle.

### 5.1 Features

The keep-alive program provides:

- **Periodic ICMP Ping**: Sends ICMP packets to specified servers at configurable intervals (supports multiple targets).
- **Mouse Micro-operations**: Periodically moves the mouse a few pixels and returns it to the original position, simulating minor activity.
- **Keyboard Micro-operations**: Periodically presses specified keys (e.g., `shift`, `ctrl`) without producing actual input.

### 5.2 Usage

The keep-alive program **does not start automatically** — it requires manual activation:

1. Connect to the desktop via VNC.
2. Double-click the `Keep Alive` desktop icon to open the settings GUI.
3. Configure parameters in the settings window:
   - **Ping targets**: Enter IP addresses or domain names (one per line).
   - **Ping interval**: Frequency of ping requests (default 30 seconds).
   - **Mouse / Keyboard operations**: Enable/disable individually; adjust intervals and parameters.
4. Click **"Save Config"** to save settings.
5. Click **"▶ Start"** to launch the daemon (status bar shows running state and PID).
6. Click **"■ Stop"** to stop the daemon.

> Configuration is stored in `/root/.keep-alive/config.json`. Since `/root` is mounted as a Docker volume for persistence, your settings survive container restarts — but the daemon still needs to be started manually each time.

### 5.3 Command-Line Management

You can also manage the keep-alive program from the command line:

```bash
# Start the daemon
docker exec atrust-ubuntu python3 /usr/local/bin/keep-alive.py --start

# Stop the daemon
docker exec atrust-ubuntu python3 /usr/local/bin/keep-alive.py --stop

# Check status
docker exec atrust-ubuntu python3 /usr/local/bin/keep-alive.py --status

# View logs
docker exec atrust-ubuntu tail -n 50 /root/.keep-alive/daemon.log

# Edit configuration (JSON format)
docker exec atrust-ubuntu cat /root/.keep-alive/config.json
```

### 5.4 Configuration Reference

Default structure of `/root/.keep-alive/config.json`:

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

| Field | Description |
| --- | --- |
| `ping.targets` | List of ping targets (IP or domain name) |
| `ping.interval` | Ping interval in seconds (minimum 5) |
| `ping.timeout` | Single ping timeout in seconds |
| `ping.count` | Number of packets per ping |
| `mouse.enabled` | Enable/disable mouse micro-movement |
| `mouse.interval` | Mouse operation interval in seconds |
| `mouse.dx/dy` | Mouse offset in pixels |
| `mouse.return_to_origin` | Return mouse to original position after move |
| `keyboard.enabled` | Enable/disable keyboard micro-operations |
| `keyboard.interval` | Keyboard operation interval in seconds |
| `keyboard.keys` | Key names list (e.g., `shift`, `ctrl`, `alt`) |

## 6. Troubleshooting

### 6.1 Chromium Crashes on Click

Ensure `--shm-size=512m` is in your run command. Use the desktop icon or `chromium-launcher` (this repo adds `--no-sandbox` and `--disable-dev-shm-usage`).

### 6.2 aTrust Connected but Can't Access an Internal Domain

Check DNS resolution inside the container:

```bash
docker exec atrust-ubuntu dig service.internal.example.com +short
```

Verify TUN and routing:

```bash
docker exec atrust-ubuntu ip route
docker exec atrust-ubuntu sysctl -n net.ipv4.conf.utun7.route_localnet
```

If `route_localnet` is not `1`, you likely forgot `--sysctl net.ipv4.conf.default.route_localnet=1`.

### 6.3 Desktop Icons Disappear

When mounting a host directory to `/root`, `~/.cache` may not support Unix sockets, causing the desktop manager to fail. This repo redirects `pcmanfm` cache to `/tmp` with delayed retry.

```bash
docker exec atrust-ubuntu tail -n 200 /tmp/pcmanfm-desktop.log
```

### 6.4 Port `8888` Unavailable Causes Container Exit

`8888` is the mandatory proxy port. The container strictly monitors tinyproxy — if it crashes or stops listening, the container exits to avoid a "VPN online but proxy dead" false-healthy state.

```bash
docker logs --tail 200 atrust-ubuntu
docker exec atrust-ubuntu ss -lntp | grep ':8888'
docker exec atrust-ubuntu tail -n 200 /var/log/tinyproxy/tinyproxy.log
```

### 6.5 `/dev/net/tun` Not Found on Windows

Docker Desktop for Windows runs containers in a Linux VM where `/dev/net/tun` is automatically available. If you get an error, ensure Docker Desktop has WSL 2 or Hyper-V backend enabled.

## Disclaimer

aTrust is commercial software by Sangfor. This repository only provides containerization and runtime configuration scripts — it does not modify or distribute aTrust itself. Ensure your usage complies with relevant licenses and regulations.
