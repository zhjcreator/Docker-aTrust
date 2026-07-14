# Docker-aTrust Project Memory

## 项目概述
- Fork 自 realZillionX/Docker-aTrust，推送至 zhjcreator/Docker-aTrust
- 基于 Ubuntu 18.04 的 Docker 容器，提供 VNC 桌面 + aTrust VPN + Chromium
- 容器提供 SOCKS5(1080)/HTTP(8888) 代理、VNC(5901)

## Keep Alive 保活程序
- 位置: `keep-alive/keep-alive.py` (daemon) + `keep-alive/keep-alive-gui.py` (GTK3 GUI)
- 安装路径: `/usr/local/bin/keep-alive.py` + `/usr/local/bin/keep-alive-gui.py`
- 启动器: `docker-root/usr/local/bin/keep-alive-launcher`
- 配置存储: `/root/.keep-alive/config.json` (Docker volume 持久化)
- 功能: 定时 ICMP ping + 鼠标微移动(xdotool) + 键盘微操作(xdotool)
- 不自动启动，需手动从桌面图标或 CLI 启动
- Dockerfile 新增依赖: python3, python3-gi, gir1.2-gtk-3.0, xdotool, iputils-ping

## Docker Compose
- docker-compose.yml: 面向 Linux 服务器部署，data 目录持久化 /root
- 端口: VNC(5901), SOCKS5(1080), HTTP(8888), aTrust Web(54631)

## Git 配置
- origin: https://github.com/realZillionX/Docker-aTrust (上游)
- myfork: https://github.com/zhjcreator/Docker-aTrust (个人 fork)
- feature/keep-alive 分支已推送到 myfork
