import os

from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import (QPainter, QColor, QPainterPath, QPen, QFont,
                         QLinearGradient, QBrush, QFontMetrics)
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
        self._radius = 23
        self._fading = False
        self._fade_dir = 1
        self._hide_after_fade = False
        self._transfer_on = False
        self._transfer_done = False
        self._last_w = 0
        self._last_h = 0
        self._geo_key = None

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
        if self._fading and self._fade_dir > 0:
            return
        was_hidden = not self.isVisible()
        if was_hidden:
            self.setVisible(True)
            try:
                self.raise_()
            except Exception:
                pass
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._fade_dir = 1
        self._fading = True
        if self._opacity < 0.99:
            self._opacity = 0.18
        self._fade_timer.start()
        self.update()

    def fade_out(self, hide_after=True):
        if not self.isVisible():
            return
        self._fade_dir = -1
        self._fading = True
        self._hide_after_fade = hide_after
        self._fade_timer.start()

    def show_at_top(self):
        if self.main is None:
            return
        self.reposition()
        self.fade_in()

    def _stop_fade(self):
        self._fading = False
        self._fade_timer.stop()

    def _eligible(self):
        # 只要应用还在，灵动岛就常驻前台，不因主窗口最小化/收托盘而消失
        return self.main is not None

    def guard(self):
        if self._transfer_on:
            return
        if self.main is None:
            if self.isVisible():
                self.hide()
            return
        if not self.isVisible():
            self.show_at_top()
            return
        # 屏幕几何（换显示器/改分辨率/DPI）变化时自适应重新居中
        geo = self._screen_geo()
        if geo is not None:
            key = (geo.x(), geo.y(), geo.width(), geo.height())
            if key != self._geo_key:
                self._geo_key = key
                self.reposition()

    def set_compact(self, on):
        if self._transfer_on:
            return
        if self._compact == on:
            return
        self._compact = on
        for w in (self.name_label, self.state_label, self.time_label,
                  self.vol, self.btn_stop, self.btn_more, self.btn_hide):
            w.setVisible(not on)
        self._radius = 15 if on else 23
        self.setFixedHeight(30 if on else 46)
        self.reposition()
        self.update()

    # ---------- 文件传输模式 ----------

    def begin_transfer(self, filename):
        self._transfer_on = True
        self._transfer_done = False
        self._compact = False
        for w in (self.dot, self.name_label, self.state_label, self.stretch,
                  self.ctrl, self.vol, self.btn_more, self.btn_hide):
            w.setVisible(False)
        self.transfer_box.setVisible(True)
        self.t_name.setText(self._elide(filename, 34))
        self.t_bar.set_value(0)
        self.t_sub.setText('0%   \u51c6\u5907\u4e2d\u2026')
        self._radius = 33
        self.setFixedHeight(66)
        if not self.isVisible():
            self.setVisible(True)
        self.reposition()
        try:
            self.raise_()
        except Exception:
            pass
        self._opacity = 1.0
        self.update()

    def update_transfer(self, filename, percent, speed_text=''):
        self._transfer_on = True
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
        self.t_sub.setText('\u6b63\u5728\u6253\u5f00\u6587\u4ef6\u6240\u5728\u4f4d\u7f6e\u2026')
        self._radius = 33
        self.setFixedHeight(66)
        self.reposition()
        self._opacity = 1.0
        self.update()
        QTimer.singleShot(2400, self._end_transfer)

    def _end_transfer(self):
        if not self._transfer_on:
            return
        self._transfer_on = False
        self._transfer_done = False
        self.transfer_box.setVisible(False)
        for w in (self.dot, self.name_label, self.state_label, self.stretch,
                  self.ctrl, self.vol, self.btn_more, self.btn_hide):
            w.setVisible(True)
        self._radius = 23
        self.setFixedHeight(46)
        self.reposition()
        self._opacity = 1.0
        self.update()
        self.fade_out(hide_after=True)

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
                from PyQt6.QtGui import QCursor
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
                w = 150
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
