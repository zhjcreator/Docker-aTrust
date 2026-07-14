#!/bin/sh
exec su daemon -s /bin/sh -c "exec /usr/local/bin/novnc-websockify-wrapper.py --web /usr/local/share/novnc 0.0.0.0:8080 127.0.0.1:5901"
