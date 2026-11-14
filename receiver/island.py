import os
import time

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect
from PyQt6.QtGui import (QPainter, QColor, QPainterPath, QPen, QFont,
                         QLinearGradient, QBrush, QFontMetrics, QCursor)
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QSlider, QMenu, QApplication)


class TransferBar(QWidget):
    """圆角自绘进度条。"""

    def __init__(self):
        super().__init__()
        self._v = 0
        self.setFixedHeight(6)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_value(self, v):
        v = max(0, min(100, int(v)))
        if v != self._v:
            self._v = v
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()
        w = float(r.width())
        h = float(r.height())
        if w <= 0 or h <= 0:
            p.end()
            return
        rad = h / 2.0
        bg = QPainterPath()
        bg.addRoundedRect(0.0, 0.0, w, h, rad, rad)
        p.fillPath(bg, QColor(255, 255, 255, 40))
        fw = w * self._v / 100.0
        if fw > 0.5:
            fg = QPainterPath()
            fg.addRoundedRect(0.0, 0.0, fw, h, rad, rad)
            g = QLinearGradient(0.0, 0.0, max(fw, 1.0), 0.0)
            g.setColorAt(0.0, QColor(86, 200, 255))
            g.setColorAt(1.0, QColor(126, 140, 255))
            p.fillPath(fg, QBrush(g))
        p.end()


class IslandBar(QWidget):

    def __init__(self, main_window):
        super().__init__(None, Qt.WindowType.Tool
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.main = main_window
        self.setObjectName('islandBar')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self._opacity = 1.0
        self._compact = False
        self._fading = False
        self._fade_dir = 1
        self._hide_after_fade = False
        self._transfer_on = False
        self._transfer_done = False
        self._transfer_seq = 0        # 传输序号：旧文件的完成定时器不能掐掉新文件
        self._last_w = 0
        self._last_h = 0
        self._geo_key = None
        # 单一目标状态机：所有外部调用只改状态，显隐统一由 guard() 裁决
        self._cast_mode = False        # 观影态（播放 / 暂停 / 全屏）
        self._wake_until = 0.0        # 临时唤醒截止时间（顶部热区 / 主动叫窗口）
        self._suppress_until = 0.0    # 传输完成后的静默期
        self._cast_override_until = 0.0  # 停止后短暂屏蔽播放器异步状态回落

        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(16)
        self._fade_timer.timeout.connect(self._tick_fade)

        self.setFixedHeight(46)
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 6, 12, 6)
        root.setSpacing(10)

        self.dot = QLabel('\u25cf')
        self.dot.setStyleSheet('color:#39ff88; font-size:13px; background:transparent;')
        root.addWidget(self.dot)

        self.name_label = QLabel('\u68ee\u6295\u5c4f\u63a5\u6536\u7aef')
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        self.name_label.setFont(f)
        self.name_label.setStyleSheet('color:#f2f2f7; background:transparent; letter-spacing:0.5px;')
        root.addWidget(self.name_label)

        self.state_label = QLabel('\u7a7a\u95f2')
        self.state_label.setStyleSheet('color:#9a9aa2; font-size:11px; background:transparent;')
        root.addWidget(self.state_label)

        self.stretch = QWidget()
        self.stretch.setStyleSheet('background:transparent;')
        self.stretch.setFixedWidth(1)
        root.addWidget(self.stretch, 1)

        self.ctrl = QWidget()
        self.ctrl.setStyleSheet('background:transparent;')
        ch = QHBoxLayout(self.ctrl)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(8)

        self.btn_play = self._icon_button('\u25b6', '\u64ad\u653e / \u6682\u505c', self._toggle_play)
        self.btn_stop = self._icon_button('\u25a0', '\u505c\u6b62', self._stop)
        ch.addWidget(self.btn_play)
        ch.addWidget(self.btn_stop)

        self.time_label = QLabel('')
        self.time_label.setStyleSheet('color:#c8c8d0; font-size:11px; background:transparent;')
        ch.addWidget(self.time_label)

        root.addWidget(self.ctrl)

        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setFixedWidth(84)
        self.vol.setStyleSheet(
            'QSlider{background:transparent;}'
            'QSlider::groove:horizontal{height:3px;background:rgba(255,255,255,60);border-radius:2px;}'
            'QSlider::sub-page:horizontal{background:rgba(255,255,255,190);border-radius:2px;}'
            'QSlider::handle:horizontal{width:9px;height:9px;margin:-3px 0;'
            'background:#ffffff;border-radius:5px;}')
        root.addWidget(self.vol)

        self.btn_more = self._icon_button('\u22ef', '\u66f4\u591a', self._show_more)
        root.addWidget(self.btn_more)

        root.addSpacing(4)
        self.btn_hide = self._icon_button('\u2014', '\u9690\u85cf\uff08\u6536\u8fdb\u6258\u76d8\uff09', self._hide_to_tray)
        root.addWidget(self.btn_hide)

        # ---- 文件传输模式控件（默认隐藏） ----
        self.transfer_box = QWidget()
        self.transfer_box.setStyleSheet('background:transparent;')
        tv = QVBoxLayout(self.transfer_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(3)

        self.t_name = QLabel('')
        self.t_name.setStyleSheet(
            'color:#f2f2f7; font-size:11px; font-weight:600; background:transparent;')
        tv.addWidget(self.t_name)

        self.t_bar = TransferBar()
        tv.addWidget(self.t_bar)

        self.t_sub = QLabel('')
        self.t_sub.setStyleSheet(
            'color:#9a9aa2; font-size:10px; background:transparent;')
        tv.addWidget(self.t_sub)

        self.transfer_box.setVisible(False)
        root.addWidget(self.transfer_box, 1)

        self.setVisible(True)

    def _icon_button(self, text, tip, slot):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(26, 26)
        b.setStyleSheet(
            'QPushButton{background:rgba(255,255,255,24);color:#ececf2;'
            'border:none;border-radius:13px;font-size:12px;}'
            'QPushButton:hover{background:rgba(255,255,255,58);}'
            'QPushButton:pressed{background:rgba(255,255,255,90);}')
        b.clicked.connect(slot)
        return b

    def _toggle_play(self):
        self._jump_back()
        try:
            self.main._toggle_pause()
        except Exception:
            pass

    def _stop(self):
        self._jump_back()
        try:
            self.main.on_stop()
        except Exception:
            pass

    def _hide_to_tray(self):
        try:
            self.main._minimize_to_tray()
        except Exception:
            pass

    def _jump_back(self):
        try:
            self.main.bring_to_front()
        except Exception:
            pass

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._jump_back()
        super().mousePressEvent(ev)

    def enterEvent(self, ev):
        if self._compact and not self._transfer_on:
            self.set_compact(False)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        try:
            if (not self._transfer_on and self.main is not None
                    and self.main.player.is_playing() and not self.underMouse()):
                self.set_compact(True)
        except Exception:
            pass
        super().leaveEvent(ev)

    def _show_more(self):
        m = QMenu(self)
        m.setStyleSheet(
            'QMenu{background:#1c1c22;color:#ececf2;border:1px solid rgba(255,255,255,28);'
            'border-radius:10px;padding:6px;}'
            'QMenu::item{padding:6px 22px 6px 14px;border-radius:6px;}'
            'QMenu::item:selected{background:rgba(255,255,255,32);}'
            'QMenu::separator{height:1px;background:rgba(255,255,255,22);margin:4px 8px;}')
        try:
            self.main.populate_more_menu(m)
        except Exception:
            pass
        m.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height() + 6)))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(1, 1, -1, -1)
        w = float(r.width())
        h = float(r.height())
        if w <= 0 or h <= 0:
            p.end()
            return
        radius = min(w, h) / 2.0
        path = QPainterPath()
        path.addRoundedRect(float(r.left()), float(r.top()), w, h, radius, radius)

        grad = QLinearGradient(0.0, float(r.top()), 0.0, float(r.bottom()))
        grad.setColorAt(0.0, QColor(58, 58, 70, int(234 * self._opacity)))
        grad.setColorAt(0.45, QColor(30, 30, 38, int(238 * self._opacity)))
        grad.setColorAt(1.0, QColor(13, 13, 18, int(243 * self._opacity)))
        p.fillPath(path, QBrush(grad))

        p.setPen(QPen(QColor(255, 255, 255, int(48 * self._opacity)), 1))
        p.drawPath(path)

        inset = 2.0
        if w > inset * 2 and h > 2.0:
            hl = QPainterPath()
            hl.addRoundedRect(float(r.left()) + inset, float(r.top()) + 1.0,
                              w - inset * 2, h - 2.0,
                              max(1.0, radius - inset), max(1.0, radius - inset))
            p.setPen(QPen(QColor(255, 255, 255, int(20 * self._opacity)), 1))
            p.drawPath(hl)
        p.end()

    # ---------- 淡入淡出（状态机，防重入） ----------

    def _tick_fade(self):
        if self._fade_dir > 0:
            self._opacity = min(1.0, self._opacity + 0.14)
            if self._opacity >= 1.0:
                self._opacity = 1.0
                self._fading = False
                self._fade_timer.stop()
        else:
            self._opacity = max(0.0, self._opacity - 0.16)
            if self._opacity <= 0.01:
                self._opacity = 0.0
                self._fading = False
                self._fade_timer.stop()
                if self._hide_after_fade:
                    self._hide_after_fade = False
                    self.hide()
        self.update()

    def fade_in(self):
        self._hide_after_fade = False
        if self.isVisible() and self._fading and self._fade_dir > 0:
            return
        was_hidden = not self.isVisible()
        if was_hidden:
            # 从当前透明度接着渐入，别每次硬重置造成闪烁
            if self._opacity < 0.05:
                self._opacity = 0.18
            self.setVisible(True)
            try:
                self.raise_()
            except Exception:
                pass
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._fade_dir = 1
        self._fading = True
        self._fade_timer.start()
        self.update()

    def fade_out(self, hide_after=True):
        if self._fading and self._fade_dir < 0:
            return
        if not self.isVisible():
            self._opacity = 0.0
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            return
        self._fade_dir = -1
        self._fading = True
        self._hide_after_fade = hide_after
        # 淡出期间不再拦截鼠标点击
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._fade_timer.start()

    def show_at_top(self):
        # 兼容旧调用：不再无条件显示，交给状态机裁决
        self.guard()

    def _stop_fade(self):
        self._fading = False
        self._fade_timer.stop()

    # ---------- 目标状态机 ----------

    def set_cast_mode(self, on):
        """进入/退出观影态。观影态下岛自动隐藏，避免挡住视频画面。"""
        on = bool(on)
        if self._cast_mode == on:
            return
        self._cast_mode = on
        if on:
            self._wake_until = 0.0
            self._cast_override_until = 0.0
        else:
            # 停止播放后播放器状态可能异步回落（还报 playing），
            # 短暂屏蔽兜底判定，让岛立刻回到常驻而不是再藏 350ms
            self._cast_override_until = time.monotonic() + 0.8
        self.guard()

    def wake(self, seconds=2.5):
        """主动叫窗口 / 顶部热区：临时唤出，超时自动收回。"""
        self._wake_until = time.monotonic() + seconds
        self.guard()

    def _playing_now(self):
        """兜底：即使上层忘了通知，也自己看一眼播放器与全屏状态。"""
        try:
            if self.main is None:
                return False
            p = getattr(self.main, 'player', None)
            if p is not None and p.is_playing():
                return True
            if self.main.isFullScreen():
                return True
        except Exception:
            pass
        return False

    def _in_cast(self):
        if self._cast_mode:
            return True
        if time.monotonic() < self._cast_override_until:
            return False
        return self._playing_now()

    def _cursor_pos(self):
        return QCursor.pos()

    def _hotzone(self):
        """观影态下把鼠标顶到屏幕上沿中间区域，可临时唤出控制条。"""
        try:
            geo = self._screen_geo()
            if geo is None:
                return False
            pos = self._cursor_pos()
            # 淡出过程中别再用岛自身矩形判定：岛此刻虽还 visible，
            # 但鼠标停在上面会把淡出反转成淡入，岛就永远退不下去
            if self.isVisible() and not (self._fading and self._fade_dir < 0):
                r = self.geometry().adjusted(-14, -14, 14, 14)
                if r.contains(pos):
                    return True
            band = QRect(geo.left() + geo.width() // 4, geo.top(),
                         geo.width() // 2, 24)
            return band.contains(pos)
        except Exception:
            return False

    def _desired_visible(self):
        now = time.monotonic()
        # 文件传输优先：传文件/完成提示必须弹出，哪怕正在放视频
        if self._transfer_on or self._transfer_done:
            return True
        if now < self._suppress_until:
            return False
        if self._in_cast():
            # 正在淡出就先让它淡完，别被热区当场翻转成淡入
            if self._fading and self._fade_dir < 0:
                return False
            if self._hotzone():
                self._wake_until = now + 2.5
                return True
            return now < self._wake_until
        # 空闲：常驻前台，主窗口最小化 / 收进托盘也不消失
        return True

    def guard(self):
        if self.main is None:
            if self.isVisible():
                self._stop_fade()
                self.hide()
            return
        # 屏幕几何（换显示器 / 改分辨率 / DPI）变化时自适应重新居中
        # 传输中同样检测，不再 early return
        geo = self._screen_geo()
        if geo is not None:
            key = (geo.x(), geo.y(), geo.width(), geo.height())
            if key != self._geo_key:
                self._geo_key = key
                self.reposition()
        want = self._desired_visible()
        if want:
            if not self.isVisible() or (self._fading and self._fade_dir < 0):
                self.fade_in()
        else:
            if self.isVisible() and not (self._fading and self._fade_dir < 0):
                self.fade_out(hide_after=True)

    def set_compact(self, on):
        if self._transfer_on:
            return
        if self._compact == on:
            return
        self._compact = on
        for w in (self.name_label, self.state_label, self.time_label,
                  self.vol, self.btn_stop, self.btn_more, self.btn_hide):
            w.setVisible(not on)
        self.setFixedHeight(30 if on else 46)
        self.reposition()
        self.update()

    # ---------- 文件传输模式 ----------

    def begin_transfer(self, filename):
        self._transfer_seq += 1
        self._transfer_on = True
        self._transfer_done = False
        self._compact = False
        self._suppress_until = 0.0
        self._wake_until = 0.0
        # 传输态只留文件名 + 进度条；顺便把上次 compact 藏掉的控件复位，
        # 避免从观影态起传时残留旧布局
        for w in (self.dot, self.name_label, self.state_label, self.stretch,
                  self.ctrl, self.vol, self.btn_more, self.btn_hide):
            w.setVisible(False)
        self.transfer_box.setVisible(True)
        self.t_name.setText(self._elide(filename, 34))
        self.t_bar.set_value(0)
        self.t_sub.setStyleSheet(
            'color:#9a9aa2; font-size:10px; background:transparent;')
        self.t_sub.setText('0%   \u51c6\u5907\u4e2d\u2026')
        self.setFixedHeight(66)
        self.reposition()
        # 传输强制弹出：走 fade_in 才能恢复鼠标事件与动画状态机
        self.fade_in()
        self._opacity = 1.0
        self.update()

    def update_transfer(self, filename, percent, speed_text=''):
        # 完成后又收到乱序进度包 / 上一轮已收尾：重新起一轮，
        # 否则完成态会一直挂着且 transfer_box 已被隐藏
        if not self._transfer_on or self._transfer_done:
            self.begin_transfer(filename)
        self.t_name.setText(self._elide(filename, 34))
        self.t_bar.set_value(percent)
        sub = '%d%%' % int(percent)
        if speed_text:
            sub += '   ' + speed_text
        self.t_sub.setText(sub)
        self.update()

    def finish_transfer(self, filename, saved_path):
        self._transfer_done = True
        base = os.path.basename(filename) or filename
        self.t_name.setText('\u5df2\u5b8c\u6210 \u00b7 ' + self._elide(base, 30))
        self.t_bar.set_value(100)
        self.t_sub.setStyleSheet(
            'color:#9a9aa2; font-size:10px; background:transparent;')
        self.t_sub.setText('\u6b63\u5728\u6253\u5f00\u6587\u4ef6\u6240\u5728\u4f4d\u7f6e\u2026')
        self.setFixedHeight(66)
        self.reposition()
        self.fade_in()
        self._opacity = 1.0
        self.update()
        seq = self._transfer_seq

        def _late():
            # 2.4s 内窗口可能已被销毁，别让回调在退出时抛一串异常
            try:
                self._end_transfer(seq)
            except Exception:
                pass

        QTimer.singleShot(2400, _late)

    def fail_transfer(self, filename, reason=''):
        """接收中断 / 残缺文件：提示失败后自动收起，绝不卡在传输态。"""
        if not self._transfer_on:
            self.begin_transfer(filename)
        self._transfer_done = True
        base = os.path.basename(filename) or filename
        self.t_name.setText('\u63a5\u6536\u5931\u8d25 \u00b7 ' + self._elide(base, 28))
        self.t_bar.set_value(0)
        self.t_sub.setStyleSheet(
            'color:#ff8b8b; font-size:10px; background:transparent;')
        self.t_sub.setText(reason or '\u4f20\u8f93\u4e2d\u65ad\uff0c\u6587\u4ef6\u672a\u4fdd\u5b58')
        self.setFixedHeight(66)
        self.reposition()
        self.fade_in()
        self._opacity = 1.0
        self.update()
        seq = self._transfer_seq

        def _late():
            try:
                self._end_transfer(seq)
            except Exception:
                pass

        QTimer.singleShot(2600, _late)

    def _end_transfer(self, seq=None):
        # 旧文件的完成定时器不许掐掉已经开始的新一轮传输
        if seq is not None and seq != self._transfer_seq:
            return
        if not self._transfer_on:
            return
        self._transfer_on = False
        self._transfer_done = False
        self.transfer_box.setVisible(False)
        # 观影态下恢复成紧凑形态，别把整条控制栏糊在视频上
        compact = self._in_cast()
        self._compact = compact
        for w in (self.dot, self.name_label, self.state_label, self.stretch,
                  self.ctrl, self.vol, self.btn_more, self.btn_hide,
                  self.time_label, self.btn_stop):
            w.setVisible(True)
        if compact:
            for w in (self.name_label, self.state_label, self.time_label,
                      self.vol, self.btn_stop, self.btn_more, self.btn_hide):
                w.setVisible(False)
            self.setFixedHeight(30)
        else:
            self.setFixedHeight(46)
        self.reposition()
        self._opacity = 1.0
        self.update()
        self._wake_until = 0.0
        if compact:
            # 观影态：完成提示淡出，并留静默期，防止 guard 立刻把岛拉回来
            self._suppress_until = time.monotonic() + 3.0
            self.fade_out(hide_after=True)
        else:
            # 空闲态：只收起传输条，胶囊立刻回到常驻，别整条闪一下
            self._suppress_until = 0.0
            self.fade_in()
            self._opacity = 1.0
            self.update()

    @staticmethod
    def _elide(text, maxc):
        if not text:
            return ''
        if len(text) <= maxc:
            return text
        return text[:maxc - 1] + '\u2026'

    # ---------- 布局 ----------

    def _screen_geo(self):
        try:
            scr = None
            mw = self.main
            if mw is not None:
                try:
                    if mw.isVisible() and not mw.isMinimized():
                        scr = mw.screen()
                except Exception:
                    scr = None
            if scr is None:
                scr = QApplication.screenAt(QCursor.pos())
            if scr is None:
                scr = QApplication.primaryScreen()
            return scr.availableGeometry()
        except Exception:
            return None

    def reposition(self):
        mw = self.main
        try:
            if mw is None:
                return
            if self._transfer_on:
                h = 66
            else:
                h = 30 if self._compact else 46
            geo = self._screen_geo()
            if self._transfer_on:
                w = 460
            elif self._compact:
                w = 170
            else:
                w = min(560, max(460, int((geo.width() if geo else 900) * 0.42)))
            if geo is not None:
                x = geo.center().x() - w // 2
                y = geo.top() + 10
            else:
                tl = mw.mapToGlobal(QPoint(0, 0))
                x = tl.x() + (mw.width() - w) // 2
                y = tl.y() + 8
            if w != self._last_w or h != self._last_h:
                self._last_w = w
                self._last_h = h
                self.setFixedWidth(w)
                self.setFixedHeight(h)
            self.move(x, y)
            self.update()
        except Exception:
            pass

    def set_state(self, text, playing=False):
        self.state_label.setText(text)
        self.dot.setStyleSheet(
            'color:%s; font-size:13px; background:transparent;'
            % ('#39ff88' if playing else '#8a8a92'))
        self.btn_play.setText('\u23f8' if playing else '\u25b6')

    def set_time(self, text):
        self.time_label.setText(text)
