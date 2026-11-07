"""退出清场端到端测试：启动应用 → 制造子进程 → 触发托盘退出 → 外部校验归零。"""
import os
import subprocess
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PID_FILE = os.path.join(HERE, 'dist', '_exit_test_child.pid')


def _spawn_children():
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    cmds = [
        [sys.executable, '-c', 'import time; time.sleep(120)'],
        [sys.executable, '-c', 'import time; time.sleep(120)',
         '--sencast-marker-test'],
    ]
    pids = []
    for cmd in cmds:
        p = subprocess.Popen(cmd)
        pids.append(p.pid)
    with open(PID_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(str(p) for p in pids))
    print('[TEST] spawned children: %s' % pids, flush=True)


def _do_quit():
    _spawn_children()
    for w in QApplication.topLevelWidgets():
        if w.__class__.__name__ == 'MainWindow':
            print('[TEST] triggering _quit_app', flush=True)
            w._quit_app()
            return
    print('[TEST] MainWindow NOT FOUND, hard exit', flush=True)
    from receiver.killswitch import hard_exit
    hard_exit(3)


if __name__ == '__main__':
    import main as app_main
    _real = app_main.QApplication

    class _TestApp(_real):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            QTimer.singleShot(4500, _do_quit)

    app_main.QApplication = _TestApp
    app_main.main()
