#!/usr/bin/env python3
"""
VNC ↔ X Clipboard Bridge via CUT_BUFFER0 (v2: 修复 v1 死锁 + 详细日志)
"""

import os
import sys
import time
import threading
import subprocess
import traceback

DISPLAY = os.environ.get('DISPLAY', ':1')
XAUTHORITY = os.environ.get('XAUTHORITY', '/root/.Xauthority')

ENV = dict(os.environ)
ENV['DISPLAY'] = DISPLAY
ENV['XAUTHORITY'] = XAUTHORITY

LOG_LOCK = threading.Lock()
def log(*a):
    with LOG_LOCK:
        msg = ' '.join(str(x) for x in a)
        print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)

def run(cmd, input_data=None, timeout=3):
    try:
        r = subprocess.run(cmd, env=ENV, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True,
                           input=input_data, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        log('TIMEOUT', cmd)
        return -1, '', 'timeout'
    except Exception as e:
        log('ERROR', cmd, e)
        return -1, '', str(e)

def get_x_selection():
    rc, out, err = run(['xclip', '-selection', 'clipboard', '-o'])
    if rc == 0:
        return out
    return None

def set_x_selection(text):
    if not text:
        return False
    rc, _, err = run(['xclip', '-selection', 'clipboard'], input_data=text)
    if rc != 0:
        log('set_x_selection err:', err)
    return rc == 0

def get_vnc_clip():
    rc, out, err = run(['xprop', '-root', '-notype', 'CUT_BUFFER0'])
    if rc != 0:
        return None
    if '=' not in out:
        return None
    line = out.split('=', 1)[1].strip()
    if line.startswith('"') and line.endswith('"'):
        try:
            import codecs
            return codecs.decode(line, 'unicode_escape')[1:-1]
        except Exception:
            return line[1:-1]
    return line

def set_vnc_clip(text):
    if not text:
        return
    rc, _, err = run(['xprop', '-root', '-format', 'CUT_BUFFER0', '8s',
                      '-set', 'CUT_BUFFER0', text])
    if rc != 0:
        log('set_vnc_clip err:', err)

def bridge_x_to_vnc():
    log('thread x->vnc started')
    last = None
    while True:
        try:
            cur = get_x_selection()
            if cur is None:
                time.sleep(0.3)
                continue
            if last is None:
                # Initialize last on first run so we don't push the pre-existing text back
                last = cur
                log('x->vnc init last=', repr(cur[:50]))
            elif cur != last:
                log('x->vnc change:', repr(cur[:80]))
                set_vnc_clip(cur)
                last = cur
        except Exception:
            traceback.print_exc()
        time.sleep(0.3)

def bridge_vnc_to_x():
    log('thread vnc->x started')
    last = None
    while True:
        try:
            cur = get_vnc_clip()
            if cur is None:
                time.sleep(0.3)
                continue
            if last is None:
                last = cur
                log('vnc->x init last=', repr(cur[:50]))
            elif cur != last:
                log('vnc->x change:', repr(cur[:80]))
                # Write to PRIMARY too for middle-click paste
                run(['xclip', '-selection', 'primary'], input_data=cur)
                set_x_selection(cur)
                last = cur
        except Exception:
            traceback.print_exc()
        time.sleep(0.3)

def main():
    log(f'vnc-clip-bridge v2 starting: DISPLAY={DISPLAY} XAUTHORITY={XAUTHORITY}')
    # Probe sanity
    initial_clip = get_x_selection()
    initial_vnc = get_vnc_clip()
    log(f'init x-clipboard: {initial_clip!r:.80}')
    log(f'init CUT_BUFFER0: {initial_vnc!r:.80}')

    t1 = threading.Thread(target=bridge_x_to_vnc, daemon=True)
    t2 = threading.Thread(target=bridge_vnc_to_x, daemon=True)
    t1.start()
    t2.start()
    while True:
        time.sleep(60)

if __name__ == '__main__':
    main()