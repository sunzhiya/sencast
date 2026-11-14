"""灵动岛状态机回归：播放隐藏、真实热区、淡出防反转、传输/完成、连续传输、常驻居中。

关键点：不再 mock 掉 _hotzone，而是注入 _cursor_pos，让真实热区逻辑参与裁决。
播放状态分支直接调用 MainWindow._on_playback_changed，测的是真代码。
"""
import os
import sys

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'dist')


class P:
    def __init__(self):
        self.playing = False

    def is_playing(self):
        return self.playing


class M:
    def __init__(self, app):
        self.player = P()
        self.app = app
        self.visible = True
        self.minimized = False
        self.fullscreen = False

    def screen(self):
        return self.app.primaryScreen()

    def isVisible(self):
        return self.visible

    def isMinimized(self):
        return self.minimized

    def isFullScreen(self):
        return self.fullscreen

    def mapToGlobal(self, p):
        return p

    def _toggle_pause(self):
        pass

    def on_stop(self):
        pass

    def _minimize_to_tray(self):
        pass

    def populate_more_menu(self, m):
        pass

    def bring_to_front(self):
        pass


class _Stub:
    def setText(self, *_a):
        pass


class _FakeMain:
    """只提供 _on_playback_changed 用到的属性，用来跑真实的 gui 分支。"""

    def __init__(self, island):
        self.island = island
        self.bridge = None
        self.state_label = _Stub()
        self.btn_pause = _Stub()
        self.btn_play_toggle = _Stub()

    def append_log(self, *_a):
        pass


def settle(isl, app):
    for _ in range(60):
        if isl._fading:
            isl._tick_fade()
        app.processEvents()
    return isl.isVisible()


def main():
    app = QApplication(sys.argv)
    m = M(app)
    from receiver.island import IslandBar
    from receiver.gui import MainWindow
    isl = IslandBar(m)

    geo0 = app.primaryScreen().availableGeometry()
    cur = {'p': QPoint(5, 5)}
    isl._cursor_pos = lambda: cur['p']
    AWAY = QPoint(5, 5)
    BAND = QPoint(geo0.center().x(), geo0.top() + 8)
    cur['p'] = AWAY
    os.makedirs(OUT, exist_ok=True)
    results = []

    def step(label, expect, shot=None):
        vis = settle(isl, app)
        ok = (vis == expect)
        results.append((label, vis, expect, ok))
        print('%-36s visible=%-5s expect=%-5s %s' %
              (label, vis, expect, 'OK' if ok else 'FAIL'))
        if shot:
            isl.grab().save(os.path.join(OUT, shot), 'PNG')

    def check(label, got, expect):
        ok = (got == expect)
        results.append((label, got, expect, ok))
        print('%-36s got=%-5s expect=%-5s %s' %
              (label, got, expect, 'OK' if ok else 'FAIL'))

    def playback(name):
        MainWindow._on_playback_changed(fake, name)

    fake = _FakeMain(isl)

    # 1 空闲常驻
    isl.guard()
    step('1 空闲常驻', True, '_isl_idle.png')

    # 2 播放后隐藏
    m.player.playing = True
    playback('PLAYING')
    step('2 播放视频后自动隐藏', False)

    # 3 反复 guard 不应把岛拉回来
    for _ in range(5):
        isl.guard()
    step('3 播放中反复 guard 仍隐藏', False)

    # 4 真实热区：鼠标顶到屏幕上沿中间
    cur['p'] = BAND
    isl.guard()
    step('4 真实热区唤出控制条', True)

    # 5 鼠标离开后自动收回
    cur['p'] = AWAY
    isl._wake_until = 0.0
    isl.guard()
    step('5 热区离开后自动收回', False)

    # 6 淡出过程中鼠标压在岛上，不许把淡出反转成淡入（岛卡死不退的根因）
    isl.fade_in()
    settle(isl, app)
    cur['p'] = isl.geometry().center()
    isl._wake_until = 0.0
    isl.fade_out(hide_after=True)
    for _ in range(5):
        isl.guard()
    step('6 淡出中鼠标压岛不反转', False)
    cur['p'] = AWAY

    # 7 播放中收到文件：强制弹出并显进度
    isl.begin_transfer('旅行照片.zip')
    isl.update_transfer('旅行照片.zip', 46, '12.4 MB/s')
    step('7 观影态传输强制弹出', True, '_isl_new_transfer.png')

    # 8 完成态
    isl.finish_transfer('旅行照片.zip', 'C:/fake/旅行照片.zip')
    step('8 完成态显示', True, '_isl_new_done.png')

    # 9 模拟 2.4s 定时器触发（观影态应淡出）
    isl._end_transfer()
    step('9 观影态完成后消失', False)
    for _ in range(5):
        isl.guard()
    step('10 静默期内 guard 不拉回', False)

    # 11 停止播放后恢复常驻（清掉静默期）
    m.player.playing = False
    isl._suppress_until = 0.0
    playback('STOPPED')
    step('11 停止后恢复常驻', True)

    # 12 收托盘 / 最小化仍常驻
    m.visible = False
    m.minimized = True
    isl.guard()
    step('12 收托盘后仍常驻', True)

    # 13 屏幕几何变化自适应居中
    isl._geo_key = None
    isl.guard()
    g = isl._screen_geo()
    sc, ic = g.center().x(), isl.x() + isl.width() // 2
    results.append(('13 水平中线居中', ic, sc, abs(sc - ic) <= 1))
    print('%-36s screen=%s island=%s %s' %
          ('13 水平中线居中', sc, ic, 'OK' if abs(sc - ic) <= 1 else 'FAIL'))

    # 14 起播中间态（缓冲回落）不许把岛拉回画面上
    m.visible = True
    m.minimized = False
    m.player.playing = True
    playback('PLAYING')
    playback('TRANSITIONING')
    playback('BUFFERING')
    step('14 缓冲中间态仍隐藏', False)

    # 15 明确停止态恢复常驻
    m.player.playing = False
    playback('STOPPED')
    step('15 STOPPED 后恢复常驻', True)

    # 16 连续传输：第一个文件的旧完成定时器不能掐掉第二个
    isl.begin_transfer('A.zip')
    seq_a = isl._transfer_seq
    isl.finish_transfer('A.zip', 'C:/fake/A.zip')
    isl.begin_transfer('B.zip')
    isl.update_transfer('B.zip', 30, '8.0 MB/s')
    isl._end_transfer(seq_a)          # 旧定时器按旧序号回调
    step('16 旧完成定时器不掐新传输', True)
    check('17 新传输仍在传输态', isl._transfer_on, True)
    check('18 新传输进度条可见', isl.transfer_box.isVisible(), True)

    # 19 空闲态完成传输：只收起传输条，胶囊立刻回到常驻
    isl.finish_transfer('B.zip', 'C:/fake/B.zip')
    isl._end_transfer()
    step('19 空闲态完成后回常驻', True)
    check('20 传输条已收起', isl.transfer_box.isVisible(), False)
    check('21 常驻形态高度复位', isl.height(), 46)

    # 22 传输中断：给出失败提示后自动收起，绝不永久卡在传输态
    isl.begin_transfer('C.zip')
    isl.fail_transfer('C.zip', '传输中断，文件未保存')
    step('22 接收失败提示弹出', True, '_isl_fail.png')
    check('23 失败文案正确', '接收失败' in isl.t_name.text(), True)
    isl._end_transfer()
    step('24 失败提示收起回常驻', True)
    check('25 失败后传输条收起', isl.transfer_box.isVisible(), False)

    bad = [r for r in results if not r[3]]
    print('\nRESULT: %d/%d passed' % (len(results) - len(bad), len(results)))
    for r in bad:
        print('  FAILED: %s got=%s expect=%s' % (r[0], r[1], r[2]))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
