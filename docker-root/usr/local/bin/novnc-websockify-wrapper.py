#!/usr/bin/env python3
"""websockify wrapper that registers proper MIME types for noVNC ES modules."""

import mimetypes
import sys
import os

# Register missing MIME types for noVNC v1.4.0 ES modules
# Python 3.6's mimetypes doesn't have .mjs registered
mimetypes.add_type('application/javascript', '.mjs')
# Also ensure .js is explicitly mapped (some Python versions default to
# application/octet-stream for unknown files served over certain paths)
mimetypes.add_type('application/javascript', '.js')

# Fix permissions issue: websockify runs as daemon user but may not own the novnc dir
novnc_dir = '/usr/local/share/novnc'
if os.path.isdir(novnc_dir):
    # Ensure daemon user can read all files
    os.system('chmod -R a+r ' + novnc_dir)

# Re-exec into websockify with the corrected MIME types
from websockify.websocketproxy import websockify_init

if __name__ == '__main__':
    # The arguments are the same as the original websockify command
    # --web /usr/local/share/novnc 0.0.0.0:8080 127.0.0.1:5901
    sys.exit(websockify_init())
