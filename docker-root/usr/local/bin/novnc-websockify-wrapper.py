#!/usr/bin/env python3
"""Run websockify with MIME types required by noVNC ES modules."""

import sys

from websockify import websocketproxy


default_guess_type = websocketproxy.ProxyRequestHandler.guess_type


def guess_type(self, path):
    if path.lower().endswith(('.js', '.mjs')):
        return 'application/javascript'
    return default_guess_type(self, path)


websocketproxy.ProxyRequestHandler.guess_type = guess_type


if __name__ == '__main__':
    print('noVNC MIME override active: .js/.mjs -> application/javascript',
          flush=True)
    sys.exit(websocketproxy.websockify_init())