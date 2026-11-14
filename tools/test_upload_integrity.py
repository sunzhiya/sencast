"""手机上传完整性回归：正常落盘、中途断开不落残file、无长度不落空file。"""
import io
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from receiver.dlna.server import _Handler  # noqa: E402


class FakeHandler:
    _unique_path = staticmethod(_Handler._unique_path)
    _fmt_speed = staticmethod(_Handler._fmt_speed)

    def __init__(self, name, payload, declared, dest_dir, events):
        self.path = '/upload?name=' + name
        self.headers = {'Content-Length': str(declared)}
        self.client_address = ('127.0.0.1', 54321)
        self.rfile = io.BytesIO(payload)
        self.server = SimpleNamespace(
            log=lambda *_a, **_k: None,
            upload_dir=dest_dir,
            upload_progress_cb=lambda n, p, s: events.append(('progress', n, p)),
            upload_done_cb=lambda n, p: events.append(('done', n, p)),
            upload_fail_cb=lambda n, r: events.append(('fail', n, r)),
        )
        self.events = events
        self.response = None

    def _send(self, code, body, content_type=None, extra=None):
        self.response = (code, json.loads(body) if isinstance(body, str) else body)


def run(name, payload, declared, dest_dir):
    events = []
    h = FakeHandler(name, payload, declared, dest_dir, events)
    _Handler._handle_upload(h)
    return h.response, events, sorted(os.listdir(dest_dir))


def main():
    tmp = tempfile.mkdtemp(prefix='sencast_upload_')
    results = []

    def check(label, got, expect):
        ok = (got == expect)
        results.append((label, ok))
        print('%-38s got=%-28s expect=%-28s %s' %
              (label, str(got), str(expect), 'OK' if ok else 'FAIL'))

    try:
        # 1 正常上传
        payload = b'hello-sencast' * 100
        resp, ev, files = run('ok.bin', payload, len(payload), tmp)
        check('1 正常上传返回 200', resp[0], 200)
        check('2 正常上传触发 done', ('done' in [e[0] for e in ev]), True)
        check('3 正常上传不触发 fail', ('fail' in [e[0] for e in ev]), False)
        dest = os.path.join(tmp, 'ok.bin')
        check('4 成品文件字节完整',
              os.path.getsize(dest) if os.path.exists(dest) else -1, len(payload))

        # 2 中途断开：声明 1000 字节，只给 100
        short = b'x' * 100
        resp, ev, files = run('broken.bin', short, 1000, tmp)
        check('5 断开返回 500', resp[0], 500)
        check('6 断开触发 fail', ('fail' in [e[0] for e in ev]), True)
        check('7 断开不触发 done', ('done' in [e[0] for e in ev]), False)
        check('8 断开不生成成品', os.path.exists(os.path.join(tmp, 'broken.bin')), False)
        check('9 断开不留 .part 残留',
              any(f.endswith('.part') for f in files), False)

        # 3 无 Content-Length：不能生成 0 字节空文件并报成功
        resp, ev, files = run('empty.bin', b'', 0, tmp)
        check('10 无长度返回 500', resp[0], 500)
        check('11 无长度触发 fail', ('fail' in [e[0] for e in ev]), True)
        check('12 无长度不生成空文件',
              os.path.exists(os.path.join(tmp, 'empty.bin')), False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [r for r in results if not r[1]]
    print('\nRESULT: %d/%d passed' % (len(results) - len(bad), len(results)))
    for r in bad:
        print('  FAILED: %s' % r[0])
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
