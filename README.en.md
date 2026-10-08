# Docker-aTrust (Ubuntu GUI + Chromium)

[**中文文档**](README.md) | English

This repository is based on [docker-easyconnect](https://github.com/docker-easyconnect/docker-easyconnect). It builds an Ubuntu container with a graphical desktop, installs and runs the GUI version of aTrust inside the container, and unifies the default browser and aTrust's redirect browser to Chromium for seamless web-based login flow.

The container provides:

- VNC desktop (port `5901`, password set through the `PASSWORD` environment variable).
- noVNC web access (port `8080`, open in browser directly).
- SOCKS5 proxy (default port `1080`, recommended for Clash Verge routing).
- HTTP proxy (default port `8888`, mandatory).
- aTrust local web login port (`54631`, used for aTrust's browser login redirect).

> **Ports are customizable.** Host-side SOCKS5 and HTTP proxy ports can be adjusted through `SOCKS_PORT` and `HTTP_PORT`, and bind addresses through `SOCKS_BIND_ADDR` and `HTTP_BIND_ADDR` (see [Running the Container](#2-running-the-container)). Services inside the container always listen on `1080` / `8888`.

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
  $(cat build-args/atrust-arm64-cn.txt) \
  --build-arg CHROMIUM=1 \
  .
```

### 1.2 Intel / AMD (amd64 / x86_64)

```bash
cd Docker-aTrust
docker build -t atrust-ubuntu:chromium \
  --platform linux/amd64 \
  -f Dockerfile.ubuntu \
  $(cat build-args/atrust-amd64-cn.txt) \
  --build-arg CHROMIUM=1 \
  .
```

Notes:

- `--build-arg CHROMIUM=1` installs Chromium inside the image.
- `build-args/` contains multiple aTrust versions — swap as needed.

## 2. Running the Container

### Port Configuration

Compose binds every published port to `127.0.0.1` by default. Copy the template and configure the Git-ignored `.env` first:

```bash
cp .env.example .env
chmod 600 .env
```

Set `VNC_PASSWORD` in `.env`, then run `docker compose up -d`. Keep credentials single-quoted, for example `VNC_PASSWORD='random$value'`, so Compose does not expand `$` as a variable. Legacy VNC authentication uses only the first eight password characters; use a random value, but do not rely on it for public-internet protection. To access one service from another trusted device, bind only that service to a trusted interface, for example `SOCKS_BIND_ADDR=<trusted-interface-address>` in `.env`. Do not use `0.0.0.0` unless source-address firewall rules are in place.

### Start Command

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
<summary>Windows PowerShell version</summary>

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

> Windows PowerShell 5.1 supports neither Bash `${VAR:-default}` nor the PowerShell 7 `??` operator, so the example computes port defaults explicitly.

</details>

Key parameters explained:

- `--device /dev/net/tun` + `--cap-add NET_ADMIN`: aTrust requires TUN device creation.
- `--sysctl net.ipv4.conf.default.route_localnet=1`: enables aTrust DNS routing (cannot be reliably set inside the container on Docker Desktop).
- `--shm-size=512m`: prevents Chromium crashes due to small `/dev/shm`.
- `-e PASSWORD="$VNC_PASSWORD"`: sets the required VNC password. Legacy VNC authentication uses only the first eight characters; do not use a sample value, commit the real value, or treat it as public-internet protection.
- `-e CHROMIUM=1`: enables automatic Chromium launch for aTrust login redirects.
- `-e URLWIN=1`: shows URL popup and copies to clipboard when aTrust opens a URL (useful for debugging).
- `-e USE_NOVNC=1`: enables noVNC; access it at `http://<server-ip>:<published-host-port>/vnc.html`.
- `-p 127.0.0.1:8080:8080`: noVNC web port (only needed when `USE_NOVNC` is enabled). For remote access, bind only to a trusted private interface and use firewall rules or a TLS reverse proxy.
- `-v $HOME/.atrust-data:/root`: persists `/root` (aTrust login data, Chromium config, etc.).
- `-p ${HTTP_PORT:-8888}:8888`: `8888` is the mandatory HTTP proxy port. If tinyproxy fails or stops listening, the container exits.

## 3. VNC / noVNC Desktop Login

### Option A: VNC Client

1. Connect VNC to `127.0.0.1:5901`.
2. Password: the `PASSWORD` value used when starting the container.

### Option B: Browser (noVNC, recommended for remote servers)

1. Open `http://<server-ip>:<NOVNC_PORT>/vnc.html`. The built-in server is HTTP-only; do not use `https://`. Put a TLS-enabled reverse proxy in front if HTTPS is required.
2. Enter the `PASSWORD` value used when starting the container.
3. Click Connect to enter the desktop.

> **noVNC is recommended for remote server deployments.** There is no need to expose port 5901 or install a VNC client. Bind noVNC only to a trusted private interface and access it through firewall restrictions, a private overlay network, or a WebSocket-capable TLS reverse proxy.

### noVNC Clipboard

noVNC renders the remote display in a browser canvas. Pressing `Ctrl+V` directly in the display usually sends only the key event to the remote desktop; it does not automatically read the local clipboard. To transfer plain text:

1. Expand the noVNC sidebar and open the clipboard panel.
2. Paste local text into the panel, then click outside the text area to send it.
3. Return to the remote application and press `Ctrl+V`.

You can also set or read the remote clipboard from the Docker host:

```bash
docker exec atrust-ubuntu set-vnc-clip.sh 'text to paste'
docker exec atrust-ubuntu get-vnc-clip.sh
```

VNC clipboard transfer is primarily for plain text. Chinese text, images, files, and rich text may not synchronize reliably.

### Log into aTrust

1. Three desktop icons: `aTrust`, `Chromium`, and `Keep Alive`.
2. Double-click `aTrust`, log in per your organization's config.
3. aTrust will auto-launch Chromium for the corresponding web authentication pages.

If you still need to manually copy the URL, check:

- Container was started with `-e CHROMIUM=1`.
- You're using the image built from this repo (don't mix with old images).

## 4. Accessing the aTrust Network Through the Container Proxy

After aTrust connects inside the container, proxy ports are exposed on the host:

- **SOCKS5**: `${SOCKS_BIND_ADDR:-127.0.0.1}:${SOCKS_PORT}` (default `127.0.0.1:1080`).
- **HTTP**: `${HTTP_BIND_ADDR:-127.0.0.1}:${HTTP_PORT}` (default `127.0.0.1:8888`).

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

For example, if the Docker-aTrust SOCKS5 endpoint is `<docker-host>:1080` and the internal SSH target is `<internal-host>:22`:

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

Replace `<ssh-user>` with the SSH user on the internal target, then run:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/config
ssh atrust-internal
```

Here, `-X 5` selects SOCKS5, `-x` specifies the Docker-aTrust SOCKS5 endpoint, and OpenSSH replaces `%h` and `%p` with the `HostName` and `Port` from the current block. The argument after `-x` must be one `host:port` value; do not insert an extra `1` before the address.

The example works with macOS and Linux systems using OpenBSD `nc`. If local `nc` does not support `-X/-x`, install Nmap `ncat` and use:

```sshconfig
ProxyCommand ncat --proxy <docker-host>:1080 --proxy-type socks5 %h %p
```

> The OpenBSD `nc` example above assumes SOCKS5 without authentication. A remote client also requires port `1080` to be bound to a host interface reachable by that client, not only to `127.0.0.1`. Do not expose port `1080` to the public internet. Restrict source addresses with a firewall, or access it only through a trusted LAN, SSH tunnel, or private overlay network. If authentication is required, set both `SOCKS_USER` and `SOCKS_PASSWD` in `.env` and use a client that supports SOCKS5 authentication, such as `ncat --proxy-auth <proxy-user>:<proxy-password>`. Never commit real credentials or put them in an SSH config readable by other users.

## 5. Keep Alive Program

This repo adds a keep-alive program that combines real network probes with keyboard and mouse activity to prevent idle disconnections.

### 5.1 Features

The keep-alive program provides:

- **Network keep-alive probes**: ICMP, direct TCP, and HTTP GET have independent settings and can run concurrently without SOCKS5.
- **Idle activity keep-alive**: Checks X11 idle time and, after the threshold, moves the mouse out and back and toggles Scroll Lock twice.

### 5.2 Usage

The keep-alive program must be started manually the first time. Its enabled state is persisted, so it starts automatically after later container restarts:

1. Connect to the desktop via VNC.
2. Double-click the `Keep Alive` desktop icon to open the settings GUI.
3. Configure parameters in the settings window:
   - **ICMP/TCP/HTTP tabs**: Configure enabled state, targets, interval, timeout, and attempts independently.
   - **Concurrent operation**: Enable any combination of network modules; each runs on its own schedule.
   - **Idle activity keep-alive**: Configure the idle threshold and check interval; mouse and Scroll Lock actions can be enabled independently.
4. Click **"Save Config"** to save settings.
5. Click **"▶ Start"** to launch the daemon (status bar shows running state and PID).
6. Click **"■ Stop"** to stop the daemon.

> Configuration is stored in `/root/.keep-alive/config.json`. Clicking Start persists both the settings and enabled state in the `/root` volume. Clicking Stop also disables automatic restoration.

The three network keep-alive types are configured separately:

| Target format | Probe | Example |
| --- | --- | --- |
| IP or domain | ICMP Ping | `10.0.0.1` |
| `host:port` or `tcp://host:port` | Direct TCP | `internal.example.com:22` |
| `http://` or `https://` URL | HTTP GET without a proxy | `https://intranet.example/health` |

Use an actual TCP port or HTTP URL when the resource blocks ICMP. The target must route through aTrust from inside the container. An `OK` log entry only means the target is reachable; inspect `/root/.aTrust/logs/xtunnel/tcpAccess.log` when you need to confirm that it generated aTrust business traffic.

### 5.3 Command-Line Management

You can also manage the keep-alive program from the command line:

```bash
# Start the daemon
docker exec -e DISPLAY=:1 atrust-ubuntu python3 /usr/local/bin/keep-alive.py --start

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

| Field | Description |
| --- | --- |
| `icmp.enabled` / `tcp.enabled` / `http.enabled` | Enable each network module independently; all may be `true` |
| `icmp.targets` | ICMP target list containing IP addresses or domains |
| `tcp.targets` | TCP target list containing `host:port` or `tcp://host:port` |
| `http.targets` | HTTP(S) URL list; each target receives a real GET |
| `*.interval` | Independent probe interval for that module, in seconds (minimum 5) |
| `*.timeout` | Single probe timeout for that module, in seconds |
| `*.count` | Attempts per target in each round for that module |
| `http.verify_tls` | Verify the server certificate for HTTPS GET probes |
| `activity.enabled` | Enable activity keep-alive based on X11 idle time |
| `activity.idle_threshold` | Idle seconds before activity is generated; default `4500` (75 minutes) |
| `activity.trigger_margin` | Trigger this many seconds before the idle threshold; default 60, so activity runs at minute 74 |
| `activity.check_interval` | Maximum check interval; default `1800`, with an earlier wake-up scheduled near the threshold |
| `activity.mouse_enabled` | Move the mouse out and back after the threshold |
| `activity.dx/dy` | Relative mouse offset; default `(1,0)` |
| `activity.mouse_delay_ms` | Delay before returning the mouse; default 50 ms |
| `activity.keyboard_enabled` | Generate the configured keyboard action after the threshold |
| `activity.key` / `activity.key_repeats` | Press and release `Scroll_Lock` twice by default, restoring its lock state |
| `activity.key_delay_ms` | Delay after each key down/up event; default 30 ms |

The default activity logic is based on the tested AutoHotkey script with an added pre-threshold guarantee. It checks at most every 30 minutes and schedules an earlier wake-up as the threshold approaches. At 74 minutes of X11 idle time it moves the mouse one pixel right, returns it after 50 ms, then presses and releases Scroll Lock twice. The daemon also disables X11 screen blanking, the screen saver, and DPMS. A VNC/noVNC client does not need to remain connected.

### 5.5 Hot Update Without Restarting the Container

If rebuilding must wait for a maintenance window, replace only the Keep Alive scripts. This does not restart aTrust, VNC, noVNC, or the proxy services, but it briefly restarts the Keep Alive daemon itself:

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

Close and reopen the Keep Alive window to load the new code, or launch it directly:

```bash
docker exec -d -e DISPLAY=:1 atrust-ubuntu /usr/local/bin/keep-alive-launcher
```

Changes made inside a running container are lost when the container is recreated, so rebuild the image later.

## 6. Troubleshooting

### 6.1 Chromium Crashes on Click

Ensure `--shm-size=512m` is in your run command. Use the desktop icon or `chromium-launcher` (this repo adds `--no-sandbox` and `--disable-dev-shm-usage`).

### 6.2 aTrust Connected but Can't Access an Internal Domain

Check DNS resolution inside the container:

```bash
docker exec atrust-ubuntu getent hosts service.internal.example.com
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

### 6.6 noVNC Stays on the Loading Screen

Check the JavaScript module response headers:

```bash
curl -sSI http://<docker-host>:<novnc-port>/app/ui.js
curl -sSI http://<docker-host>:<novnc-port>/app/error-handler.js
```

Both responses must contain `Content-Type: application/javascript`. The container log should also contain:

```text
noVNC MIME override active: .js/.mjs -> application/javascript
```

If the marker is absent, the container is still using an old image. Rebuild it and recreate the container with `docker compose up -d --force-recreate`. If headers are correct but the browser reports an old MIME error, clear the site cache or use a private window.

`No SSL/TLS support (no cert file)` is expected in HTTP mode. Direct `https://` requests produce `SSL connection but '/self.pem' not found`; put a TLS reverse proxy with WebSocket support in front of noVNC when HTTPS is required.

### 6.7 Invalid Keep Alive Desktop Entry or Startup Failure

If PCManFM reports `Invalid desktop entry file`, inspect the desktop entry and launcher permissions:

```bash
docker exec atrust-ubuntu sh -c '
ls -l /root/Desktop/KeepAlive.desktop /usr/local/bin/keep-alive-launcher
test -x /usr/local/bin/keep-alive-launcher
'
```

The launcher must be executable. Temporarily fix an old image with:

```bash
docker exec atrust-ubuntu chmod 0755 /usr/local/bin/keep-alive-launcher
docker exec atrust-ubuntu touch /root/Desktop/KeepAlive.desktop
```

If the GUI displays `init() got an unexpected keyword argument 'capture_output'`, the old scripts use a Python 3.7-only argument while Ubuntu 18.04 ships Python 3.6. Use the current image or hot-update both Keep Alive scripts as described in section 5.5.

## Disclaimer

aTrust is commercial software by Sangfor. This repository only provides containerization and runtime configuration scripts — it does not modify or distribute aTrust itself. Ensure your usage complies with relevant licenses and regulations.
