import sys
import ctypes
import json
import math
import random
import re
import shutil
import string
import time
import os
import tempfile
import threading
from pathlib import Path
from ctypes import wintypes

from PySide6.QtCore import Qt, QUrl, QPoint, QPointF, QRectF, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QBrush,
    QDesktopServices,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QPen,
    QPalette,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QStyle,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from telethon.sync import TelegramClient
from telethon.errors import (
    AuthRestartError,
    ChatAdminRequiredError,
    FloodWaitError,
    InputUserDeactivatedError,
    PasswordHashInvalidError,
    PeerFloodError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNotOccupiedError,
    PhoneNumberInvalidError,
    PhoneNumberUnoccupiedError,
    SendCodeUnavailableError,
    SessionPasswordNeededError,
    UserAlreadyParticipantError,
    UserBannedInChannelError,
    UserChannelsTooMuchError,
    UserKickedError,
    UserNotMutualContactError,
    UserPrivacyRestrictedError,
    UserNotParticipantError,
)
from telethon.tl.functions.channels import GetParticipantRequest, InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.contacts import ResolvePhoneRequest


ADMIN_USERNAME = "kun_amra"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _protect_for_current_user(data):
    if os.name != "nt":
        raise OSError("Encrypted credential storage is supported only on Windows.")

    input_buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_byte))
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    protect_data = crypt32.CryptProtectData
    protect_data.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    protect_data.restype = wintypes.BOOL
    if not protect_data(
        ctypes.byref(input_blob),
        "Telegram Member Manager credentials",
        None,
        None,
        None,
        0x1,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect_for_current_user(data):
    if os.name != "nt":
        raise OSError("Encrypted credential storage is supported only on Windows.")

    input_buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_byte))
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    unprotect_data = crypt32.CryptUnprotectData
    unprotect_data.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    unprotect_data.restype = wintypes.BOOL
    if not unprotect_data(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


class AnimatedLogo(QWidget):
    """Animated floating Telegram logo with gentle aerodynamics and hover reaction."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(62, 62)
        self.phase = 0.0
        self.is_hovered = False
        self.show_checkmark = False

        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def set_active(self, active: bool):
        if active:
            if not self.timer.isActive():
                self.timer.start()
        else:
            if self.timer.isActive():
                self.timer.stop()

    def set_checkmark(self, show: bool):
        self.show_checkmark = show
        self.update()

    def _tick(self):
        self.phase += 0.05
        if self.phase > math.tau * 100:
            self.phase = 0.0
        self.update()

    def enterEvent(self, event):
        self.is_hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        hover_lift = -2.0 if self.is_hovered else 0.0
        dy = math.sin(self.phase * 2.6) * 3.0 + hover_lift
        tilt = math.sin(self.phase * 2.2) * 3.5

        # Soft dynamic shadow underneath
        shadow_rect = QRectF(7, 49 - dy * 0.3, 48 + dy * 0.5, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(3, 16, 28, 90))
        painter.drawEllipse(shadow_rect)

        # Circular gradient badge
        circle_rect = QRectF(5, 5 + dy, 52, 52)
        gradient = QLinearGradient(circle_rect.topLeft(), circle_rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#35c7e8"))
        gradient.setColorAt(1.0, QColor("#1689d4"))

        if self.is_hovered:
            glow_pen = QPen(QColor(100, 220, 255, 140), 2.5)
            painter.setPen(glow_pen)
        else:
            painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(gradient)
        painter.drawEllipse(circle_rect)

        # Paper Airplane with float & banking roll
        center_x = circle_rect.center().x()
        center_y = circle_rect.center().y()

        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(tilt)

        scale = 0.38
        painter.scale(scale, scale)
        painter.translate(-64, -64)

        plane = QPainterPath()
        plane.moveTo(27, 61)
        plane.lineTo(101, 31)
        plane.lineTo(75, 99)
        plane.lineTo(59, 74)
        plane.lineTo(44, 85)
        plane.lineTo(48, 65)
        plane.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(plane)

        # Crisp fold line
        painter.setPen(QPen(QColor("#9be8f6"), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(48, 65, 101, 31)
        painter.restore()

        # Checkmark when authorized
        if self.show_checkmark:
            badge_rect = QRectF(38, 38 + dy, 18, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#4caf50"))
            painter.drawEllipse(badge_rect)
            check_pen = QPen(QColor("#ffffff"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(check_pen)
            painter.drawLine(43, 47 + dy, 46, 50 + dy)
            painter.drawLine(46, 50 + dy, 51, 44 + dy)


class AnimatedHeroCard(QFrame):
    """Dynamic animated hero card with ambient waving gradient, light beam shimmer, and particles."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hero")
        self.phase = 0.0
        self.shimmer_pos = -0.5

        self.particles = []
        for _ in range(6):
            self.particles.append({
                "x": random.uniform(0.0, 1.0),
                "y": random.uniform(0.1, 0.9),
                "r": random.uniform(1.2, 2.8),
                "speed": random.uniform(0.0004, 0.0013),
                "alpha_base": random.uniform(40, 130),
                "alpha_phase": random.uniform(0, math.tau),
            })

        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._animate_step)
        self.timer.start()

    def set_active(self, active: bool):
        if active:
            if not self.timer.isActive():
                self.timer.start()
        else:
            if self.timer.isActive():
                self.timer.stop()

    def _animate_step(self):
        self.phase += 0.035
        if self.phase > math.tau * 100:
            self.phase = 0.0

        self.shimmer_pos += 0.009
        if self.shimmer_pos > 2.6:
            self.shimmer_pos = -0.6

        for p in self.particles:
            p["x"] += p["speed"]
            if p["x"] > 1.05:
                p["x"] = -0.05
                p["y"] = random.uniform(0.1, 0.9)

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        h = float(self.height())
        radius = 16.0

        clip_path = QPainterPath()
        clip_path.addRoundedRect(0.5, 0.5, w - 1, h - 1, radius, radius)
        painter.setClipPath(clip_path)

        # Dynamic ambient oceanic wave gradient
        x1 = w * (0.0 + 0.12 * math.sin(self.phase * 0.45))
        y1 = h * (0.0 + 0.10 * math.cos(self.phase * 0.40))
        x2 = w * (1.0 + 0.12 * math.cos(self.phase * 0.50))
        y2 = h * (1.0 + 0.10 * math.sin(self.phase * 0.45))

        grad = QLinearGradient(x1, y1, x2, y2)
        grad.setColorAt(0.0, QColor("#083452"))
        c_mid = QColor(
            int(10 + 6 * math.sin(self.phase * 0.6)),
            int(74 + 14 * math.cos(self.phase * 0.7)),
            int(118 + 18 * math.sin(self.phase * 0.5)),
        )
        grad.setColorAt(0.5, c_mid)
        grad.setColorAt(1.0, QColor("#0c7da6"))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRect(self.rect())

        # Ambient floating glowing particles
        for p in self.particles:
            px = p["x"] * w
            py = p["y"] * h
            alpha = int(p["alpha_base"] + 35 * math.sin(self.phase * 1.6 + p["alpha_phase"]))
            alpha = max(10, min(220, alpha))
            painter.setBrush(QColor(190, 238, 255, alpha))
            painter.drawEllipse(QPointF(px, py), p["r"], p["r"])

        # Shimmer light beam sweep
        if -0.3 <= self.shimmer_pos <= 1.3:
            sx = self.shimmer_pos * w
            shimmer_grad = QLinearGradient(sx - 75, 0, sx + 75, h)
            shimmer_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            shimmer_grad.setColorAt(0.5, QColor(255, 255, 255, 28))
            shimmer_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(shimmer_grad)
            painter.drawRect(self.rect())

        # Outer smooth border
        painter.setClipping(False)
        border_pen = QPen(QColor("#1c6e92"), 1.2)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0.5, 0.5, w - 1, h - 1, radius, radius)


class AnimatedBadge(QWidget):
    """Pulsing status badge with live glowing neon indicator dot."""
    def __init__(self, text="TELEGRAM TOOL", parent=None):
        super().__init__(parent)
        self.text = text
        self.phase = 0.0
        self.setFixedSize(135, 28)

        self.timer = QTimer(self)
        self.timer.setInterval(75)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def set_active(self, active: bool):
        if active:
            if not self.timer.isActive():
                self.timer.start()
        else:
            if self.timer.isActive():
                self.timer.stop()

    def set_text(self, text):
        self.text = text
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(text)
        self.setFixedWidth(max(130, text_w + 34))
        self.update()

    def _tick(self):
        self.phase += 0.06
        if self.phase > math.tau * 100:
            self.phase = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        h = float(self.height())
        radius = 9.0

        pulse = 0.5 + 0.5 * math.sin(self.phase * 2.0)
        bg_alpha = int(22 + 18 * pulse)
        border_alpha = int(75 + 55 * pulse)

        painter.setPen(QPen(QColor(255, 255, 255, border_alpha), 1.0))
        painter.setBrush(QColor(255, 255, 255, bg_alpha))
        painter.drawRoundedRect(0.5, 0.5, w - 1, h - 1, radius, radius)

        # Pulsing active neon dot
        dot_alpha = int(180 + 75 * pulse)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(42, 235, 255, dot_alpha))
        painter.drawEllipse(QPointF(12.0, h / 2.0), 3.2, 3.2)

        # Text
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(22, 0, w - 24, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)


class AudioManager:
    """Audio notifications and sound effects for Telegram Member Manager."""
    def __init__(self):
        self.enabled = True

    def play_success(self):
        if not self.enabled:
            return
        threading.Thread(target=self._beep_success, daemon=True).start()

    def play_complete(self):
        if not self.enabled:
            return
        threading.Thread(target=self._beep_complete, daemon=True).start()

    def play_alert(self):
        if not self.enabled:
            return
        threading.Thread(target=self._beep_alert, daemon=True).start()

    def play_stop(self):
        if not self.enabled:
            return
        threading.Thread(target=self._beep_stop, daemon=True).start()

    @staticmethod
    def _beep_success():
        try:
            import winsound
            winsound.Beep(587, 100)
            winsound.Beep(880, 160)
        except Exception:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
            except Exception:
                pass

    @staticmethod
    def _beep_complete():
        try:
            import winsound
            winsound.Beep(523, 100)
            winsound.Beep(659, 100)
            winsound.Beep(784, 220)
        except Exception:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

    @staticmethod
    def _beep_alert():
        try:
            import winsound
            winsound.Beep(370, 120)
            winsound.Beep(294, 200)
        except Exception:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass

    @staticmethod
    def _beep_stop():
        try:
            import winsound
            winsound.Beep(440, 120)
            winsound.Beep(330, 160)
        except Exception:
            pass


class CustomIcons:
    """Generates crisp vector-drawn icons for actions and menus."""
    @staticmethod
    def _create_pixmap(size=32):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        return pix, p

    @classmethod
    def globe(cls, color="#38bdf8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawEllipse(4, 4, 24, 24)
        p.drawEllipse(10, 4, 12, 24)
        p.drawLine(4, 16, 28, 16)
        p.end()
        return QIcon(pix)

    @classmethod
    def audio(cls, enabled=True):
        pix, p = cls._create_pixmap()
        color = "#38bdf8" if enabled else "#94a3b8"
        p.setPen(QPen(QColor(color), 2.0))
        path = QPainterPath()
        path.moveTo(6, 12)
        path.lineTo(11, 12)
        path.lineTo(17, 7)
        path.lineTo(17, 25)
        path.lineTo(11, 20)
        path.lineTo(6, 20)
        path.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(path)
        if enabled:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(19, 10, 8, 12, -60 * 16, 120 * 16)
            p.drawArc(22, 6, 12, 20, -60 * 16, 120 * 16)
        else:
            p.setPen(QPen(QColor("#ef4444"), 2.2))
            p.drawLine(6, 6, 26, 26)
        p.end()
        return QIcon(pix)

    @classmethod
    def upload(cls, color="#38bdf8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        path = QPainterPath()
        path.moveTo(8, 4)
        path.lineTo(19, 4)
        path.lineTo(24, 9)
        path.lineTo(24, 28)
        path.lineTo(8, 28)
        path.closeSubpath()
        p.drawPath(path)
        arrow = QPainterPath()
        arrow.moveTo(16, 23)
        arrow.lineTo(16, 13)
        arrow.moveTo(12, 17)
        arrow.lineTo(16, 13)
        arrow.lineTo(20, 17)
        p.drawPath(arrow)
        p.end()
        return QIcon(pix)

    @classmethod
    def search(cls, color="#38bdf8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.2))
        p.drawEllipse(6, 6, 13, 13)
        p.drawLine(16, 16, 25, 25)
        p.end()
        return QIcon(pix)

    @classmethod
    def play(cls, color="#10b981"):
        pix, p = cls._create_pixmap()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        path = QPainterPath()
        path.moveTo(9, 6)
        path.lineTo(25, 16)
        path.lineTo(9, 26)
        path.closeSubpath()
        p.drawPath(path)
        p.end()
        return QIcon(pix)

    @classmethod
    def stop(cls, color="#ef4444"):
        pix, p = cls._create_pixmap()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(7, 7, 18, 18, 3, 3)
        p.end()
        return QIcon(pix)

    @classmethod
    def clear(cls, color="#94a3b8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawArc(7, 7, 18, 18, 45 * 16, 270 * 16)
        p.drawLine(16, 4, 20, 8)
        p.drawLine(16, 12, 20, 8)
        p.end()
        return QIcon(pix)

    @classmethod
    def dice(cls, color="#38bdf8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawRoundedRect(6, 6, 20, 20, 4, 4)
        p.setBrush(QColor(color))
        p.drawEllipse(10, 10, 3, 3)
        p.drawEllipse(15, 15, 3, 3)
        p.drawEllipse(19, 19, 3, 3)
        p.end()
        return QIcon(pix)

    @classmethod
    def group(cls, color="#38bdf8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawEllipse(11, 6, 10, 10)
        path = QPainterPath()
        path.moveTo(6, 26)
        path.quadTo(6, 19, 16, 19)
        path.quadTo(26, 19, 26, 26)
        p.drawPath(path)
        p.end()
        return QIcon(pix)

    @classmethod
    def key(cls, color="#eab308"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawEllipse(7, 7, 10, 10)
        p.drawLine(15, 15, 25, 25)
        p.drawLine(21, 21, 24, 18)
        p.drawLine(23, 23, 26, 20)
        p.end()
        return QIcon(pix)

    @classmethod
    def info(cls, color="#38bdf8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawEllipse(5, 5, 22, 22)
        p.setBrush(QColor(color))
        p.drawEllipse(15, 9, 2, 2)
        p.drawLine(16, 14, 16, 22)
        p.end()
        return QIcon(pix)

    @classmethod
    def login(cls, color="#10b981"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawRoundedRect(5, 5, 22, 22, 4, 4)
        p.drawLine(10, 16, 20, 16)
        p.drawLine(16, 12, 20, 16)
        p.drawLine(16, 20, 20, 16)
        p.end()
        return QIcon(pix)

    @classmethod
    def exit(cls, color="#ef4444"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawArc(7, 7, 18, 18, -45 * 16, 270 * 16)
        p.drawLine(16, 5, 16, 14)
        p.end()
        return QIcon(pix)

    @classmethod
    def user_plus(cls, color="#38bdf8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawEllipse(7, 6, 9, 9)
        path = QPainterPath()
        path.moveTo(3, 24)
        path.quadTo(3, 18, 12, 18)
        path.quadTo(20, 18, 20, 24)
        p.drawPath(path)
        # Plus sign
        p.drawLine(23, 10, 23, 16)
        p.drawLine(20, 13, 26, 13)
        p.end()
        return QIcon(pix)


    @classmethod
    def trash(cls, color="#ef4444"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 1.8))
        p.drawLine(8, 9, 24, 9)
        p.drawLine(13, 6, 19, 6)
        path = QPainterPath()
        path.moveTo(10, 9)
        path.lineTo(11, 24)
        path.lineTo(21, 24)
        path.lineTo(22, 9)
        p.drawPath(path)
        p.drawLine(14, 12, 14, 21)
        p.drawLine(18, 12, 18, 21)
        p.end()
        return QIcon(pix)

    @classmethod
    def disk(cls, color="#38bdf8"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 1.8))
        p.drawRoundedRect(5, 7, 22, 18, 3, 3)
        p.drawLine(5, 19, 27, 19)
        p.setBrush(QColor(color))
        p.drawEllipse(21, 21, 2, 2)
        p.drawEllipse(17, 21, 2, 2)
        p.end()
        return QIcon(pix)

    @classmethod
    def broom(cls, color="#10b981"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawLine(23, 5, 15, 15)
        path = QPainterPath()
        path.moveTo(11, 14)
        path.lineTo(19, 18)
        path.lineTo(15, 27)
        path.lineTo(7, 23)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(9, 21, 13, 27)
        p.end()
        return QIcon(pix)

    @classmethod
    def speed(cls, color="#f59e0b"):
        pix, p = cls._create_pixmap()
        p.setPen(QPen(QColor(color), 2.0))
        p.drawArc(5, 6, 22, 22, -30 * 16, 240 * 16)
        p.drawLine(16, 17, 22, 11)
        p.setBrush(QColor(color))
        p.drawEllipse(14, 15, 4, 4)
        p.end()
        return QIcon(pix)


class PCStorageManager:
    """Calculates PC storage & memory metrics and performs safe cache cleanup."""

    @staticmethod
    def get_storage_info() -> dict:
        temp_dir = tempfile.gettempdir()
        drive_path = os.path.splitdrive(temp_dir)[0] or "C:"
        drive_root = drive_path + "\\" if not drive_path.endswith("\\") else drive_path

        try:
            usage = shutil.disk_usage(drive_root)
            drive_total_gb = usage.total / (1024 ** 3)
            drive_used_gb = usage.used / (1024 ** 3)
            drive_free_gb = usage.free / (1024 ** 3)
            drive_free_pct = (usage.free / usage.total) * 100.0 if usage.total else 0.0
            drive_used_pct = 100.0 - drive_free_pct
        except Exception:
            drive_total_gb = drive_used_gb = drive_free_gb = drive_free_pct = drive_used_pct = 0.0

        ram_total_gb = 0.0
        ram_free_gb = 0.0
        ram_used_pct = 0.0
        try:
            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_total_gb = stat.ullTotalPhys / (1024 ** 3)
                ram_free_gb = stat.ullAvailPhys / (1024 ** 3)
                ram_used_pct = float(stat.dwMemoryLoad)
        except Exception:
            pass

        app_storage_bytes = 0
        appdata_dir = os.getenv("APPDATA")
        if appdata_dir:
            app_folder = Path(appdata_dir) / "TelegramMemberManager"
            if app_folder.is_dir():
                for root, _, files in os.walk(app_folder):
                    for f in files:
                        try:
                            app_storage_bytes += os.path.getsize(os.path.join(root, f))
                        except Exception:
                            pass

        cleanable_bytes = 0
        cleanable_count = 0
        meipass = getattr(sys, "_MEIPASS", None)
        now = time.time()
        try:
            import glob
            mei_patterns = glob.glob(os.path.join(temp_dir, "_MEI*"))
            for mei in mei_patterns:
                if meipass and os.path.abspath(mei) == os.path.abspath(meipass):
                    continue
                try:
                    mtime = os.path.getmtime(mei)
                    if (now - mtime) > 600:
                        item_size = 0
                        for root, _, files in os.walk(mei):
                            for f in files:
                                try:
                                    item_size += os.path.getsize(os.path.join(root, f))
                                except Exception:
                                    pass
                        cleanable_bytes += item_size
                        cleanable_count += 1
                except Exception:
                    pass
        except Exception:
            pass

        return {
            "drive": drive_path,
            "drive_total_gb": drive_total_gb,
            "drive_used_gb": drive_used_gb,
            "drive_free_gb": drive_free_gb,
            "drive_free_pct": drive_free_pct,
            "drive_used_pct": drive_used_pct,
            "ram_total_gb": ram_total_gb,
            "ram_free_gb": ram_free_gb,
            "ram_used_pct": ram_used_pct,
            "app_storage_mb": app_storage_bytes / (1024 ** 2),
            "cleanable_mb": cleanable_bytes / (1024 ** 2),
            "cleanable_count": cleanable_count,
            "is_low_space": drive_free_pct < 10.0 or drive_free_gb < 15.0,
        }

    @staticmethod
    def clean_cache() -> tuple[float, int]:
        temp_dir = tempfile.gettempdir()
        meipass = getattr(sys, "_MEIPASS", None)
        now = time.time()
        freed_bytes = 0
        items_cleaned = 0

        try:
            import glob
            mei_patterns = glob.glob(os.path.join(temp_dir, "_MEI*"))
            for mei in mei_patterns:
                if meipass and os.path.abspath(mei) == os.path.abspath(meipass):
                    continue
                try:
                    mtime = os.path.getmtime(mei)
                    if (now - mtime) > 600:
                        size = 0
                        for root, _, files in os.walk(mei):
                            for f in files:
                                try:
                                    size += os.path.getsize(os.path.join(root, f))
                                except Exception:
                                    pass
                        shutil.rmtree(mei, ignore_errors=True)
                        if not os.path.exists(mei):
                            freed_bytes += size
                            items_cleaned += 1
                except Exception:
                    pass
        except Exception:
            pass

        return freed_bytes / (1024 ** 2), items_cleaned


class PCStorageDialog(QDialog):
    """Detailed dialog for PC storage calculation and one-click optimization."""
    def __init__(self, parent=None, storage_manager=None, translations_fn=None):
        super().__init__(parent)
        self.storage_manager = storage_manager or PCStorageManager
        self.tr_text = translations_fn or (lambda k, **kw: k)
        self.setWindowTitle(self.tr_text("dialog_pc_space_title"))
        self.setMinimumWidth(540)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #e2e8f0;
                font-family: 'Segoe UI', Tahoma, sans-serif;
            }
            QLabel {
                color: #cbd5e1;
            }
            QFrame#cardBox {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        self._build_ui()
        self.refresh_stats()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(22, 20, 22, 20)

        header_row = QHBoxLayout()
        header_icon = QLabel()
        header_icon.setPixmap(CustomIcons.disk("#38bdf8").pixmap(32, 32))
        header_row.addWidget(header_icon)

        header_title = QLabel(self.tr_text("dialog_pc_space_title"))
        header_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #38bdf8;")
        header_row.addWidget(header_title)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Drive C: Card
        drive_frame = QFrame()
        drive_frame.setObjectName("cardBox")
        drive_layout = QVBoxLayout(drive_frame)
        drive_layout.setSpacing(8)

        self.drive_title = QLabel("Drive C: (System Storage)")
        self.drive_title.setStyleSheet("font-weight: 700; color: #f8fafc;")
        drive_layout.addWidget(self.drive_title)

        self.drive_bar = QProgressBar()
        self.drive_bar.setRange(0, 100)
        self.drive_bar.setFixedHeight(20)
        drive_layout.addWidget(self.drive_bar)

        self.drive_details = QLabel()
        self.drive_details.setWordWrap(True)
        self.drive_details.setStyleSheet("color: #94a3b8; font-size: 12px;")
        drive_layout.addWidget(self.drive_details)
        layout.addWidget(drive_frame)

        # System RAM Card
        ram_frame = QFrame()
        ram_frame.setObjectName("cardBox")
        ram_layout = QVBoxLayout(ram_frame)
        ram_layout.setSpacing(8)

        self.ram_title = QLabel("System Memory (RAM)")
        self.ram_title.setStyleSheet("font-weight: 700; color: #a78bfa;")
        ram_layout.addWidget(self.ram_title)

        self.ram_bar = QProgressBar()
        self.ram_bar.setRange(0, 100)
        self.ram_bar.setFixedHeight(18)
        self.ram_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0f172a;
                border: 1px solid #475569;
                border-radius: 5px;
                text-align: center;
                color: #f1f5f9;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:1 #c084fc);
                border-radius: 4px;
            }
        """)
        ram_layout.addWidget(self.ram_bar)

        self.ram_details = QLabel()
        self.ram_details.setStyleSheet("color: #94a3b8; font-size: 12px;")
        ram_layout.addWidget(self.ram_details)
        layout.addWidget(ram_frame)

        # Cache & App Storage Card
        cache_frame = QFrame()
        cache_frame.setObjectName("cardBox")
        cache_layout = QVBoxLayout(cache_frame)
        cache_layout.setSpacing(8)

        cache_title = QLabel("Temporary Cache & App Storage")
        cache_title.setStyleSheet("font-weight: 700; color: #34d399;")
        cache_layout.addWidget(cache_title)

        self.cache_details = QLabel()
        self.cache_details.setStyleSheet("color: #cbd5e1; font-size: 13px;")
        cache_layout.addWidget(self.cache_details)

        tip_label = QLabel(self.tr_text("dialog_clean_tip"))
        tip_label.setStyleSheet("color: #64748b; font-size: 11px; font-style: italic;")
        tip_label.setWordWrap(True)
        cache_layout.addWidget(tip_label)
        layout.addWidget(cache_frame)

        # Bottom Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_clean = QPushButton(self.tr_text("btn_clean_cache").replace("&", "&&"))
        self.btn_clean.setIcon(CustomIcons.broom("#10b981"))
        self.btn_clean.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-weight: 700;
                padding: 8px 18px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #10b981;
            }
        """)
        self.btn_clean.clicked.connect(self._do_clean)

        self.btn_refresh = QPushButton(self.tr_text("btn_calculate_space").replace("&", "&&"))
        self.btn_refresh.setIcon(CustomIcons.speed("#38bdf8"))
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #38bdf8;
                border: 1px solid #0284c7;
                padding: 8px 14px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #0369a1;
                color: #ffffff;
            }
        """)
        self.btn_refresh.clicked.connect(self.refresh_stats)

        btn_close = QPushButton("Close")
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #e2e8f0;
                padding: 8px 16px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        btn_close.clicked.connect(self.accept)

        btn_row.addWidget(self.btn_clean)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def refresh_stats(self):
        info = self.storage_manager.get_storage_info()
        drive = info.get("drive", "C:")
        total = info.get("drive_total_gb", 0.0)
        free = info.get("drive_free_gb", 0.0)
        used = info.get("drive_used_gb", 0.0)
        free_pct = info.get("drive_free_pct", 0.0)
        used_pct = int(info.get("drive_used_pct", 0.0))

        self.drive_title.setText(f"Drive {drive} (Total: {total:.1f} GB)")
        self.drive_bar.setValue(used_pct)
        self.drive_bar.setFormat(f"Disk Used: {used_pct}% ({free:.1f} GB Free)")

        if info.get("is_low_space", False):
            self.drive_bar.setStyleSheet("""
                QProgressBar {
                    background-color: #0f172a;
                    border: 1px solid #dc2626;
                    border-radius: 5px;
                    text-align: center;
                    color: #fecaca;
                    font-size: 11px;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ef4444, stop:1 #f59e0b);
                    border-radius: 4px;
                }
            """)
            self.drive_details.setText(
                f"⚠️ LOW DISK SPACE: Used {used:.1f} GB / Free {free:.1f} GB ({free_pct:.1f}% free). "
                f"Windows needs at least 15 GB free to run smoothly."
            )
            self.drive_details.setStyleSheet("color: #f87171; font-size: 12px;")
        else:
            self.drive_bar.setStyleSheet("""
                QProgressBar {
                    background-color: #0f172a;
                    border: 1px solid #334155;
                    border-radius: 5px;
                    text-align: center;
                    color: #f1f5f9;
                    font-size: 11px;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #10b981);
                    border-radius: 4px;
                }
            """)
            self.drive_details.setText(f"Used {used:.1f} GB | Free {free:.1f} GB ({free_pct:.1f}% free) - Status: Healthy")
            self.drive_details.setStyleSheet("color: #34d399; font-size: 12px;")

        ram_total = info.get("ram_total_gb", 0.0)
        ram_free = info.get("ram_free_gb", 0.0)
        ram_used_pct = int(info.get("ram_used_pct", 0.0))
        self.ram_bar.setValue(ram_used_pct)
        self.ram_bar.setFormat(f"RAM Used: {ram_used_pct}% ({ram_free:.1f} GB Free)")
        self.ram_details.setText(f"Total: {ram_total:.1f} GB | Available: {ram_free:.1f} GB | In Use: {max(0.0, ram_total - ram_free):.1f} GB")

        cleanable_mb = info.get("cleanable_mb", 0.0)
        count = info.get("cleanable_count", 0)
        app_mb = info.get("app_storage_mb", 0.0)
        self.cache_details.setText(
            f"• Cleanable PyInstaller Temp Cache: <b>{cleanable_mb:.1f} MB</b> ({count} temporary items)<br>"
            f"• Telegram Member Manager App Data & Sessions: <b>{app_mb:.1f} MB</b>"
        )

    def _do_clean(self):
        self.btn_clean.setEnabled(False)
        self.btn_clean.setText("Cleaning...")
        QApplication.processEvents()
        freed_mb, count = self.storage_manager.clean_cache()
        self.refresh_stats()
        self.btn_clean.setEnabled(True)
        self.btn_clean.setText(self.tr_text("btn_clean_cache").replace("&", "&&"))
        if self.parent() and hasattr(self.parent(), "_update_storage_ui"):
            self.parent()._update_storage_ui()
            if hasattr(self.parent(), "audio_manager") and self.parent().audio_manager:
                self.parent().audio_manager.play_success()
        if freed_mb > 0.1 or count > 0:
            QMessageBox.information(
                self,
                self.tr_text("dialog_pc_space_title"),
                self.tr_text("msg_cleaned_success").format(freed_mb=freed_mb),
            )
        else:
            QMessageBox.information(
                self,
                self.tr_text("dialog_pc_space_title"),
                self.tr_text("msg_already_clean"),
            )

TRANSLATIONS = {
    "en": {
        "app_title": "Telegram Member Manager",
        "hero_title": "Member Studio",
        "hero_subtitle": "A simple workspace for your Telegram groups",
        "hero_badge": "TELEGRAM TOOL",
        "card_account": "CONNECTED ACCOUNTS (MULTI-ACCOUNT)",
        "card_account_hint": "Connect up to 25 Telegram accounts. When adding members, they will automatically share the work without duplicate invites (ចែកគ្នាធ្វើការ មិនជាន់គ្នា).",
        "connected_accounts_title": "Saved Telegram Accounts ({count} / 25):",
        "btn_add_account": "+ Connect / Add Account",
        "btn_remove_account": "Remove Account",
        "btn_clear_all_accounts": "Clear All",
        "btn_select_all": "Select All",
        "btn_deselect_all": "Deselect All",
        "max_per_account_label": "Max invites per account",
        "invites_suffix": " invites",
        "active_workers_status": "Active accounts: {active} of {total} (Max 25)",
        "rotation_mode_hint": "Accounts will rotate automatically per invite to share the work without collisions.",
        "api_id": "API ID",
        "api_id_ph": "Your numeric API ID",
        "api_hash": "API hash",
        "api_hash_ph": "Your API hash",
        "phone_number": "Phone number",
        "phone_ph": "Example: +85517271771 or 017271771",
        "api_help_hint": "Need API details? Get them from my.telegram.org.",
        "btn_get_api": "Get API ID and Hash",
        "btn_login": "Login with Telegram",
        "btn_confirm_account": "Confirm account",
        "not_signed_in": "Not signed in",
        "signed_in_as": "Signed in as {name}",
        "card_target": "TARGET GROUP",
        "card_target_hint": "Invites are sent only to the members in the list below.",
        "target_ph": "Target group link or username (@group_link)",
        "card_source": "SOURCE GROUP",
        "card_source_hint": "Fetch usernames or user IDs from a group where you can read the member list.",
        "source_ph": "Source group link or username (@group_link)",
        "btn_fetch": "Fetch members",
        "card_upload": "UPLOAD USERNAMES FROM TXT",
        "card_upload_hint": "Load usernames, phone numbers, or user IDs from a .txt file (one per line).",
        "upload_ph": "Select a .txt file containing usernames...",
        "btn_browse": "Browse file",
        "btn_start_file": "Start from file",
        "card_members": "MEMBER LIST",
        "card_members_hint": "Paste usernames, phone numbers, or numeric user IDs. Phone numbers are checked with Telegram automatically. Invite links are ignored.",
        "members_ph": "@telegram_user\n+85512345678\n123456789",
        "consent_check": "I have permission to invite these accounts.",
        "random_amount": "Random amount",
        "btn_select_random": "Select random",
        "btn_gen_random": "Generate random numbers",
        "btn_scan_phones": "Scan phones",
        "btn_upload_txt": "Upload TXT...",
        "delay_label": "Delay between invites",
        "delay_suffix": " sec",
        "btn_add_members": "Add members",
        "btn_clear": "Clear",
        "btn_stop": "Stop",
        "status_ready": "Ready",
        "admin_contact": "Admin contact: <a href=\"https://t.me/{username}\">@{username}</a>",
        "menu_tools": "Tools",
        "menu_language": "Language",
        "menu_audio": "Audio",
        "menu_help": "Help",
        "action_get_api": "Get API ID and Hash",
        "action_guide": "Telegram API guide",
        "action_scan_phones": "Scan phone numbers",
        "action_upload_txt": "Upload users (TXT)",
        "action_fetch_members": "Fetch members",
        "action_add_members": "Add members",
        "action_clear": "Clear fields",
        "action_stop": "Stop addition",
        "action_exit": "Exit",
        "action_lang_en": "English",
        "action_lang_km": "ភាសាខ្មែរ (Khmer)",
        "action_switch_lang": "Switch Language (English / ខ្មែរ)",
        "action_sound_toggle_on": "Sound Effects (Enabled)",
        "action_sound_toggle_off": "Sound Effects (Disabled)",
        "action_test_sound": "Play Test Sound",
        "action_tool_info": "Tool info",
        "action_contact_admin": "Contact admin (@{username})",
        "card_pc_space": "PC STORAGE & PERFORMANCE MONITOR",
        "card_pc_space_hint": "Monitor Drive C: storage, RAM memory, and clean temporary cache to keep your PC and tool ultra-smooth.",
        "storage_drive_status": "Drive {drive}  {free_gb:.1f} GB Free / {total_gb:.1f} GB ({free_pct:.1f}%)",
        "storage_ram_status": "RAM: {free_ram:.1f} GB Avail ({used_ram_pct:.0f}% Used)",
        "storage_cache_status": "Cleanable Cache: {cache_mb:.1f} MB | Telegram App Data: {app_mb:.1f} MB",
        "storage_warning_low": "⚠️ Low Free Disk Space (<10%)! Cleaning cache is recommended to prevent Windows & tool lag.",
        "storage_status_good": "✨ Disk storage is healthy. Windows and Telegram tool are running smoothly.",
        "btn_clean_cache": "⚡ Clean Cache & Speed Up PC",
        "btn_calculate_space": "🔄 Calculate Space",
        "btn_storage_details": "📊 Storage Details",
        "msg_cleaned_success": "Successfully cleaned {freed_mb:.1f} MB of temporary cache!\nDrive C: has more free space and your PC runs smoother.",
        "msg_already_clean": "Storage is already clean!\nNo orphaned temporary cache files were found.",
        "dialog_pc_space_title": "PC Storage & Performance Calculator",
        "action_pc_space": "PC Space Calculator & Cleaner",
        "dialog_storage_overview": "Drive & Memory Overview",
        "dialog_clean_tip": "Tip: Cleaning temporary cache frees space on Drive C: and speeds up tool startup and response.",
    },
    "km": {
        "app_title": "Telegram Member Manager - កម្មវិធីគ្រប់គ្រងសមាជិក",
        "hero_title": "Member Studio",
        "hero_subtitle": "កន្លែងការងារសាមញ្ញសម្រាប់គ្រប់គ្រងក្រុម Telegram របស់អ្នក",
        "hero_badge": "ឧបករណ៍ TELEGRAM",
        "card_account": "គណនីភ្ជាប់ច្រើន (MULTI-ACCOUNT)",
        "card_account_hint": "ភ្ជាប់គណនី Telegram ច្រើន (រហូតដល់ ២៥ គណនី)។ ពេលបន្ថែមសមាជិក គណនីទាំងអស់នឹងចែកគ្នាធ្វើការដោយស្វ័យប្រវត្តិ មិនជាន់គ្នាឡើយ។",
        "connected_accounts_title": "បញ្ជីគណនី Telegram ({count} / 25):",
        "btn_add_account": "+ ភ្ជាប់ / បន្ថែមគណនី",
        "btn_remove_account": "លុបគណនី",
        "btn_clear_all_accounts": "លុបទាំងអស់",
        "btn_select_all": "ជ្រើសទាំងអស់",
        "btn_deselect_all": "ដោះការជ្រើសរើស",
        "max_per_account_label": "ចំនួនអញ្ជើញអតិបរមាក្នុង ១ គណនី",
        "invites_suffix": " នាក់",
        "active_workers_status": "គណនីសកម្ម: {active} នៃ {total} (អតិបរមា ២៥)",
        "rotation_mode_hint": "គណនីទាំងអស់នឹងចែកវេនគ្នាធ្វើការរាល់ការអញ្ជើញម្តងៗ ដោយមិនជាន់គ្នានោះឡើយ។",
        "api_id": "API ID",
        "api_id_ph": "លេខសម្គាល់ API របស់អ្នក",
        "api_hash": "API hash",
        "api_hash_ph": "កូដ API hash របស់អ្នក",
        "phone_number": "លេខទូរស័ព្ទ",
        "phone_ph": "ឧទាហរណ៍: +85517271771 ឬ 017271771",
        "api_help_hint": "ត្រូវការព័ត៌មាន API? យកបានពី my.telegram.org។",
        "btn_get_api": "យក API ID និង Hash",
        "btn_login": "ចូលគណនី Telegram",
        "btn_confirm_account": "បញ្ជាក់គណនី",
        "not_signed_in": "មិនទាន់ចូលគណនី",
        "signed_in_as": "បានចូលគណនី: {name}",
        "card_target": "ក្រុមគោលដៅ (TARGET GROUP)",
        "card_target_hint": "ការអញ្ជើញនឹងត្រូវផ្ញើទៅកាន់សមាជិកដែលមានក្នុងបញ្ជីខាងក្រោម។",
        "target_ph": "តំណភ្ជាប់ ឬឈ្មោះក្រុមគោលដៅ (@group_link)",
        "card_source": "ក្រុមប្រភព (SOURCE GROUP)",
        "card_source_hint": "ទាញយកឈ្មោះអ្នកប្រើ ឬលេខសម្គាល់ពីក្រុមដែលអ្នកអាចមើលបញ្ជីសមាជិកបាន។",
        "source_ph": "តំណភ្ជាប់ ឬឈ្មោះក្រុមប្រភព (@group_link)",
        "btn_fetch": "ទាញយកសមាជិក",
        "card_upload": "បញ្ចូលឈ្មោះអ្នកប្រើពីឯកសារ TXT",
        "card_upload_hint": "ទាញយកឈ្មោះអ្នកប្រើ លេខទូរស័ព្ទ ឬ ID ពីឯកសារ .txt (មួយជួរម្នាក់)។",
        "upload_ph": "ជ្រើសរើសឯកសារ .txt ដែលមានបញ្ជីសមាជិក...",
        "btn_browse": "រើសឯកសារ",
        "btn_start_file": "ចាប់ផ្ដើមពីឯកសារ",
        "card_members": "បញ្ជីសមាជិក (MEMBER LIST)",
        "card_members_hint": "បិទភ្ជាប់ឈ្មោះអ្នកប្រើ (@username) លេខទូរស័ព្ទ (+phone) ឬ ID។ លេខទូរស័ព្ទនឹងត្រូវស្កេនជាមួយ Telegram ដោយស្វ័យប្រវត្តិ។",
        "members_ph": "@telegram_user\n+85512345678\n123456789",
        "consent_check": "ខ្ញុំមានការអនុញ្ញាតក្នុងការអញ្ជើញគណនីទាំងនេះ។",
        "random_amount": "ចំនួនចៃដន្យ",
        "btn_select_random": "រើសចៃដន្យ",
        "btn_gen_random": "បង្កើតលេខសាកល្បង",
        "btn_scan_phones": "ស្កេនលេខទូរស័ព្ទ",
        "btn_upload_txt": "បញ្ចូលពី TXT...",
        "delay_label": "រយៈពេលរង់ចាំរវាងការអញ្ជើញ",
        "delay_suffix": " វិនាទី",
        "btn_add_members": "បន្ថែមសមាជិក",
        "btn_clear": "សម្អាត",
        "btn_stop": "បញ្ឈប់",
        "status_ready": "រួចរាល់",
        "admin_contact": "ទាក់ទង Admin: <a href=\"https://t.me/{username}\">@{username}</a>",
        "menu_tools": "ឧបករណ៍",
        "menu_language": "ភាសា (Language)",
        "menu_audio": "សំឡេង (Audio)",
        "menu_help": "ជំនួយ",
        "action_get_api": "យក API ID និង Hash",
        "action_guide": "សៀវភៅណែនាំ Telegram API",
        "action_scan_phones": "ស្កេនលេខទូរស័ព្ទ",
        "action_upload_txt": "បញ្ចូលសមាជិកពី TXT",
        "action_fetch_members": "ទាញយកសមាជិក",
        "action_add_members": "ចាប់ផ្ដើមបន្ថែមសមាជិក",
        "action_clear": "សម្អាតទិន្នន័យ",
        "action_stop": "បញ្ឈប់ការបន្ថែម",
        "action_exit": "ចាកចេញ",
        "action_lang_en": "English",
        "action_lang_km": "ភាសាខ្មែរ (Khmer)",
        "action_switch_lang": "ប្តូរភាសា (Switch Language)",
        "action_sound_toggle_on": "សំឡេងជូនដំណឹង (បើក)",
        "action_sound_toggle_off": "សំឡេងជូនដំណឹង (បិទ)",
        "action_test_sound": "សាកល្បងសំឡេង",
        "action_tool_info": "ព័ត៌មានកម្មវិធី",
        "action_contact_admin": "ទាក់ទង Admin (@{username})",
        "card_pc_space": "ស្ថានភាពទំហំថាស & ល្បឿនម៉ាស៊ីន (PC STORAGE & PERFORMANCE)",
        "card_pc_space_hint": "ពិនិត្យទំហំ Drive C: និងអង្គចងចាំ RAM។ សម្អាតឯកសារ Cache បណ្ដោះអាសន្នដើម្បីឱ្យកម្មវិធី និងកុំព្យូទ័រដើររលូន មិនទាក់។",
        "storage_drive_status": "ថាស {drive}  សល់ {free_gb:.1f} GB / {total_gb:.1f} GB ({free_pct:.1f}%)",
        "storage_ram_status": "RAM: សល់ {free_ram:.1f} GB (ប្រើ {used_ram_pct:.0f}%)",
        "storage_cache_status": "Cache អាចសម្អាតបាន: {cache_mb:.1f} MB | ទិន្នន័យ App Telegram: {app_mb:.1f} MB",
        "storage_warning_low": "⚠️ ទំហំថាស C: នៅសល់តិច (<10%)! សូមសម្អាត Cache ដើម្បីកុំឱ្យកុំព្យូទ័រដើរយឺត ឬទាក់។",
        "storage_status_good": "✨ ទំហំថាស Drive C: គ្រប់គ្រាន់ល្អ កុំព្យូទ័រ និងកម្មវិធីដំណើរការរលូន។",
        "btn_clean_cache": "⚡ សម្អាត Cache & បង្កើនល្បឿន PC",
        "btn_calculate_space": "🔄 គណនាទំហំឡើងវិញ",
        "btn_storage_details": "📊 ព័ត៌មានលម្អិត",
        "msg_cleaned_success": "បានសម្អាតដោយជោគជ័យ {freed_mb:.1f} MB!\nទំហំថាស Drive C: ត្រូវបានបង្កើន និងកុំព្យូទ័រដំណើរការលឿនរលូន។",
        "msg_already_clean": "ទំហំផ្ទុកស្អាតស្រាប់ហើយ!\nគ្មានឯកសារ Cache ចាស់ៗដែលត្រូវសម្អាតទៀតទេ។",
        "dialog_pc_space_title": "ផ្ទាំងគណនាទំហំថាស និងល្បឿនកុំព្យូទ័រ (PC Storage Calculator)",
        "action_pc_space": "គណនាទំហំថាស & សម្អាត Cache ម៉ាស៊ីន...",
        "dialog_storage_overview": "ទិដ្ឋភាពទូទៅនៃទំហំថាស និង RAM",
        "dialog_clean_tip": "គន្លឹះ: ការសម្អាត Cache បណ្តោះអាសន្ន ជួយបង្កើនទំហំទំនេរ Drive C: និងធ្វើឱ្យកម្មវិធីបើកលឿនរហ័ស មិនទាក់។",
    }
}


class TelegramMemberManager(QMainWindow):
    MAX_ACCOUNTS = 25

    def __init__(self):
        super().__init__()
        self._apply_dark_palette()
        self.client = None
        self.phone_number = ""
        self._client_signature = None
        self._participant_cache = {}
        self._last_phone_lookup = 0.0
        self._saved_phone = ""
        self._stop_addition = False
        self.accounts = []
        self.audio_manager = AudioManager()
        self.current_language = "en"
        self._load_saved_settings()
        self.setWindowTitle(self.tr_text("app_title"))
        self.setWindowIcon(self._create_app_icon())
        self.setMinimumSize(620, 620)
        self.resize(800, 820)
        self._build_ui()
        self._build_menu()
        self._apply_styles()
        self._update_storage_ui()
        self._load_saved_credentials()
        self._load_environment_credentials()
        self._migrate_legacy_session()
        if self.current_language != "en":
            self.set_language(self.current_language)

    @staticmethod
    def _settings_file():
        app_data = os.getenv("APPDATA")
        if not app_data:
            return Path("settings.json")
        folder = Path(app_data) / "TelegramMemberManager"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "settings.json"

    def _load_saved_settings(self):
        try:
            p = self._settings_file()
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                self.current_language = data.get("language", "en")
                if self.current_language not in ("en", "km"):
                    self.current_language = "en"
                self.audio_manager.enabled = bool(data.get("audio_enabled", True))
        except Exception:
            pass

    def _save_settings(self):
        try:
            p = self._settings_file()
            data = {
                "language": self.current_language,
                "audio_enabled": self.audio_manager.enabled,
            }
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def tr_text(self, key, **kwargs):
        lang = self.current_language if self.current_language in TRANSLATIONS else "en"
        text = TRANSLATIONS[lang].get(key, TRANSLATIONS["en"].get(key, key))
        if kwargs:
            try:
                text = text.format(**kwargs)
            except Exception:
                pass
        return text

    def set_language(self, lang_code):
        if lang_code not in ("en", "km"):
            return
        self.current_language = lang_code
        self._save_settings()

        self.setWindowTitle(self.tr_text("app_title"))

        if hasattr(self, "hero_title"):
            self.hero_title.setText(self.tr_text("hero_title"))
        if hasattr(self, "hero_subtitle"):
            self.hero_subtitle.setText(self.tr_text("hero_subtitle"))
        if hasattr(self, "hero_badge"):
            self.hero_badge.set_text(self.tr_text("hero_badge"))

        if hasattr(self, "storage_card"):
            self.storage_card.title_label.setText(self.tr_text("card_pc_space"))
            self.storage_card.hint_label.setText(self.tr_text("card_pc_space_hint"))
        if hasattr(self, "btn_clean_cache"):
            self.btn_clean_cache.setText(self.tr_text("btn_clean_cache").replace("&", "&&"))
        if hasattr(self, "btn_calculate_space"):
            self.btn_calculate_space.setText(self.tr_text("btn_calculate_space").replace("&", "&&"))
        if hasattr(self, "btn_storage_details"):
            self.btn_storage_details.setText(self.tr_text("btn_storage_details").replace("&", "&&"))
        if hasattr(self, "_update_storage_ui"):
            self._update_storage_ui()

        if hasattr(self, "credentials_card"):
            self.credentials_card.title_label.setText(self.tr_text("card_account"))
            self.credentials_card.hint_label.setText(self.tr_text("card_account_hint"))
        if hasattr(self, "accounts_count_label"):
            self.accounts_count_label.setText(self.tr_text("connected_accounts_title"))
        if hasattr(self, "btn_select_all"):
            self.btn_select_all.setText(self.tr_text("btn_select_all"))
        if hasattr(self, "btn_deselect_all"):
            self.btn_deselect_all.setText(self.tr_text("btn_deselect_all"))
        if hasattr(self, "btn_remove_account"):
            self.btn_remove_account.setText(self.tr_text("btn_remove_account"))
        if hasattr(self, "btn_clear_all_accounts"):
            self.btn_clear_all_accounts.setText(self.tr_text("btn_clear_all_accounts"))
        if hasattr(self, "max_per_account_label"):
            self.max_per_account_label.setText(self.tr_text("max_per_account_label"))
        if hasattr(self, "max_per_account_spin"):
            self.max_per_account_spin.setSuffix(self.tr_text("invites_suffix"))
        self._update_accounts_summary()
        if hasattr(self, "groups_card"):
            self.groups_card.title_label.setText(self.tr_text("card_target"))
            self.groups_card.hint_label.setText(self.tr_text("card_target_hint"))
        if hasattr(self, "source_card"):
            self.source_card.title_label.setText(self.tr_text("card_source"))
            self.source_card.hint_label.setText(self.tr_text("card_source_hint"))
        if hasattr(self, "upload_card"):
            self.upload_card.title_label.setText(self.tr_text("card_upload"))
            self.upload_card.hint_label.setText(self.tr_text("card_upload_hint"))
        if hasattr(self, "members_card"):
            self.members_card.title_label.setText(self.tr_text("card_members"))
            self.members_card.hint_label.setText(self.tr_text("card_members_hint"))

        if hasattr(self, "api_id_label"):
            self.api_id_label.setText(self.tr_text("api_id"))
        if hasattr(self, "api_hash_label"):
            self.api_hash_label.setText(self.tr_text("api_hash"))
        if hasattr(self, "phone_label"):
            self.phone_label.setText(self.tr_text("phone_number"))

        if hasattr(self, "api_id_entry"):
            self.api_id_entry.setPlaceholderText(self.tr_text("api_id_ph"))
        if hasattr(self, "api_hash_entry"):
            self.api_hash_entry.setPlaceholderText(self.tr_text("api_hash_ph"))
        if hasattr(self, "phone_entry"):
            self.phone_entry.setPlaceholderText(self.tr_text("phone_ph"))
        if hasattr(self, "api_help_hint"):
            self.api_help_hint.setText(self.tr_text("api_help_hint"))

        if hasattr(self, "group_entry"):
            self.group_entry.setPlaceholderText(self.tr_text("target_ph"))
        if hasattr(self, "source_group_entry"):
            self.source_group_entry.setPlaceholderText(self.tr_text("source_ph"))
        if hasattr(self, "upload_path_edit"):
            self.upload_path_edit.setPlaceholderText(self.tr_text("upload_ph"))
        if hasattr(self, "members_entry"):
            self.members_entry.setPlaceholderText(self.tr_text("members_ph"))

        if hasattr(self, "api_help_button"):
            self.api_help_button.setText(self.tr_text("btn_get_api"))
        if hasattr(self, "login_button"):
            is_auth = (
                self.client is not None
                and self.client.is_connected()
                and self.client.is_user_authorized()
            ) if self.client else False
            self.login_button.setText(
                self.tr_text("btn_confirm_account") if is_auth else self.tr_text("btn_login")
            )
        if hasattr(self, "fetch_button"):
            self.fetch_button.setText(self.tr_text("btn_fetch"))
        if hasattr(self, "browse_button"):
            self.browse_button.setText(self.tr_text("btn_browse"))
        if hasattr(self, "upload_start_btn"):
            self.upload_start_btn.setText(self.tr_text("btn_start_file"))
        if hasattr(self, "upload_txt_button"):
            self.upload_txt_button.setText(self.tr_text("btn_upload_txt"))
        if hasattr(self, "generate_button"):
            self.generate_button.setText(self.tr_text("btn_select_random"))
        if hasattr(self, "random_numbers_button"):
            self.random_numbers_button.setText(self.tr_text("btn_gen_random"))
        if hasattr(self, "scan_button"):
            self.scan_button.setText(self.tr_text("btn_scan_phones"))
        if hasattr(self, "add_button"):
            self.add_button.setText(self.tr_text("btn_add_members"))
        if hasattr(self, "clear_button"):
            self.clear_button.setText(self.tr_text("btn_clear"))
        if hasattr(self, "stop_button"):
            self.stop_button.setText(self.tr_text("btn_stop"))

        if hasattr(self, "permission_confirmation"):
            self.permission_confirmation.setText(self.tr_text("consent_check"))
        if hasattr(self, "delay_label"):
            self.delay_label.setText(self.tr_text("delay_label"))
        if hasattr(self, "speed_scale"):
            self.speed_scale.setSuffix(self.tr_text("delay_suffix"))
        if hasattr(self, "count_label"):
            self.count_label.setText(self.tr_text("random_amount"))
        if hasattr(self, "admin_label"):
            self.admin_label.setText(self.tr_text("admin_contact", username=ADMIN_USERNAME))

        self._build_menu()

        if hasattr(self, "status_label"):
            if self.status_label.text() in ("Ready", "រួចរាល់"):
                self.status_label.setText(self.tr_text("status_ready"))

    def _toggle_language(self):
        new_lang = "km" if self.current_language == "en" else "en"
        self.set_language(new_lang)
        self.audio_manager.play_success()

    def _toggle_audio(self):
        self.audio_manager.enabled = not self.audio_manager.enabled
        self._save_settings()
        if self.audio_manager.enabled:
            self.audio_manager.play_success()
            msg = "Sound effects enabled" if self.current_language == "en" else "បានបើកសំឡេងជូនដំណឹង"
        else:
            msg = "Sound effects disabled" if self.current_language == "en" else "បានបិទសំឡេងជូនដំណឹង"
        self.status_label.setText(msg)
        self._build_menu()

    def _test_audio(self):
        self.audio_manager.play_complete()
        msg = "Playing audio sound effect..." if self.current_language == "en" else "កំពុងចាក់សំឡេងសាកល្បង..."
        self.status_label.setText(msg)

    @staticmethod
    def _credential_file():
        app_data = os.getenv("APPDATA")
        if not app_data:
            raise OSError("Windows APPDATA folder is unavailable.")
        return Path(app_data) / "TelegramMemberManager" / "credentials.dat"

    def _load_saved_credentials(self):
        try:
            encrypted = self._credential_file().read_bytes()
        except FileNotFoundError:
            return
        except OSError as exc:
            return

        try:
            raw = json.loads(_unprotect_for_current_user(encrypted).decode("utf-8"))
            if isinstance(raw, list):
                self.accounts = raw
            elif isinstance(raw, dict):
                self.accounts = [raw]
            else:
                self.accounts = []
        except Exception:
            self.accounts = []

        if self.accounts:
            latest = self.accounts[-1]
            self.api_id_entry.setText(str(latest.get("api_id", "")))
            self.api_hash_entry.setText(str(latest.get("api_hash", "")))
            self.phone_entry.setText(str(latest.get("phone_number", "")))
            self._saved_phone = self._normalize_phone(str(latest.get("phone_number", "")))

        self._refresh_accounts_list()

    def _load_environment_credentials(self):
        environment_values = (
            (self.api_id_entry, os.getenv("TG_API_ID", "")),
            (self.api_hash_entry, os.getenv("TG_API_HASH", "")),
            (self.phone_entry, os.getenv("TG_PHONE_NUMBER", "")),
        )
        for field, value in environment_values:
            if not field.text().strip() and value:
                field.setText(value)

    def _save_credentials(self):
        path = None
        temporary_path = None
        try:
            path = self._credential_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            encrypted = _protect_for_current_user(
                json.dumps(self.accounts).encode("utf-8")
            )
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(encrypted)
            os.replace(temporary_path, path)
            self._saved_phone = self._normalize_phone(self.phone_entry.text())
        except (OSError, ValueError) as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _refresh_accounts_list(self):
        if not hasattr(self, "accounts_list_widget"):
            return
        self.accounts_list_widget.blockSignals(True)
        self.accounts_list_widget.clear()
        for idx, acc in enumerate(self.accounts):
            phone = acc.get("phone_number", f"Account #{idx + 1}")
            username = f" (@{acc['username']})" if acc.get("username") else ""
            name = acc.get("first_name", "")
            display_name = f"{name}{username}".strip()
            is_premium = bool(acc.get("is_premium", False))
            prem_tag = " ⭐ [PREMIUM]" if is_premium else ""
            item_text = f"👤 {phone}"
            if display_name:
                item_text += f" - {display_name}"
            item_text += prem_tag

            item = QListWidgetItem(item_text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            is_enabled = acc.get("enabled", True)
            item.setCheckState(Qt.CheckState.Checked if is_enabled else Qt.CheckState.Unchecked)
            if is_premium:
                item.setToolTip(
                    "Telegram Premium account: Unlimited invites (no limit) / គណនី Telegram Premium: អញ្ជើញគ្មានកម្រិតកំណត់"
                )
                item.setForeground(QColor("#fde047"))
            item.setData(Qt.ItemDataRole.UserRole, acc)
            self.accounts_list_widget.addItem(item)
        self.accounts_list_widget.blockSignals(False)
        self._update_accounts_summary()

    def _update_accounts_summary(self):
        count = len(self.accounts)
        if hasattr(self, "accounts_count_label"):
            self.accounts_count_label.setText(
                self.tr_text("connected_accounts_title", count=count, max=self.MAX_ACCOUNTS)
            )
        if not hasattr(self, "active_workers_label"):
            return
        total = self.accounts_list_widget.count() if hasattr(self, "accounts_list_widget") else count
        active = len(self._get_active_accounts())
        self.active_workers_label.setText(
            self.tr_text("active_workers_status", active=active, total=total, max=self.MAX_ACCOUNTS)
        )

    def _on_account_item_changed(self, item):
        acc = item.data(Qt.ItemDataRole.UserRole)
        if acc:
            is_checked = (item.checkState() == Qt.CheckState.Checked)
            acc_phone = self._normalize_phone(acc.get("phone_number", ""))
            for a in self.accounts:
                if self._normalize_phone(a.get("phone_number", "")) == acc_phone:
                    a["enabled"] = is_checked
                    break
            self._save_credentials()
            self._update_accounts_summary()

    def _on_account_double_clicked(self, item):
        acc = item.data(Qt.ItemDataRole.UserRole)
        if acc:
            self.api_id_entry.setText(str(acc.get("api_id", "")))
            self.api_hash_entry.setText(str(acc.get("api_hash", "")))
            self.phone_entry.setText(str(acc.get("phone_number", "")))
            msg = f"Selected account: {acc.get('phone_number')}" if self.current_language == "en" else f"បានជ្រើសរើសគណនី: {acc.get('phone_number')}"
            self.status_label.setText(msg)

    def _select_all_accounts(self):
        if hasattr(self, "accounts_list_widget"):
            self.accounts_list_widget.blockSignals(True)
            for i in range(self.accounts_list_widget.count()):
                self.accounts_list_widget.item(i).setCheckState(Qt.CheckState.Checked)
            self.accounts_list_widget.blockSignals(False)
        for acc in self.accounts:
            acc["enabled"] = True
        self._save_credentials()
        self._update_accounts_summary()

    def _deselect_all_accounts(self):
        if hasattr(self, "accounts_list_widget"):
            self.accounts_list_widget.blockSignals(True)
            for i in range(self.accounts_list_widget.count()):
                self.accounts_list_widget.item(i).setCheckState(Qt.CheckState.Unchecked)
            self.accounts_list_widget.blockSignals(False)
        for acc in self.accounts:
            acc["enabled"] = False
        self._save_credentials()
        self._update_accounts_summary()

    def _accounts_list_key_press(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._remove_selected_account()
        else:
            QListWidget.keyPressEvent(self.accounts_list_widget, event)

    def _show_accounts_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_remove = menu.addAction(CustomIcons.trash(), self.tr_text("btn_remove_account"))
        act_remove.triggered.connect(self._remove_selected_account)
        menu.addSeparator()
        act_sel = menu.addAction(self.tr_text("btn_select_all"))
        act_sel.triggered.connect(self._select_all_accounts)
        act_desel = menu.addAction(self.tr_text("btn_deselect_all"))
        act_desel.triggered.connect(self._deselect_all_accounts)
        menu.addSeparator()
        act_clear = menu.addAction(CustomIcons.clear(), self.tr_text("btn_clear_all_accounts"))
        act_clear.triggered.connect(self._clear_all_accounts)
        menu.exec(self.accounts_list_widget.mapToGlobal(pos))

    def _remove_selected_account(self):
        # Gather checked items or highlighted item
        targets = []
        if hasattr(self, "accounts_list_widget"):
            for i in range(self.accounts_list_widget.count()):
                it = self.accounts_list_widget.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    acc_data = it.data(Qt.ItemDataRole.UserRole)
                    if acc_data and acc_data not in targets:
                        targets.append(acc_data)
        
        # If no checked items, use the currently selected row
        if not targets and hasattr(self, "accounts_list_widget"):
            curr = self.accounts_list_widget.currentItem()
            if curr:
                acc_data = curr.data(Qt.ItemDataRole.UserRole)
                if acc_data:
                    targets.append(acc_data)

        if not targets:
            QMessageBox.information(
                self,
                "Select account" if self.current_language == "en" else "ជ្រើសរើសគណនី",
                "Please select or check an account in the list to remove."
                if self.current_language == "en"
                else "សូមចុចជ្រើសរើស ឬគូសធីកគណនីក្នុងបញ្ជីដែលត្រូវលុប។",
            )
            return

        if len(targets) == 1:
            phone = targets[0].get("phone_number", "this account")
            prompt = (
                f"Remove account {phone} from Member Studio?"
                if self.current_language == "en"
                else f"តើអ្នកពិតជាចង់លុបគណនី {phone} មែនទេ?"
            )
        else:
            prompt = (
                f"Remove {len(targets)} selected accounts from Member Studio?"
                if self.current_language == "en"
                else f"តើអ្នកពិតជាចង់លុប {len(targets)} គណនីដែលបានជ្រើសមែនទេ?"
            )

        confirm = QMessageBox.question(
            self,
            "Remove account" if self.current_language == "en" else "លុបគណនី",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        phones_to_remove = {self._normalize_phone(t.get("phone_number", "")) for t in targets}

        # If current client belongs to removed accounts, disconnect
        if self._normalize_phone(self.phone_number) in phones_to_remove:
            self._disconnect_client()
            self.phone_entry.clear()
            self.login_status.setText(self.tr_text("not_signed_in"))
            self.setWindowIcon(self._create_app_icon(show_checkmark=False))
            if hasattr(self, "hero_logo"):
                self.hero_logo.set_checkmark(False)

        # Remove matching accounts
        self.accounts = [
            a for a in self.accounts
            if self._normalize_phone(a.get("phone_number", "")) not in phones_to_remove
        ]

        # Clean session files for removed accounts
        for p in phones_to_remove:
            digits = re.sub(r"\D", "", p)
            if digits:
                sessions_dir = Path(__file__).resolve().parent / "sessions"
                sfile = sessions_dir / f"telegram_adder_session_{digits}.session"
                if sfile.exists():
                    try:
                        sfile.unlink(missing_ok=True)
                    except Exception:
                        pass

        self._save_credentials()
        self._refresh_accounts_list()
        msg = (
            f"Removed {len(targets)} account(s)"
            if self.current_language == "en"
            else f"បានលុប {len(targets)} គណនីរួចរាល់"
        )
        self.status_label.setText(msg)

    def _clear_all_accounts(self):
        if not self.accounts:
            return
        count = len(self.accounts)
        confirm = QMessageBox.question(
            self,
            "Clear all accounts" if self.current_language == "en" else "លុបបញ្ជីគណនីទាំងអស់",
            f"Are you sure you want to remove all {count} saved accounts from Member Studio?"
            if self.current_language == "en"
            else f"តើអ្នកពិតជាចង់លុបគណនីទាំង {count} ចេញពីបញ្ជីទាំងអស់មែនទេ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._disconnect_client()
        self.phone_entry.clear()
        self.login_status.setText(self.tr_text("not_signed_in"))
        self.setWindowIcon(self._create_app_icon(show_checkmark=False))
        if hasattr(self, "hero_logo"):
            self.hero_logo.set_checkmark(False)

        for a in self.accounts:
            digits = re.sub(r"\D", "", a.get("phone_number", ""))
            if digits:
                sessions_dir = Path(__file__).resolve().parent / "sessions"
                sfile = sessions_dir / f"telegram_adder_session_{digits}.session"
                if sfile.exists():
                    try:
                        sfile.unlink(missing_ok=True)
                    except Exception:
                        pass

        self.accounts = []
        self._save_credentials()
        self._refresh_accounts_list()
        msg = "All accounts removed" if self.current_language == "en" else "បានលុបបញ្ជីគណនីទាំងអស់រួចរាល់"
        self.status_label.setText(msg)

    def _get_active_accounts(self):
        active = []
        if hasattr(self, "accounts_list_widget") and self.accounts_list_widget.count() > 0:
            for i in range(self.accounts_list_widget.count()):
                item = self.accounts_list_widget.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    acc = item.data(Qt.ItemDataRole.UserRole)
                    if acc:
                        active.append(acc)
            if active:
                return active

            # Fallback 1: If user highlighted an item, select it
            curr = self.accounts_list_widget.currentItem()
            if curr:
                acc = curr.data(Qt.ItemDataRole.UserRole)
                if acc:
                    curr.setCheckState(Qt.CheckState.Checked)
                    return [acc]

            # Fallback 2: If none checked, automatically select all accounts in list
            if self.accounts:
                self._select_all_accounts()
                return [a for a in self.accounts if a.get("enabled", True)]

            return active

        if not active and self.phone_entry.text().strip():
            norm_phone = self._normalize_phone(self.phone_entry.text())
            active = [{
                "api_id": self.api_id_entry.text().strip(),
                "api_hash": self.api_hash_entry.text().strip(),
                "phone_number": norm_phone,
                "enabled": True,
            }]
        return active

    def _build_ui(self):
        scroll_area = QScrollArea()
        scroll_area.setObjectName("contentScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.verticalScrollBar().setSingleStep(26)
        scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        content = QWidget()
        content.setObjectName("centralPanel")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(18)

        self.header_card = AnimatedHeroCard(self)
        header = QHBoxLayout(self.header_card)
        header.setContentsMargins(22, 18, 22, 18)
        header.setSpacing(16)
        self.hero_logo = AnimatedLogo(self.header_card)
        header.addWidget(self.hero_logo, 0, Qt.AlignmentFlag.AlignVCenter)

        title_block = QVBoxLayout()
        title_block.setSpacing(3)
        self.hero_title = QLabel(self.tr_text("hero_title"))
        self.hero_title.setObjectName("title")
        self.hero_subtitle = QLabel(self.tr_text("hero_subtitle"))
        self.hero_subtitle.setObjectName("subtitle")
        title_block.addWidget(self.hero_title)
        title_block.addWidget(self.hero_subtitle)
        header.addLayout(title_block, 1)

        self.hero_badge = AnimatedBadge(self.tr_text("hero_badge"), self.header_card)
        header.addWidget(self.hero_badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.header_card)


        self.credentials_card = self._create_card(
            self.tr_text("card_account"),
            self.tr_text("card_account_hint"),
        )

        # Accounts List Header & Actions
        accounts_header_row = QHBoxLayout()
        self.accounts_count_label = QLabel(self.tr_text("connected_accounts_title"))
        self.accounts_count_label.setStyleSheet("font-weight: 700; color: #38bdf8;")
        accounts_header_row.addWidget(self.accounts_count_label)
        accounts_header_row.addStretch()

        self.btn_select_all = QPushButton(self.tr_text("btn_select_all"))
        self.btn_select_all.setObjectName("quietButton")
        self.btn_select_all.clicked.connect(self._select_all_accounts)

        self.btn_deselect_all = QPushButton(self.tr_text("btn_deselect_all"))
        self.btn_deselect_all.setObjectName("quietButton")
        self.btn_deselect_all.clicked.connect(self._deselect_all_accounts)

        self.btn_remove_account = QPushButton(self.tr_text("btn_remove_account"))
        self.btn_remove_account.setObjectName("quietButton")
        self.btn_remove_account.setIcon(CustomIcons.trash("#f87171"))
        self.btn_remove_account.setToolTip("Delete selected or checked accounts")
        self.btn_remove_account.clicked.connect(self._remove_selected_account)

        self.btn_clear_all_accounts = QPushButton(self.tr_text("btn_clear_all_accounts"))
        self.btn_clear_all_accounts.setObjectName("quietButton")
        self.btn_clear_all_accounts.setIcon(CustomIcons.clear("#94a3b8"))
        self.btn_clear_all_accounts.setToolTip("Clear all accounts from the list")
        self.btn_clear_all_accounts.clicked.connect(self._clear_all_accounts)

        accounts_header_row.addWidget(self.btn_select_all)
        accounts_header_row.addWidget(self.btn_deselect_all)
        accounts_header_row.addWidget(self.btn_remove_account)
        accounts_header_row.addWidget(self.btn_clear_all_accounts)
        self.credentials_card.layout().addLayout(accounts_header_row)

        self.accounts_list_widget = QListWidget()
        self.accounts_list_widget.setMinimumHeight(130)
        self.accounts_list_widget.setMaximumHeight(175)
        self.accounts_list_widget.itemChanged.connect(self._on_account_item_changed)
        self.accounts_list_widget.itemDoubleClicked.connect(self._on_account_double_clicked)
        self.accounts_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.accounts_list_widget.customContextMenuRequested.connect(self._show_accounts_context_menu)
        self.accounts_list_widget.keyPressEvent = self._accounts_list_key_press
        self.credentials_card.layout().addWidget(self.accounts_list_widget)

        # Multi-Account Work Distribution Settings (ចែកគ្នាធ្វើការ)
        multi_settings_row = QHBoxLayout()
        self.max_per_account_label = QLabel(self.tr_text("max_per_account_label"))
        self.max_per_account_spin = QSpinBox()
        self.max_per_account_spin.setRange(1, 500)
        self.max_per_account_spin.setValue(30)
        self.max_per_account_spin.setSuffix(self.tr_text("invites_suffix"))
        self.max_per_account_spin.setToolTip(self.tr_text("rotation_mode_hint"))

        self.active_workers_label = QLabel("Active: 0 accounts")
        self.active_workers_label.setStyleSheet("color: #10b981; font-weight: 600;")

        multi_settings_row.addWidget(self.max_per_account_label)
        multi_settings_row.addWidget(self.max_per_account_spin)
        multi_settings_row.addSpacing(16)
        multi_settings_row.addWidget(self.active_workers_label)
        multi_settings_row.addStretch()
        self.credentials_card.layout().addLayout(multi_settings_row)

        # Connect / Add Account Form
        credentials_form = QFormLayout()
        credentials_form.setHorizontalSpacing(18)
        credentials_form.setVerticalSpacing(10)
        self.api_id_entry = QLineEdit()
        self.api_id_entry.setPlaceholderText(self.tr_text("api_id_ph"))
        self.api_hash_entry = QLineEdit()
        self.api_hash_entry.setPlaceholderText(self.tr_text("api_hash_ph"))
        self.api_hash_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.phone_entry = QLineEdit()
        self.phone_entry.setPlaceholderText(self.tr_text("phone_ph"))
        for field in (self.api_id_entry, self.api_hash_entry, self.phone_entry):
            palette = field.palette()
            palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7fa3bb"))
            field.setPalette(palette)
        self.api_id_label = QLabel(self.tr_text("api_id"))
        self.api_hash_label = QLabel(self.tr_text("api_hash"))
        self.phone_label = QLabel(self.tr_text("phone_number"))
        credentials_form.addRow(self.api_id_label, self.api_id_entry)
        credentials_form.addRow(self.api_hash_label, self.api_hash_entry)
        credentials_form.addRow(self.phone_label, self.phone_entry)
        self.credentials_card.layout().addLayout(credentials_form)

        api_help_row = QHBoxLayout()
        api_help_row.setSpacing(12)
        self.api_help_hint = QLabel(self.tr_text("api_help_hint"))
        self.api_help_hint.setObjectName("sectionHint")
        self.api_help_hint.setWordWrap(True)
        self.api_help_button = QPushButton(self.tr_text("btn_get_api"))
        self.api_help_button.setObjectName("secondaryButton")
        self.api_help_button.setIcon(CustomIcons.key())
        self.api_help_button.setToolTip(
            "Open my.telegram.org/apps in your browser to get your API ID and API hash"
        )
        self.api_help_button.clicked.connect(self.open_api_credentials_page)
        api_help_row.addWidget(self.api_help_hint, 1)
        api_help_row.addWidget(self.api_help_button)
        self.credentials_card.layout().addLayout(api_help_row)

        login_row = QHBoxLayout()
        login_row.setSpacing(12)
        self.login_status = QLabel(self.tr_text("not_signed_in"))
        self.login_status.setObjectName("loginStatus")
        self.login_button = QPushButton(self.tr_text("btn_add_account"))
        self.login_button.setObjectName("primaryButton")
        self.login_button.setIcon(CustomIcons.user_plus())
        self.login_button.clicked.connect(self.login_account)
        self.login_button.setToolTip(
            "Log in and add this Telegram account to your connected accounts list."
        )
        login_row.addWidget(self.login_status, 1)
        login_row.addWidget(self.login_button)
        self.credentials_card.layout().addLayout(login_row)
        layout.addWidget(self.credentials_card)

        self.groups_card = self._create_card(
            self.tr_text("card_target"),
            self.tr_text("card_target_hint"),
        )
        self.group_entry = QLineEdit()
        self.group_entry.setPlaceholderText(self.tr_text("target_ph"))
        self.groups_card.layout().addWidget(self.group_entry)
        layout.addWidget(self.groups_card)

        self.source_card = self._create_card(
            self.tr_text("card_source"),
            self.tr_text("card_source_hint"),
        )
        source_row = QHBoxLayout()
        source_row.setSpacing(12)
        self.source_group_entry = QLineEdit()
        self.source_group_entry.setPlaceholderText(self.tr_text("source_ph"))
        self.fetch_button = QPushButton(self.tr_text("btn_fetch"))
        self.fetch_button.setObjectName("secondaryButton")
        self.fetch_button.setIcon(CustomIcons.group())
        self.fetch_button.clicked.connect(self.start_fetching)
        source_row.addWidget(self.source_group_entry, 1)
        source_row.addWidget(self.fetch_button)
        self.source_card.layout().addLayout(source_row)
        layout.addWidget(self.source_card)



        self.members_card = self._create_card(
            self.tr_text("card_members"),
            self.tr_text("card_members_hint"),
        )
        self.members_entry = QPlainTextEdit()
        self.members_entry.setPlaceholderText(self.tr_text("members_ph"))
        self.members_entry.setMinimumHeight(155)
        members_palette = self.members_entry.palette()
        members_palette.setColor(
            QPalette.ColorRole.PlaceholderText, QColor("#7fa3bb")
        )
        self.members_entry.setPalette(members_palette)
        self._updating_member_list = False
        self.members_entry.textChanged.connect(self._member_list_edited)
        self.members_card.layout().addWidget(self.members_entry)

        self.permission_confirmation = QCheckBox(
            self.tr_text("consent_check")
        )
        self.permission_confirmation.setObjectName("consentCheck")
        self.members_card.layout().addWidget(self.permission_confirmation)

        member_options = QHBoxLayout()
        member_options.setSpacing(12)
        self.random_entry = QSpinBox()
        self.random_entry.setRange(1, 10000)
        self.random_entry.setValue(10)
        self.random_entry.setFixedWidth(100)
        self.random_entry.setToolTip("How many members to select or generate")
        self.count_label = QLabel(self.tr_text("random_amount"))
        self.count_label.setObjectName("controlLabel")
        self.generate_button = QPushButton(self.tr_text("btn_select_random"))
        self.generate_button.setObjectName("secondaryButton")
        self.generate_button.setIcon(CustomIcons.dice())
        self.generate_button.clicked.connect(self.select_random_members)
        self.random_numbers_button = QPushButton(self.tr_text("btn_gen_random"))
        self.random_numbers_button.setObjectName("secondaryButton")
        self.random_numbers_button.setIcon(CustomIcons.dice())
        self.random_numbers_button.setToolTip(
            "Fill the list with random +855 phone-number placeholders for testing"
        )
        self.random_numbers_button.clicked.connect(self.generate_random_members)
        self.scan_button = QPushButton(self.tr_text("btn_scan_phones"))
        self.scan_button.setObjectName("secondaryButton")
        self.scan_button.setIcon(CustomIcons.search())
        self.scan_button.setToolTip(
            "Check phone numbers with Telegram and replace resolved numbers with usernames/IDs. "
            "Telegram allows about one phone lookup every 3 seconds."
        )
        self.scan_button.clicked.connect(self.scan_phone_numbers)
        member_options.addWidget(self.count_label)
        member_options.addWidget(self.random_entry)
        member_options.addWidget(self.generate_button)
        member_options.addStretch()
        self.members_card.layout().addLayout(member_options)

        member_tools = QHBoxLayout()
        member_tools.setSpacing(12)
        self.upload_txt_button = QPushButton(self.tr_text("btn_upload_txt"))
        self.upload_txt_button.setObjectName("primaryButton")
        self.upload_txt_button.setIcon(CustomIcons.upload())
        self.upload_txt_button.setToolTip(
            "Select a .txt file to load usernames directly into this list"
        )
        self.upload_txt_button.clicked.connect(self._browse_upload_file)
        member_tools.addWidget(self.upload_txt_button)
        member_tools.addWidget(self.random_numbers_button)
        member_tools.addWidget(self.scan_button)
        member_tools.addStretch()
        self.members_card.layout().addLayout(member_tools)
        layout.addWidget(self.members_card)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.delay_label = QLabel(self.tr_text("delay_label"))
        self.speed_scale = QSpinBox()
        self.speed_scale.setRange(1, 120)
        self.speed_scale.setValue(10)
        self.speed_scale.setSuffix(self.tr_text("delay_suffix"))
        self.speed_scale.setFixedWidth(105)
        self.speed_scale.setToolTip("Pause between invite requests")
        controls.addWidget(self.delay_label)
        controls.addWidget(self.speed_scale)
        controls.addStretch()
        layout.addLayout(controls)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.add_button = QPushButton(self.tr_text("btn_add_members"))
        self.add_button.setObjectName("primaryButton")
        self.add_button.setIcon(CustomIcons.play())
        self.add_button.clicked.connect(self.start_adding)
        self.clear_button = QPushButton(self.tr_text("btn_clear"))
        self.clear_button.setObjectName("quietButton")
        self.clear_button.setToolTip(
            "Clear the target group, source group, and member list; keep the account login"
        )
        self.clear_button.setIcon(CustomIcons.clear())
        self.clear_button.clicked.connect(self.clear_entries)
        actions.addStretch()
        actions.addWidget(self.clear_button)
        actions.addWidget(self.add_button)
        layout.addLayout(actions)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.stop_button = QPushButton(self.tr_text("btn_stop"))
        self.stop_button.setObjectName("secondaryButton")
        self.stop_button.setIcon(CustomIcons.stop())
        self.stop_button.clicked.connect(self._request_stop_addition)
        layout.addWidget(self.stop_button)

        self.status_label = QLabel(self.tr_text("status_ready"))
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch()
        self.admin_label = QLabel(
            self.tr_text("admin_contact", username=ADMIN_USERNAME)
        )
        self.admin_label.setObjectName("adminContact")
        self.admin_label.setOpenExternalLinks(True)
        self.admin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.admin_label.setToolTip(f"Open Telegram chat with @{ADMIN_USERNAME}")
        layout.addWidget(self.admin_label)
        scroll_area.setWidget(content)
        self.setCentralWidget(scroll_area)
    def _build_menu(self):
        menubar = self.menuBar()
        menubar.clear()

        # Tools Menu
        self.tools_menu = menubar.addMenu(self.tr_text("menu_tools"))

        self.action_upload = QAction(CustomIcons.upload(), self.tr_text("action_upload_txt"), self)
        self.action_upload.setShortcut(QKeySequence("Ctrl+U"))
        self.action_upload.triggered.connect(self.upload_users_from_file)
        self.tools_menu.addAction(self.action_upload)

        self.action_fetch = QAction(CustomIcons.group(), self.tr_text("action_fetch_members"), self)
        self.action_fetch.setShortcut(QKeySequence("Ctrl+F"))
        self.action_fetch.triggered.connect(self.start_fetching)
        self.tools_menu.addAction(self.action_fetch)

        self.action_add = QAction(CustomIcons.play(), self.tr_text("action_add_members"), self)
        self.action_add.setShortcut(QKeySequence("Ctrl+Return"))
        self.action_add.triggered.connect(self.start_adding)
        self.tools_menu.addAction(self.action_add)

        self.action_scan = QAction(CustomIcons.search(), self.tr_text("action_scan_phones"), self)
        self.action_scan.setShortcut(QKeySequence("Ctrl+S"))
        self.action_scan.triggered.connect(self.scan_phone_numbers)
        self.tools_menu.addAction(self.action_scan)

        self.action_random = QAction(CustomIcons.dice(), self.tr_text("btn_select_random"), self)
        self.action_random.setShortcut(QKeySequence("Ctrl+R"))
        self.action_random.triggered.connect(self.select_random_members)
        self.tools_menu.addAction(self.action_random)

        self.action_gen_numbers = QAction(CustomIcons.dice(), self.tr_text("btn_gen_random"), self)
        self.action_gen_numbers.setShortcut(QKeySequence("Ctrl+G"))
        self.action_gen_numbers.triggered.connect(self.generate_random_members)
        self.tools_menu.addAction(self.action_gen_numbers)


        self.tools_menu.addSeparator()

        self.action_get_api = QAction(CustomIcons.key(), self.tr_text("action_get_api"), self)
        self.action_get_api.triggered.connect(self.open_api_credentials_page)
        self.tools_menu.addAction(self.action_get_api)

        self.action_guide = QAction(CustomIcons.info(), self.tr_text("action_guide"), self)
        self.action_guide.triggered.connect(self.open_api_guide)
        self.tools_menu.addAction(self.action_guide)

        self.tools_menu.addSeparator()

        self.action_clear = QAction(CustomIcons.clear(), self.tr_text("action_clear"), self)
        self.action_clear.setShortcut(QKeySequence("Ctrl+Delete"))
        self.action_clear.triggered.connect(self.clear_entries)
        self.tools_menu.addAction(self.action_clear)

        self.action_stop = QAction(CustomIcons.stop(), self.tr_text("action_stop"), self)
        self.action_stop.setShortcut(QKeySequence("Esc"))
        self.action_stop.triggered.connect(self._request_stop_addition)
        self.tools_menu.addAction(self.action_stop)

        self.tools_menu.addSeparator()

        self.action_exit = QAction(CustomIcons.exit(), self.tr_text("action_exit"), self)
        self.action_exit.setShortcut(QKeySequence("Ctrl+Q"))
        self.action_exit.triggered.connect(self.close)
        self.tools_menu.addAction(self.action_exit)

        # Language Menu
        self.lang_menu = menubar.addMenu(self.tr_text("menu_language"))

        self.action_lang_en = QAction(CustomIcons.globe(), self.tr_text("action_lang_en"), self)
        self.action_lang_en.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.action_lang_en.setCheckable(True)
        self.action_lang_en.setChecked(self.current_language == "en")
        self.action_lang_en.triggered.connect(lambda: self.set_language("en"))
        self.lang_menu.addAction(self.action_lang_en)

        self.action_lang_km = QAction(CustomIcons.globe(), self.tr_text("action_lang_km"), self)
        self.action_lang_km.setShortcut(QKeySequence("Ctrl+Shift+K"))
        self.action_lang_km.setCheckable(True)
        self.action_lang_km.setChecked(self.current_language == "km")
        self.action_lang_km.triggered.connect(lambda: self.set_language("km"))
        self.lang_menu.addAction(self.action_lang_km)

        self.lang_menu.addSeparator()

        self.action_lang_toggle = QAction(CustomIcons.globe(), self.tr_text("action_switch_lang"), self)
        self.action_lang_toggle.setShortcut(QKeySequence("Ctrl+L"))
        self.action_lang_toggle.triggered.connect(self._toggle_language)
        self.lang_menu.addAction(self.action_lang_toggle)

        # Audio Menu
        self.audio_menu = menubar.addMenu(self.tr_text("menu_audio"))

        sound_label = self.tr_text("action_sound_toggle_on") if self.audio_manager.enabled else self.tr_text("action_sound_toggle_off")
        self.action_audio_toggle = QAction(CustomIcons.audio(self.audio_manager.enabled), sound_label, self)
        self.action_audio_toggle.setShortcut(QKeySequence("Ctrl+M"))
        self.action_audio_toggle.triggered.connect(self._toggle_audio)
        self.audio_menu.addAction(self.action_audio_toggle)

        self.action_audio_test = QAction(CustomIcons.audio(True), self.tr_text("action_test_sound"), self)
        self.action_audio_test.triggered.connect(self._test_audio)
        self.audio_menu.addAction(self.action_audio_test)

        # Help Menu
        self.help_menu = menubar.addMenu(self.tr_text("menu_help"))

        self.action_info = QAction(CustomIcons.info(), self.tr_text("action_tool_info"), self)
        self.action_info.setShortcut(QKeySequence("F1"))
        self.action_info.triggered.connect(self.show_tool_info)
        self.help_menu.addAction(self.action_info)

        self.help_menu.addSeparator()

        self.action_contact = QAction(CustomIcons.group(), self.tr_text("action_contact_admin", username=ADMIN_USERNAME), self)
        self.action_contact.triggered.connect(self.open_admin_contact)
        self.help_menu.addAction(self.action_contact)
    def _request_stop_addition(self):
        self._stop_addition = True
        self.audio_manager.play_stop()
        self.status_label.setText("Stop requested – current operation will halt")

    def open_api_credentials_page(self):
        url = QUrl("https://my.telegram.org/apps")
        if QDesktopServices.openUrl(url):
            self.status_label.setText(
                "Opened my.telegram.org/apps — log in to get your API ID and API hash."
            )
        else:
            self._show_error(
                "Could not open browser",
                "Open this address manually:\nhttps://my.telegram.org/apps",
            )

    def open_api_guide(self):
        url = QUrl("https://core.telegram.org/api/obtaining_api_id")
        if not QDesktopServices.openUrl(url):
            self._show_error(
                "Could not open browser",
                "Open this address manually:\nhttps://core.telegram.org/api/obtaining_api_id",
            )

    def open_admin_contact(self):
        url = QUrl(f"https://t.me/{ADMIN_USERNAME}")
        if QDesktopServices.openUrl(url):
            self.status_label.setText(
                f"Opened Telegram chat with @{ADMIN_USERNAME}."
            )
        else:
            self._show_error(
                "Could not open Telegram",
                f"Open this address manually:\nhttps://t.me/{ADMIN_USERNAME}",
            )

    def show_tool_info(self):
        QMessageBox.information(
            self,
            "Tool info",
            "Member Studio — Telegram Member Manager\n\n"
            "ACCOUNT LOGIN\n"
            "• Enter API ID, API hash, and your Telegram phone number.\n"
            "• Click Login with Telegram, then enter the login code from Telegram.\n"
            "• If two-step verification is enabled, enter your Telegram password.\n"
            "• The app confirms the account and saves the login session locally.\n"
            "• Each phone number keeps its own session; enter new credentials to connect another account.\n\n"
            "GET API ID AND API HASH\n"
            "• Click Get API ID and Hash above the login button.\n"
            "• Or open https://my.telegram.org/apps in a browser.\n"
            "• Log in with your Telegram phone number.\n"
            "• Open API development tools and create an app if needed.\n"
            "• Copy the API ID and API hash into the Account fields.\n"
            "• Telegram controls these values; this app cannot fetch them automatically.\n\n"
            "MEMBERS\n"
            "• Fetch members from a source group where you have access.\n"
            "• Upload usernames from a .txt file (one per line, usernames or phone numbers).\n"
            "• Scan phone numbers through Telegram (about one lookup every 3 seconds).\n"
            "• Select random entries or generate test placeholders.\n"
            "• Add members with permission confirmation and rate-limit handling.\n\n"
            "ADMIN CONTACT\n"
            f"• Telegram: @{ADMIN_USERNAME}\n"
            f"• https://t.me/{ADMIN_USERNAME}\n\n"
            "Use this tool only with permission and follow Telegram's rules.",
        )

    @classmethod
    def _create_app_icon(cls, show_checkmark=False):
        icon = QIcon()
        for size in (16, 24, 32, 48, 64, 128, 256):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            margin = max(1.0, size * 0.05)
            circle_rect = QRectF(margin, margin, size - margin * 2, size - margin * 2)
            grad = QLinearGradient(circle_rect.topLeft(), circle_rect.bottomRight())
            grad.setColorAt(0.0, QColor("#35c7e8"))
            grad.setColorAt(1.0, QColor("#1689d4"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawEllipse(circle_rect)

            scale = size / 128.0
            painter.save()
            painter.translate(circle_rect.center().x(), circle_rect.center().y())
            painter.scale(scale, scale)
            painter.translate(-64, -64)

            plane = QPainterPath()
            plane.moveTo(27, 61)
            plane.lineTo(101, 31)
            plane.lineTo(75, 99)
            plane.lineTo(59, 74)
            plane.lineTo(44, 85)
            plane.lineTo(48, 65)
            plane.closeSubpath()

            painter.setBrush(QColor("#ffffff"))
            painter.drawPath(plane)

            fold_pen = QPen(QColor("#9be8f6"), max(1.5, 3.0 * scale), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(fold_pen)
            painter.drawLine(48, 65, 101, 31)
            painter.restore()

            if show_checkmark:
                badge_size = max(4.0, size * 0.32)
                badge_rect = QRectF(size - badge_size - margin, size - badge_size - margin, badge_size, badge_size)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#4caf50"))
                painter.drawEllipse(badge_rect)
                check_pen = QPen(QColor("#ffffff"), max(1.0, 1.8 * scale), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(check_pen)
                bx = badge_rect.x()
                by = badge_rect.y()
                bw = badge_rect.width()
                bh = badge_rect.height()
                painter.drawLine(bx + bw * 0.28, by + bh * 0.52, bx + bw * 0.45, by + bh * 0.70)
                painter.drawLine(bx + bw * 0.45, by + bh * 0.70, bx + bw * 0.74, by + bh * 0.32)

            painter.end()
            icon.addPixmap(pixmap)
        return icon

    def _create_card(self, heading, description):
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(10)
        title = QLabel(heading)
        title.setObjectName("sectionTitle")
        hint = QLabel(description)
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        card_layout.addWidget(title)
        card_layout.addWidget(hint)
        card.title_label = title
        card.hint_label = hint
        return card

    @staticmethod
    def _apply_dark_palette():
        app = QApplication.instance()
        if app is None:
            return
        app.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#071522"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#081a2a"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#0f2740"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#0f2740"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#123a56"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Link, QColor("#4fc3f7"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#0f7fa5"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7fa3bb"))
        palette.setColor(QPalette.ColorRole.Light, QColor("#2b6085"))
        palette.setColor(QPalette.ColorRole.Midlight, QColor("#1e4463"))
        palette.setColor(QPalette.ColorRole.Dark, QColor("#020b13"))
        palette.setColor(QPalette.ColorRole.Mid, QColor("#0a1c2e"))
        palette.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))
        for role in (
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(
                QPalette.ColorGroup.Disabled, role, QColor("#6f8ea3")
            )
        app.setPalette(palette)

    def _apply_styles(self):
        stylesheet = (
            """
            QMainWindow {
                background-color: #071522;
            }
            QWidget {
                color: #ffffff;
                font-family: "Segoe UI", "Leelawadee UI", "Khmer UI", sans-serif;
                font-size: 10pt;
            }
            QWidget#centralPanel {
                background-color: #071522;
            }
            QScrollArea#contentScrollArea {
                background-color: #071522;
                border: none;
            }
            QLabel {
                background-color: transparent;
                color: #ffffff;
            }
            QFrame#hero {
                background-color: transparent;
                border: none;
            }
            QLabel#brandIcon {
                background: transparent;
            }
            QLabel#title {
                color: #ffffff;
                font-size: 22pt;
                font-weight: 700;
            }
            QLabel#subtitle {
                color: #d7eefb;
                font-size: 10pt;
            }
            QLabel#heroBadge {
                color: #ffffff;
                background-color: rgba(255, 255, 255, 28);
                border: 1px solid rgba(255, 255, 255, 90);
                border-radius: 10px;
                padding: 6px 10px;
                font-size: 8pt;
                font-weight: 700;
            }
            QLabel#sectionTitle {
                color: #ffffff;
                font-size: 9pt;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#sectionHint {
                color: #b9d6e8;
            }
            QLabel#status {
                color: #8fe6ff;
                font-weight: 600;
            }
            QLabel#loginStatus {
                color: #7fe0ff;
                font-weight: 600;
            }
            QLabel#controlLabel {
                color: #ffffff;
                font-weight: 600;
            }
            QLabel#adminContact {
                color: #8fb3cc;
                font-size: 9pt;
                padding-top: 4px;
            }
            QCheckBox, QCheckBox#consentCheck {
                color: #ffffff;
                spacing: 8px;
                font-weight: 600;
            }
            QCheckBox#consentCheck::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #5f9cbd;
                border-radius: 4px;
                background-color: #081a2a;
            }
            QCheckBox#consentCheck::indicator:checked {
                background-color: #12a2c9;
                border: 1px solid #12a2c9;
            }
            QFrame#card {
                background-color: #0f2740;
                border: 1px solid #1e4463;
                border-radius: 13px;
            }
            QLineEdit, QPlainTextEdit, QSpinBox {
                background-color: #081a2a;
                color: #ffffff;
                border: 1px solid #24506d;
                border-radius: 8px;
                min-height: 22px;
                padding: 7px 9px;
                selection-background-color: #0f7fa5;
                selection-color: #ffffff;
            }
            QLineEdit::placeholder {
                color: #7fa3bb;
            }
            QPlainTextEdit {
                color: #ffffff;
            }
            QListWidget {
                background-color: #081a2a;
                color: #ffffff;
                border: 1px solid #24506d;
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-radius: 4px;
                margin: 1px 0;
            }
            QListWidget::item:hover {
                background-color: #123a56;
            }
            QListWidget::item:selected {
                background-color: #0e86ad;
                color: #ffffff;
            }
            QListWidget::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #5f9cbd;
                border-radius: 4px;
                background-color: #081a2a;
            }
            QListWidget::indicator:checked {
                background-color: #12a2c9;
                border: 1px solid #12a2c9;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {
                background-color: #0a2033;
                border: 1px solid #19b6df;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 18px;
                border: none;
                background-color: #123a56;
            }
            QPushButton {
                min-height: 40px;
                padding: 0 17px;
                border: none;
                border-radius: 8px;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton#primaryButton {
                background-color: #0e86ad;
                color: #ffffff;
            }
            QPushButton#primaryButton:hover {
                background-color: #0a6f92;
            }
            QPushButton#secondaryButton {
                background-color: #123a56;
                color: #ffffff;
                border: 1px solid #2b6085;
            }
            QPushButton#secondaryButton:hover {
                background-color: #1a4d6e;
            }
            QPushButton#quietButton {
                background-color: #0b2136;
                color: #ffffff;
                border: 1px solid #24506d;
            }
            QPushButton#quietButton:hover {
                background-color: #123754;
            }
            QPushButton:disabled {
                background-color: #0b2237;
                color: #6f8ea3;
                border: 1px solid #17364d;
            }
            QScrollBar:vertical {
                width: 12px;
                background: #0a1c2e;
                margin: 2px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #2b6085;
                min-height: 28px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3f7fa8;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                height: 12px;
                background: #0a1c2e;
                margin: 2px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #2b6085;
                min-width: 28px;
                border-radius: 6px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QProgressBar {
                height: 12px;
                background-color: #102d45;
                border: none;
                border-radius: 6px;
                text-align: center;
                color: transparent;
            }
            QProgressBar::chunk {
                background-color: #12a2c9;
                border-radius: 5px;
            }
            QDialog, QMessageBox, QInputDialog {
                background-color: #0a1c2e;
                color: #ffffff;
            }
            QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {
                color: #ffffff;
                background-color: transparent;
            }
            QMessageBox QTextEdit, QMessageBox QPlainTextEdit {
                background-color: #081a2a;
                color: #ffffff;
                border: 1px solid #24506d;
            }
            QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
                background-color: #123a56;
                color: #ffffff;
                border: 1px solid #2b6085;
                border-radius: 7px;
                min-height: 32px;
                min-width: 80px;
                padding: 5px 16px;
                font-weight: 600;
            }
            QDialog QPushButton:hover, QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
                background-color: #1a4d6e;
            }
            QMenuBar {
                background-color: #0a1c2e;
                color: #ffffff;
                border-bottom: 1px solid #1e4463;
                padding: 2px;
            }
            QMenuBar::item {
                color: #ffffff;
                background: transparent;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background-color: #123a56;
            }
            QMenuBar::item:pressed {
                background-color: #0e86ad;
            }
            QMenu {
                background-color: #0f2740;
                color: #ffffff;
                border: 1px solid #24506d;
                padding: 6px;
            }
            QMenu::item {
                color: #ffffff;
                padding: 7px 24px 7px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0e86ad;
                color: #ffffff;
            }
            QMenu::item:disabled {
                color: #6f8ea3;
            }
            QMenu::separator {
                height: 1px;
                background: #1e4463;
                margin: 4px 8px;
            }
            QToolTip {
                background-color: #0f2740;
                color: #ffffff;
                border: 1px solid #2b6085;
                padding: 4px;
            }
            """
        )
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        else:
            self.setStyleSheet(stylesheet)

    def _show_error(self, title, message):
        self.audio_manager.play_alert()
        QMessageBox.critical(self, title, message)

    def _set_busy(self, busy):
        for name in (
            "login_button",
            "fetch_button",
            "add_button",
            "generate_button",
            "random_numbers_button",
            "scan_button",
            "browse_button",
            "upload_start_btn",
            "upload_txt_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(not busy)

    @staticmethod
    def _normalize_phone(raw_phone):
        if not raw_phone:
            return ""
        text = str(raw_phone).strip()
        compact = re.sub(r"[\s().-]", "", text)
        if not compact:
            return ""

        if compact.startswith("00"):
            compact = "+" + compact[2:]

        if compact.startswith("+8550"):
            compact = "+855" + compact[5:]
        elif compact.startswith("8550") and len(compact) in (12, 13):
            compact = "+855" + compact[4:]
        elif compact.startswith("+855"):
            pass
        elif compact.startswith("855") and len(compact) in (11, 12):
            compact = "+" + compact
        elif compact.startswith("0") and len(compact) in (8, 9, 10, 11):
            compact = "+855" + compact[1:]
        elif not compact.startswith("+"):
            if len(compact) in (8, 9) and compact.isdigit():
                compact = "+855" + compact
            else:
                compact = "+" + compact

        return compact

    @staticmethod
    def _is_phone_number(value):
        text = (value or "").strip()
        if not text:
            return False
        compact = re.sub(r"[\s().-]", "", text)
        if compact.startswith("+"):
            return bool(re.fullmatch(r"\+\d{7,15}", compact))
        if not compact.isdigit():
            return False
        if compact.startswith("00"):
            return 9 <= len(compact) <= 17
        if compact.startswith("855"):
            return 11 <= len(compact) <= 13
        if compact.startswith("0"):
            return 8 <= len(compact) <= 11
        if len(compact) in (8, 9):
            return True
        return 10 <= len(compact) <= 15

    def _cache_user(self, user):
        if getattr(user, "username", None):
            self._participant_cache[user.username.casefold()] = user
            self._participant_cache[f"@{user.username}".casefold()] = user
        if getattr(user, "phone", None):
            self._participant_cache[f"+{user.phone}".casefold()] = user
            self._participant_cache[str(user.phone).casefold()] = user
        self._participant_cache[str(user.id)] = user

    def _lookup_phone(self, phone):
        normalized = self._normalize_phone(phone)
        if not normalized:
            raise ValueError("empty phone number")

        wait_seconds = 3.1 - (time.monotonic() - self._last_phone_lookup)
        if self._last_phone_lookup and wait_seconds > 0:
            self.status_label.setText(
                f"Telegram allows one phone lookup every 3 seconds. Waiting {wait_seconds:.1f} seconds..."
            )
            QApplication.processEvents()
            time.sleep(wait_seconds)
        self._last_phone_lookup = time.monotonic()

        try:
            result = self.client(ResolvePhoneRequest(phone=normalized))
        except (PhoneNotOccupiedError, PhoneNumberUnoccupiedError):
            raise ValueError("number is not linked to a Telegram account") from None
        except PhoneNumberInvalidError:
            raise ValueError("invalid phone number") from None

        users = [
            user
            for user in getattr(result, "users", [])
            if not getattr(user, "bot", False)
            and not getattr(user, "deleted", False)
        ]
        if not users:
            raise ValueError("number not found, or privacy settings block phone lookup")

        user = users[0]
        self._cache_user(user)
        self._participant_cache[phone.strip().casefold()] = user
        self._participant_cache[normalized.casefold()] = user
        self._participant_cache[normalized.lstrip("+").casefold()] = user
        return user

    @staticmethod
    def _sessions_folder():
        app_data = os.getenv("APPDATA")
        if app_data:
            folder = Path(app_data) / "TelegramMemberManager" / "sessions"
        else:
            folder = Path.home() / "AppData" / "Roaming" / "TelegramMemberManager" / "sessions"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @classmethod
    def _session_path(cls, phone_number):
        digits = re.sub(r"\D", "", phone_number or "") or "default"
        name = f"telegram_adder_session_{digits}"
        appdata_sessions = cls._sessions_folder()
        primary_file = appdata_sessions / f"{name}.session"
        if primary_file.is_file():
            return str(primary_file.with_suffix(""))

        exe_dir = Path(sys.executable).parent
        cwd = Path.cwd()
        script_dir = Path(__file__).resolve().parent

        candidates = (
            primary_file,
            appdata_sessions.parent / f"{name}.session",
            cwd / "TelegramAdder" / "sessions" / f"{name}.session",
            cwd / "sessions" / f"{name}.session",
            cwd / f"{name}.session",
            exe_dir / "sessions" / f"{name}.session",
            exe_dir / f"{name}.session",
            exe_dir.parent / "sessions" / f"{name}.session",
            exe_dir.parent / "TelegramAdder" / "sessions" / f"{name}.session",
            script_dir / "sessions" / f"{name}.session",
            script_dir / f"{name}.session",
            script_dir.parent / "sessions" / f"{name}.session",
            script_dir.parent / "TelegramAdder" / "sessions" / f"{name}.session",
        )
        for candidate in candidates:
            if candidate.is_file():
                try:
                    shutil.copy2(candidate, primary_file)
                    return str(primary_file.with_suffix(""))
                except Exception:
                    return str(candidate.with_suffix(""))

        return str(primary_file.with_suffix(""))

    def _migrate_legacy_session(self):
        if not self._saved_phone:
            return
        digits = re.sub(r"\D", "", self._saved_phone)
        if not digits:
            return
        sessions_dir = Path(__file__).resolve().parent / "sessions"
        account_session = sessions_dir / f"telegram_adder_session_{digits}.session"
        if account_session.exists():
            return
        legacy_candidates = (
            Path.cwd() / "telegram_adder_session.session",
            Path(__file__).resolve().parent / "telegram_adder_session.session",
            Path(__file__).resolve().parent.parent / "telegram_adder_session.session",
        )
        for legacy_session in legacy_candidates:
            if not legacy_session.exists():
                continue
            try:
                sessions_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_session, account_session)
            except OSError:
                pass
            return

    @staticmethod
    def _account_name(user):
        full_name = " ".join(
            part
            for part in (user.first_name or "", user.last_name or "")
            if part
        )
        return full_name or user.username or str(user.id)

    def _disconnect_client(self):
        if self.client is not None:
            try:
                if self.client.is_connected():
                    self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self._client_signature = None

    def connect_client(self):
        try:
            api_id = int(self.api_id_entry.text().strip())
            if api_id <= 0:
                raise ValueError
        except ValueError:
            self._show_error(
                "Invalid API ID", "Enter the numeric API ID from my.telegram.org."
            )
            return False

        api_hash = self.api_hash_entry.text().strip()
        phone_number = self._normalize_phone(self.phone_entry.text())
        if not api_hash or not phone_number:
            QMessageBox.warning(
                self,
                "Credentials required",
                "Enter your Telegram API hash and phone number to continue.",
            )
            return False

        signature = (api_id, api_hash, phone_number)
        if self.client is not None and self._client_signature != signature:
            self._disconnect_client()

        if self.client is None:
            try:
                self.client = TelegramClient(
                    self._session_path(phone_number), api_id, api_hash
                )
            except Exception as exc:
                self._show_error("Client error", f"Could not start Telegram: {exc}")
                return False
            self._client_signature = signature

        try:
            if not self.client.is_connected():
                self.client.connect()
        except Exception as exc:
            self._show_error("Connection error", f"Could not connect to Telegram: {exc}")
            self._disconnect_client()
            return False

        self.phone_number = phone_number
        self.phone_entry.setText(phone_number)
        return True

    def _request_two_factor_password(self):
        for _ in range(3):
            password, accepted = QInputDialog.getText(
                self,
                "Two-step verification",
                "Enter your Telegram password:",
                QLineEdit.EchoMode.Password,
            )
            if not accepted:
                return False
            if not password:
                QMessageBox.warning(
                    self, "Password required", "Enter your Telegram password."
                )
                continue
            try:
                self.client.sign_in(password=password)
                return True
            except PasswordHashInvalidError:
                QMessageBox.warning(
                    self,
                    "Incorrect password",
                    "The Telegram password was incorrect. Try again.",
                )
        return False

    def _update_login_status(self, user):
        username = f" (@{user.username})" if user.username else ""
        is_premium = bool(getattr(user, "premium", False))
        prem_badge = " ⭐ [PREMIUM]" if is_premium else ""
        self.login_status.setText(f"Signed in as {self._account_name(user)}{username}{prem_badge}")
        self.login_button.setText("Confirm account")
        # Update the window icon to show a checkmark when the account is confirmed
        try:
            is_authorized = self.client is not None and self.client.is_connected() and self.client.is_user_authorized()
        except Exception:
            is_authorized = False
        self.setWindowIcon(self._create_app_icon(show_checkmark=is_authorized))
        if hasattr(self, "hero_logo"):
            self.hero_logo.set_checkmark(is_authorized)

    def _show_account_confirmation(self, user):
        username = f" (@{user.username})" if user.username else ""
        is_premium = bool(getattr(user, "premium", False))
        details = [
            f"Signed in as {self._account_name(user)}{username}",
            f"User ID: {user.id}",
        ]
        if getattr(user, "phone", None):
            details.append(f"Phone: +{user.phone}")
        if is_premium:
            details.append("Account Tier: ⭐ Telegram Premium (Unlimited Invites Enabled / គ្មានកម្រិតកំណត់)")
        else:
            details.append("Account Tier: Standard Telegram")
        details.extend(
            [
                "",
                "This Telegram account is confirmed and ready to use.",
            ]
        )
        QMessageBox.information(
            self, "Telegram account confirmed", "\n".join(details)
        )

    def login_account(self):
        norm_phone = self._normalize_phone(self.phone_entry.text())
        existing_phones = {self._normalize_phone(a.get("phone_number", "")) for a in self.accounts}
        if norm_phone not in existing_phones and len(self.accounts) >= self.MAX_ACCOUNTS:
            QMessageBox.warning(
                self,
                "Account limit reached" if self.current_language == "en" else "ដល់កម្រិតកំណត់គណនី",
                f"You have reached the maximum limit of {self.MAX_ACCOUNTS} accounts.\nPlease remove an account before adding a new one."
                if self.current_language == "en"
                else f"អ្នកបានដល់ចំនួនកំណត់អតិបរមា {self.MAX_ACCOUNTS} គណនីហើយ។\nសូមលុបគណនីចាស់ចេញជាមុនសិន មុននឹងបន្ថែមគណនីថ្មី។",
            )
            return

        if not self.connect_client():
            return
        self._set_busy(True)
        self.login_button.setText("Connecting...")
        QApplication.processEvents()
        try:
            self.authenticate_client(show_confirmation=True)
        finally:
            self._set_busy(False)
            try:
                is_authorized = (
                    self.client is not None
                    and self.client.is_connected()
                    and self.client.is_user_authorized()
                )
            except Exception:
                is_authorized = False
            self.login_button.setText(
                "Confirm account" if is_authorized else "Login with Telegram"
            )

    def authenticate_client(self, show_confirmation=False):
        if self.client is None or not self.client.is_connected():
            if not self.connect_client():
                return False

        try:
            if not self.client.is_user_authorized():
                self.status_label.setText("Requesting a Telegram login code...")
                QApplication.processEvents()
                try:
                    sent_code = self.client.send_code_request(self.phone_number)
                except PhoneNumberInvalidError:
                    self._show_error(
                        "Invalid phone number",
                        "Telegram rejected that phone number. Enter it with the country code.",
                    )
                    return False
                except SendCodeUnavailableError:
                    self._show_error(
                        "Code unavailable",
                        "Telegram could not send a login code. Try again later.",
                    )
                    return False
                except FloodWaitError as exc:
                    self._show_error(
                        "Flood wait",
                        f"Telegram asked you to wait {exc.seconds} seconds before requesting another code.",
                    )
                    return False
                except AuthRestartError:
                    self._show_error(
                        "Authentication error",
                        "Telegram requested an authentication restart. Please try again.",
                    )
                    return False

                for attempt in range(3):
                    auth_code, accepted = QInputDialog.getText(
                        self,
                        "Confirm Telegram account",
                        "Telegram sent a login code to your Telegram app for\n"
                        f"{self.phone_number}.\n\n"
                        "Enter the code to confirm this account:",
                    )
                    if not accepted or not auth_code.strip():
                        self.status_label.setText("Login cancelled")
                        return False
                    try:
                        self.client.sign_in(
                            phone=self.phone_number,
                            code=auth_code.strip(),
                            phone_code_hash=sent_code.phone_code_hash,
                        )
                        break
                    except SessionPasswordNeededError:
                        if not self._request_two_factor_password():
                            self.status_label.setText("Login cancelled")
                            return False
                        break
                    except PhoneCodeInvalidError:
                        if attempt == 2:
                            self._show_error(
                                "Invalid code",
                                "The login code was incorrect. Click Login with Telegram to request a new code.",
                            )
                            return False
                        QMessageBox.warning(
                            self, "Invalid code", "That code was incorrect. Try again."
                        )
                    except PhoneCodeExpiredError:
                        self._show_error(
                            "Code expired",
                            "The login code expired. Click Login with Telegram to request a new code.",
                        )
                        return False
                    except FloodWaitError as exc:
                        self._show_error(
                            "Flood wait",
                            f"Telegram asked you to wait {exc.seconds} seconds before trying again.",
                        )
                        return False
                else:
                    return False

            user = self.client.get_me()
            if user is None:
                self._show_error(
                    "Account not confirmed",
                    "Telegram did not return account details. Please log in again.",
                )
                return False

            is_premium = bool(getattr(user, "premium", False))
            new_acc = {
                "api_id": self.api_id_entry.text().strip(),
                "api_hash": self.api_hash_entry.text().strip(),
                "phone_number": self.phone_number,
                "user_id": user.id,
                "first_name": user.first_name or "",
                "username": user.username or "",
                "is_premium": is_premium,
                "enabled": True,
            }
            norm_new = self._normalize_phone(self.phone_number)
            for i, existing in enumerate(self.accounts):
                if self._normalize_phone(existing.get("phone_number")) == norm_new:
                    self.accounts[i] = new_acc
                    break
            else:
                self.accounts.append(new_acc)

            self._save_credentials()
            self._refresh_accounts_list()
            self._update_login_status(user)
            self.audio_manager.play_success()
            self.status_label.setText(f"Connected: {self._account_name(user)}")
            if show_confirmation:
                self._show_account_confirmation(user)
            return True
        except (
            SendCodeUnavailableError,
            AuthRestartError,
            PhoneNumberInvalidError,
            FloodWaitError,
        ) as exc:
            self._show_error("Telegram login failed", str(exc))
            return False
        except Exception as exc:
            self._show_error("Telegram login failed", f"Could not sign in: {exc}")
            return False

    def _resolve_member(self, member):
        cached = self._participant_cache.get(member.strip().casefold())
        if cached is not None:
            return cached
        if self._is_phone_number(member):
            return self._lookup_phone(member)
        return self.client.get_entity(member.strip())

    def _resolve_member_with_wait(self, member):
        for _ in range(2):
            try:
                return self._resolve_member(member)
            except FloodWaitError as exc:
                self.status_label.setText(
                    f"Telegram flood wait: waiting {exc.seconds} seconds before continuing..."
                )
                QApplication.processEvents()
                time.sleep(max(1, exc.seconds))
        return self._resolve_member(member)

    def _resolve_member_for_client(self, client, member):
        cached = self._participant_cache.get(member.strip().casefold())
        if cached is not None:
            return cached
        if self._is_phone_number(member):
            normalized = self._normalize_phone(member)
            wait_seconds = 3.1 - (time.monotonic() - self._last_phone_lookup)
            if self._last_phone_lookup and wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_phone_lookup = time.monotonic()
            result = client(ResolvePhoneRequest(phone=normalized))
            users = [
                u for u in getattr(result, "users", [])
                if not getattr(u, "bot", False) and not getattr(u, "deleted", False)
            ]
            if not users:
                raise ValueError("number not found or blocked by privacy")
            user = users[0]
            self._cache_user(user)
            return user
        user = client.get_entity(member.strip())
        self._cache_user(user)
        return user

    def add_members(self, group_link, member_list):
        """Add members across multiple connected accounts in rotation without collisions (ចែកគ្នាធ្វើការ មិនជាន់គ្នា)."""
        active_accounts = self._get_active_accounts()
        if not active_accounts:
            self._show_error(
                "No active accounts" if self.current_language == "en" else "គ្មានគណនីសកម្ម",
                "Please connect and select at least one Telegram account before adding members."
                if self.current_language == "en"
                else "សូមភ្ជាប់ និងជ្រើសរើសយ៉ាងហោចណាស់គណនី Telegram មួយ មុនពេលបន្ថែមសមាជិក។",
            )
            return

        self.status_label.setText(
            f"Connecting {len(active_accounts)} account(s)..."
            if self.current_language == "en"
            else f"កំពុងភ្ជាប់គណនីចំនួន {len(active_accounts)}..."
        )
        QApplication.processEvents()

        # Disconnect GUI client to release SQLite locks on session files
        self._disconnect_client()

        workers = []
        need_save_accs = False
        for acc in active_accounts:
            phone = self._normalize_phone(acc.get("phone_number", ""))
            try:
                api_id = int(acc.get("api_id", 0))
                api_hash = acc.get("api_hash", "")
                if not phone or api_id <= 0 or not api_hash:
                    continue
                session = self._session_path(phone)
                client = TelegramClient(session, api_id, api_hash)
                client.connect()
                if not client.is_user_authorized():
                    print(f"Account {phone} not authorized; skipping.")
                    continue

                me = client.get_me()
                is_premium = bool(getattr(me, "premium", False)) if me else False
                if acc.get("is_premium") != is_premium:
                    acc["is_premium"] = is_premium
                    need_save_accs = True

                workers.append({
                    "account": acc,
                    "phone": phone,
                    "client": client,
                    "target_group": None,
                    "invites_done": 0,
                    "status": "ready",
                    "is_premium": is_premium,
                })
            except Exception as exc:
                print(f"Could not connect worker {phone}: {exc}")

        if need_save_accs:
            self._save_credentials()
            self._refresh_accounts_list()

        if not workers:
            self._show_error(
                "Accounts not ready" if self.current_language == "en" else "គណនីមិនទាន់រួចរាល់",
                "None of the selected accounts are authorized. Please log in first."
                if self.current_language == "en"
                else "គ្មានគណនីណាមួយដែលបានជ្រើសរើសមានសិទ្ធិចូលទេ។ សូម Login ជាមុនសិន។",
            )
            return

        # Resolve target group for each worker and auto-join
        valid_workers = []
        for w in workers:
            try:
                target = w["client"].get_entity(group_link)
                # Auto-join target group if account is not a participant yet
                try:
                    w["client"](JoinChannelRequest(target))
                except Exception:
                    pass
                w["target_group"] = target
                valid_workers.append(w)
            except Exception as exc:
                print(f"Account {w['phone']} cannot access target group {group_link}: {exc}")

        if not valid_workers:
            self._show_error(
                "Target group inaccessible" if self.current_language == "en" else "មិនអាចចូលក្រុមគោលដៅ",
                f"None of your accounts could access {group_link}. Ensure the group link is correct."
                if self.current_language == "en"
                else f"គ្មានគណនីណាមួយអាចចូលក្រុម {group_link} បានទេ។ សូមពិនិត្យតំណភ្ជាប់ក្រុម។",
            )
            for w in workers:
                try:
                    w["client"].disconnect()
                except Exception:
                    pass
            return

        total_members = len(member_list) or 1
        max_per_account = self.max_per_account_spin.value() if hasattr(self, "max_per_account_spin") else 30
        added_count = 0
        skipped_count = 0
        worker_idx = 0
        delay = self.speed_scale.value()

        try:
            for idx, member in enumerate(member_list):
                if self._stop_addition:
                    self._stop_addition = False
                    self.audio_manager.play_stop()
                    self.status_label.setText("Stopped by user" if self.current_language == "en" else "បានបញ្ឈប់ដោយអ្នកប្រើប្រាស់")
                    break

                # Get available healthy workers:
                # Regular accounts: invites_done < max_per_account
                # Telegram Premium accounts: NO LIMIT (Unlimited invites / គ្មានកម្រិតកំណត់)!
                available = [
                    w for w in valid_workers
                    if w["status"] == "ready" and (w.get("is_premium") or w["invites_done"] < max_per_account)
                ]
                if not available:
                    msg = (
                        "All accounts reached their invite limits or were restricted."
                        if self.current_language == "en"
                        else "គណនីទាំងអស់បានដល់កម្រិតកំណត់ ឬជាប់កំហិតហើយ។"
                    )
                    self.status_label.setText(msg)
                    break

                # Round-robin worker selection (ចែកគ្នាធ្វើការ មិនជាន់គ្នា)
                worker = available[worker_idx % len(available)]
                worker_idx += 1
                client = worker["client"]
                target_group = worker["target_group"]
                phone = worker["phone"]

                self.progress_bar.setValue((idx + 1) * 100 // total_members)
                prem_indicator = " ⭐ Premium" if worker.get("is_premium") else ""
                status_msg = (
                    f"[{phone}{prem_indicator}] Inviting {member} ({idx + 1}/{total_members})..."
                    if self.current_language == "en"
                    else f"[{phone}{prem_indicator}] កំពុងអញ្ជើញ {member} ({idx + 1}/{total_members})..."
                )
                self.status_label.setText(status_msg)
                QApplication.processEvents()

                # Resolve user
                try:
                    user = self._resolve_member_for_client(client, member)
                except Exception as exc:
                    skipped_count += 1
                    print(f"Could not resolve member {member}: {exc}")
                    continue

                # Skip Deleted Account
                user_full_name = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip().casefold()
                if getattr(user, "deleted", False) or "deleted account" in user_full_name:
                    skipped_count += 1
                    print(f"{member} is a deleted account, skipping invite")
                    continue

                # Check participation
                try:
                    client(GetParticipantRequest(target_group, user.id))
                    skipped_count += 1
                    print(f"{user.id} already a participant, skipping")
                    continue
                except UserNotParticipantError:
                    pass
                except Exception as exc:
                    skipped_count += 1
                    print(f"Could not check participation for {user.id}: {exc}")
                    continue

                # Invite
                retries = 2
                while retries > 0:
                    try:
                        client(InviteToChannelRequest(target_group, [user]))
                        added_count += 1
                        worker["invites_done"] += 1
                        self.audio_manager.play_success()
                        time.sleep(delay)
                        break
                    except PeerFloodError:
                        worker["status"] = "limited"
                        print(f"Account {phone} reached spam limit (PeerFloodError).")
                        available_now = [
                            w for w in valid_workers
                            if w["status"] == "ready" and w["invites_done"] < max_per_account
                        ]
                        if available_now:
                            worker_idx += 1
                            alt_worker = available_now[worker_idx % len(available_now)]
                            try:
                                alt_worker["client"](InviteToChannelRequest(alt_worker["target_group"], [user]))
                                added_count += 1
                                alt_worker["invites_done"] += 1
                                self.audio_manager.play_success()
                                time.sleep(delay)
                            except Exception:
                                skipped_count += 1
                        else:
                            skipped_count += 1
                        break
                    except FloodWaitError as exc:
                        if exc.seconds <= 12:
                            time.sleep(exc.seconds)
                            retries -= 1
                        else:
                            worker["status"] = "flood_wait"
                            print(f"Account {phone} flood wait {exc.seconds}s; switching.")
                            skipped_count += 1
                            break
                    except UserAlreadyParticipantError:
                        skipped_count += 1
                        break
                    except (
                        UserPrivacyRestrictedError,
                        UserNotMutualContactError,
                        UserChannelsTooMuchError,
                        UserKickedError,
                        UserBannedInChannelError,
                        InputUserDeactivatedError,
                    ) as exc:
                        skipped_count += 1
                        print(f"Telegram refused {member}: {exc}")
                        break
                    except ChatAdminRequiredError:
                        worker["status"] = "no_admin"
                        skipped_count += 1
                        break
                    except Exception as exc:
                        skipped_count += 1
                        print(f"Failed to add {member} with {phone}: {exc}")
                        break

            self.progress_bar.setValue(100)
            self.audio_manager.play_complete()
            self.status_label.setText("Finished" if self.current_language == "en" else "បានបញ្ចប់")

            # Account breakdown
            breakdown_lines = []
            for w in valid_workers:
                p_num = w["phone"]
                inv = w["invites_done"]
                status_note = ""
                if w["status"] == "limited":
                    status_note = " (Spam limited / ជាប់ស្ពែម)"
                elif w["status"] == "flood_wait":
                    status_note = " (Flood wait / រង់ចាំ)"
                prem_note = " ⭐ [PREMIUM - Unlimited]" if w.get("is_premium") else ""
                breakdown_lines.append(f"  • {p_num}{prem_note}: {inv} added{status_note}")

            breakdown_text = "\n".join(breakdown_lines)
            if self.current_language == "km":
                summary = (
                    "ការអញ្ជើញសមាជិកត្រូវបានបញ្ចប់!\n\n"
                    f"សរុបបានបន្ថែម: {added_count}\n"
                    f"រំលង ឬបរាជ័យ: {skipped_count}\n\n"
                    f"បែងចែកតាមគណនី (ចែកគ្នាធ្វើការ):\n{breakdown_text}"
                )
            else:
                summary = (
                    "Invite processing finished!\n\n"
                    f"Total Added: {added_count}\n"
                    f"Skipped or Failed: {skipped_count}\n\n"
                    f"Account Breakdown (Load-balanced):\n{breakdown_text}"
                )
            QMessageBox.information(self, "Finished" if self.current_language == "en" else "បានបញ្ចប់", summary)

        finally:
            for w in workers:
                try:
                    w["client"].disconnect()
                except Exception:
                    pass

    @staticmethod
    def _parse_members_from_text(text):
        """Extract and clean usernames, phone numbers, and user IDs from raw text."""
        invite_link_pattern = re.compile(
            r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)",
            re.IGNORECASE,
        )
        tme_user_pattern = re.compile(
            r"^(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{3,32})/?$",
            re.IGNORECASE,
        )
        results = []
        seen = set()

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            # Support comma or semicolon separated values on the same line
            parts = re.split(r"[,;]+", line)
            for part in parts:
                item = part.strip().strip("'\"")
                if not item:
                    continue

                # Skip Telegram group/channel invite links
                if invite_link_pattern.match(item):
                    continue

                # Convert t.me/username or https://t.me/username to @username
                tme_match = tme_user_pattern.match(item)
                if tme_match:
                    item = f"@{tme_match.group(1)}"
                elif re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{3,31}", item):
                    item = f"@{item}"

                normalized = item.lstrip("@").casefold()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    results.append(item)

        return results

    def _read_text_file(self, file_path):
        """Read text file handling UTF-8, UTF-8 BOM, ANSI, and Latin-1."""
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                self._show_error(
                    "Could not read file",
                    f"Error reading {file_path}:\n{exc}",
                )
                return None
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError as exc:
            self._show_error(
                "Could not read file",
                f"Error reading {file_path}:\n{exc}",
            )
            return None

    def _browse_upload_file(self):
        """Open a file dialog and load usernames from the selected .txt file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select user list text file",
            "",
            "Text files (*.txt);;All files (*)",
        )
        if not file_path:
            return

        if hasattr(self, "upload_path_edit"):
            self.upload_path_edit.setText(file_path)
        self.load_users_from_file(file_path)

    def upload_users_from_file(self):
        """Menu action – open file dialog and load users."""
        self._browse_upload_file()

    def load_users_from_file(self, file_path=None):
        """Read users from the given or selected file and load them into Member List."""
        if not file_path and hasattr(self, "upload_path_edit"):
            file_path = self.upload_path_edit.text().strip()
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select user list text file",
                "",
                "Text files (*.txt);;All files (*)",
            )
        if not file_path or not os.path.isfile(file_path):
            self._show_error(
                "File not found",
                f"The selected file does not exist:\n{file_path}",
            )
            return False

        content = self._read_text_file(file_path)
        if content is None:
            return False

        members = self._parse_members_from_text(content)
        if not members:
            QMessageBox.warning(
                self,
                "No members found",
                f"No valid usernames, phone numbers, or user IDs were found in:\n{Path(file_path).name}",
            )
            self.status_label.setText("No members found in file")
            return False

        self._set_member_list(members)
        file_name = Path(file_path).name
        self.status_label.setText(
            f"Loaded {len(members)} users from {file_name}"
        )
        QMessageBox.information(
            self,
            "Users loaded",
            f"Loaded {len(members)} unique users from:\n{file_name}\n\n"
            "Review the list in the Member List section, verify permission, and click Add members (or Start from file).",
        )
        return True

    def start_upload_users(self):
        """Read txt file, ensure target group is set, and add users to group."""
        file_path = self.upload_path_edit.text().strip()
        if not file_path:
            self._browse_upload_file()
            file_path = self.upload_path_edit.text().strip()
            if not file_path:
                return

        if not os.path.isfile(file_path):
            self._show_error(
                "File not found",
                f"The selected file does not exist:\n{file_path}",
            )
            return

        group_link = self.group_entry.text().strip()
        if not group_link:
            QMessageBox.warning(
                self,
                "Target group required",
                "Enter a target group link or username first.",
            )
            self.group_entry.setFocus()
            return

        content = self._read_text_file(file_path)
        if content is None:
            return

        members = self._parse_members_from_text(content)
        if not members:
            QMessageBox.warning(
                self,
                "No members found",
                f"No valid usernames, phone numbers, or user IDs were found in:\n{Path(file_path).name}",
            )
            return

        self._set_member_list(members)
        self.permission_confirmation.setChecked(True)

        answer = QMessageBox.question(
            self,
            "Confirm addition",
            f"Found {len(members)} unique users in:\n{Path(file_path).name}\n\n"
            f"Target group: {group_link}\n\n"
            "Do you want to start adding them now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.progress_bar.setValue(0)
        self.status_label.setText("Checking Telegram login...")
        self._set_busy(True)
        try:
            self.add_members(group_link, members)
        finally:
            self._set_busy(False)

    def fetch_members_from_group(self, source_group_link):
        if not self.connect_client() or not self.authenticate_client():
            return

        self.status_label.setText("Fetching members from the source group...")
        QApplication.processEvents()
        try:
            source_group = self.client.get_entity(source_group_link)
        except Exception as exc:
            self._show_error(
                "Source group unavailable",
                f"Could not open {source_group_link}: {exc}",
            )
            return

        # Auto-join source group if account is not a member yet
        try:
            self.client(JoinChannelRequest(source_group))
        except Exception:
            pass

        try:
            participants = self.client.get_participants(source_group)
        except ChatAdminRequiredError:
            self._show_error(
                "Permission required",
                "Telegram requires admin access to read that group's member list.",
            )
            return
        except FloodWaitError as exc:
            self._show_error(
                "Flood wait",
                f"Telegram asked you to wait {exc.seconds} seconds before fetching members.",
            )
            return
        except Exception as exc:
            self._show_error("Could not fetch members", str(exc))
            return

        self._participant_cache.clear()
        identifiers = []
        seen = set()
        deleted_count = 0
        bot_count = 0

        for user in participants:
            # Skip Deleted Accounts, Bots, and Self
            first_name = (getattr(user, "first_name", "") or "").strip()
            last_name = (getattr(user, "last_name", "") or "").strip()
            full_name = f"{first_name} {last_name}".strip().casefold()

            if getattr(user, "deleted", False) or "deleted account" in full_name:
                deleted_count += 1
                continue
            if getattr(user, "bot", False):
                bot_count += 1
                continue
            if getattr(user, "is_self", False):
                continue

            if getattr(user, "username", None):
                identifier = f"@{user.username}"
            elif getattr(user, "phone", None):
                identifier = f"+{user.phone}"
            else:
                identifier = str(user.id)
            key = identifier.casefold()
            if key in seen:
                continue
            seen.add(key)
            identifiers.append(identifier)
            self._participant_cache[key] = user
            self._participant_cache[str(user.id)] = user

        if not identifiers:
            QMessageBox.warning(
                self,
                "No members found" if self.current_language == "en" else "រកមិនឃើញសមាជិក",
                "No usable members were returned (all accounts were deleted or bots)."
                if self.current_language == "en"
                else "រកមិនឃើញសមាជិកដែលប្រើការបានទេ (គណនីទាំងអស់សុទ្ធតែត្រូវបានលុប ឬជា Bot)។",
            )
            self.status_label.setText("No active members found")
            return

        # Add / Join into existing member list without duplicates
        existing_members = self._get_member_candidates()
        if existing_members:
            combined = []
            seen_existing = set()
            for m in existing_members:
                k = m.lstrip("@").casefold()
                if k not in seen_existing:
                    seen_existing.add(k)
                    combined.append(m)
            added_new = 0
            for m in identifiers:
                k = m.lstrip("@").casefold()
                if k not in seen_existing:
                    seen_existing.add(k)
                    combined.append(m)
                    added_new += 1
            self._set_member_list(combined)
            total_count = len(combined)
            self.status_label.setText(
                f"Fetched {len(identifiers)} members (added {added_new} new to list, total: {total_count})"
                if self.current_language == "en"
                else f"ទាញយកបាន {len(identifiers)} នាក់ (បានបញ្ចូលបន្ថែម {added_new} នាក់ថ្មី, សរុប: {total_count} នាក់)"
            )
            summary_info = (
                f"Fetched {len(identifiers)} active members from source group.\n"
                f"Joined into list: +{added_new} new (Total in list: {total_count})\n"
                f"Skipped {deleted_count} deleted accounts and {bot_count} bots."
                if self.current_language == "en"
                else f"ទាញយកបាន {len(identifiers)} សមាជិកសកម្មពីក្រុមប្រភព។\n"
                     f"បានបញ្ចូលក្នុងបញ្ជី: +{added_new} នាក់ថ្មី (សរុបក្នុងបញ្ជី: {total_count} នាក់)\n"
                     f"បានរំលងគណនីដែលលុប (Deleted Account) ចំនួន {deleted_count} នាក់ និង Bot ចំនួន {bot_count}។"
            )
        else:
            self._set_member_list(identifiers)
            total_count = len(identifiers)
            self.status_label.setText(
                f"Fetched {total_count} members from source group"
                if self.current_language == "en"
                else f"ទាញយកបាន {total_count} សមាជិកពីក្រុមប្រភព"
            )
            summary_info = (
                f"Fetched {total_count} active members.\n"
                f"Skipped {deleted_count} deleted accounts and {bot_count} bots."
                if self.current_language == "en"
                else f"ទាញយកបាន {total_count} សមាជិកសកម្ម។\n"
                     f"បានរំលងគណនីដែលលុប (Deleted Account) ចំនួន {deleted_count} នាក់ និង Bot ចំនួន {bot_count}។"
            )

        self.audio_manager.play_success()
        QMessageBox.information(
            self,
            "Members fetched" if self.current_language == "en" else "ទាញយកសមាជិករួចរាល់",
            summary_info,
        )
    def start_fetching(self):
        source_group_link = self.source_group_entry.text().strip()
        if not source_group_link:
            QMessageBox.warning(
                self, "Input required", "Enter a source group link first."
            )
            return
        self._set_busy(True)
        try:
            self.fetch_members_from_group(source_group_link)
        finally:
            self._set_busy(False)

    def scan_phone_numbers(self):
        candidates = self._get_member_candidates()
        phone_entries = [
            candidate for candidate in candidates if self._is_phone_number(candidate)
        ]
        if not phone_entries:
            QMessageBox.information(
                self,
                "No phone numbers",
                "The member list does not contain any phone numbers to scan.",
            )
            return

        if len(phone_entries) > 5:
            estimated_seconds = len(phone_entries) * 3
            answer = QMessageBox.question(
                self,
                "Scan phone numbers",
                f"Scan {len(phone_entries)} phone numbers with Telegram?\n\n"
                "Telegram allows about one lookup every 3 seconds, so this may take "
                f"about {estimated_seconds} seconds.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        if not self.connect_client() or not self.authenticate_client():
            return

        self._set_busy(True)
        resolved = {}
        unresolved = []
        checked_count = 0
        try:
            for index, phone in enumerate(phone_entries, 1):
                checked_count += 1
                self.status_label.setText(
                    f"Scanning phone number {index} of {len(phone_entries)}..."
                )
                QApplication.processEvents()
                try:
                    user = self._resolve_member(phone)
                except FloodWaitError as exc:
                    unresolved.append(f"{phone}: Telegram flood wait ({exc.seconds}s)")
                    self._show_error(
                        "Telegram flood wait",
                        f"Scan stopped. Telegram asked you to wait {exc.seconds} seconds "
                        "before looking up more numbers.",
                    )
                    break
                except Exception as exc:
                    unresolved.append(f"{phone}: {exc}")
                    continue

                if user.username:
                    resolved[phone.strip().casefold()] = f"@{user.username}"
                else:
                    resolved[phone.strip().casefold()] = str(user.id)
        finally:
            self._set_busy(False)

        if resolved:
            updated_members = []
            seen = set()
            for candidate in candidates:
                replacement = resolved.get(candidate.strip().casefold(), candidate)
                key = replacement.lstrip("@").casefold()
                if key in seen:
                    continue
                seen.add(key)
                updated_members.append(replacement)
            self._set_member_list(updated_members)

        summary = (
            f"Phone numbers checked: {checked_count} of {len(phone_entries)}\n"
            f"Resolved: {len(resolved)}\n"
            f"Unresolved: {len(unresolved)}"
        )
        if unresolved:
            preview = "\n".join(unresolved[:10])
            if len(unresolved) > 10:
                preview += f"\n... and {len(unresolved) - 10} more"
            summary += (
                "\n\nUnresolved numbers are not registered Telegram accounts, or "
                "their privacy settings block phone lookup.\n\n" + preview
            )
            QMessageBox.warning(self, "Phone scan finished", summary)
        else:
            QMessageBox.information(self, "Phone scan finished", summary)
        self.status_label.setText(
            f"Scanned {checked_count} phone numbers; resolved {len(resolved)}"
        )

    @staticmethod
    def _generate_random_phone_number():
        return "+855" + "".join(random.choices(string.digits, k=8))

    def generate_random_members(self):
        count = self.random_entry.value()
        random_members = [
            self._generate_random_phone_number() for _ in range(count)
        ]
        self._set_member_list(random_members)
        self.status_label.setText(
            f"Generated {count} random phone-number placeholders - not real Telegram accounts."
        )
        QMessageBox.information(
            self,
            "Random test numbers",
            f"Generated {count} random +855 phone-number placeholders.\n\n"
            "These are not real Telegram accounts, so they normally cannot be added. "
            "Paste real phone numbers or usernames, then use Scan phones to check them "
            "against Telegram.",
        )

    def start_adding(self):
        if not self.permission_confirmation.isChecked():
            QMessageBox.warning(
                self,
                "Permission confirmation required",
                "Confirm that you have permission to invite the accounts in this list before continuing.",
            )
            return

        group_link = self.group_entry.text().strip()
        members = self._get_member_candidates()
        if not group_link or not members:
            QMessageBox.warning(
                self,
                "Input required",
                "Enter a target group and at least one username, phone number, or user ID.",
            )
            return

        self.progress_bar.setValue(0)
        self.status_label.setText("Checking Telegram login...")
        self._set_busy(True)
        try:
            self.add_members(group_link, members)
        finally:
            self._set_busy(False)

    def _member_list_edited(self):
        if not self._updating_member_list:
            self.permission_confirmation.setChecked(False)

    def _set_member_list(self, members):
        self._updating_member_list = True
        try:
            self.members_entry.setPlainText("\n".join(members))
        finally:
            self._updating_member_list = False
        self.permission_confirmation.setChecked(False)

    def _get_member_candidates(self):
        candidates = []
        seen = set()
        invite_link_pattern = re.compile(
            r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)",
            re.IGNORECASE,
        )
        for line in self.members_entry.toPlainText().splitlines():
            member = line.strip()
            if not member or invite_link_pattern.match(member):
                continue
            normalized = member.lstrip("@").casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(member)
        return candidates

    def select_random_members(self):
        candidates = self._get_member_candidates()
        count = self.random_entry.value()
        if not candidates:
            QMessageBox.warning(
                self,
                "No eligible users",
                "Enter usernames, phone numbers, or user IDs, one per line.",
            )
            return
        if count > len(candidates):
            QMessageBox.warning(
                self,
                "Not enough users",
                f"The list contains {len(candidates)} unique entries, but {count} were requested.",
            )
            return

        selected = random.sample(candidates, count)
        self._set_member_list(selected)
        self.status_label.setText(
            f"Selected {len(selected)} users. Review the list before adding."
        )

    def clear_entries(self):
        self.group_entry.clear()
        self.source_group_entry.clear()
        self.members_entry.clear()
        if hasattr(self, "upload_path_edit"):
            self.upload_path_edit.clear()
        self.permission_confirmation.setChecked(False)
        self._participant_cache.clear()
        self.random_entry.setValue(10)
        self.progress_bar.setValue(0)
        self.status_label.setText("Ready")

    def _update_storage_ui(self, info=None):
        if not hasattr(self, "storage_drive_label"):
            return
        if info is None:
            info = PCStorageManager.get_storage_info()
        self._current_storage_info = info

        drive = info.get("drive", "C:")
        free_gb = info.get("drive_free_gb", 0.0)
        total_gb = info.get("drive_total_gb", 0.0)
        free_pct = info.get("drive_free_pct", 0.0)
        used_pct = int(info.get("drive_used_pct", 0.0))

        self.storage_drive_label.setText(
            self.tr_text("storage_drive_status").format(
                drive=drive, free_gb=free_gb, total_gb=total_gb, free_pct=free_pct
            )
        )

        ram_free = info.get("ram_free_gb", 0.0)
        ram_total = info.get("ram_total_gb", 0.0)
        ram_used = info.get("ram_used_pct", 0.0)
        if ram_total > 0:
            self.storage_ram_label.setText(
                self.tr_text("storage_ram_status").format(
                    free_ram=ram_free, total_ram=ram_total, used_ram_pct=ram_used
                )
            )
            self.storage_ram_label.show()
        else:
            self.storage_ram_label.hide()

        self.storage_bar.setValue(used_pct)
        self.storage_bar.setFormat(f"Disk Used: {used_pct}% ({free_gb:.1f} GB Free)")

        if info.get("is_low_space", False):
            self.storage_bar.setStyleSheet("""
                QProgressBar {
                    background-color: #1e293b;
                    border: 1px solid #dc2626;
                    border-radius: 6px;
                    text-align: center;
                    color: #fecaca;
                    font-weight: 700;
                    font-size: 11px;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ef4444, stop:1 #f59e0b);
                    border-radius: 5px;
                }
            """)
            self.storage_info_label.setText(self.tr_text("storage_warning_low"))
            self.storage_info_label.setStyleSheet("color: #f87171; font-weight: 600; font-size: 12px;")
        else:
            self.storage_bar.setStyleSheet("""
                QProgressBar {
                    background-color: #1e293b;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    text-align: center;
                    color: #e2e8f0;
                    font-weight: 700;
                    font-size: 11px;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #10b981);
                    border-radius: 5px;
                }
            """)
            self.storage_info_label.setText(self.tr_text("storage_status_good"))
            self.storage_info_label.setStyleSheet("color: #34d399; font-weight: 500; font-size: 12px;")

        cache_mb = info.get("cleanable_mb", 0.0)
        app_mb = info.get("app_storage_mb", 0.0)
        self.storage_cache_label.setText(
            self.tr_text("storage_cache_status").format(
                cache_mb=cache_mb, app_mb=app_mb
            )
        )

    def _clean_pc_cache(self):
        self.btn_clean_cache.setEnabled(False)
        self.btn_clean_cache.setText("Cleaning...")
        QApplication.processEvents()

        freed_mb, count = PCStorageManager.clean_cache()
        info = PCStorageManager.get_storage_info()
        self._update_storage_ui(info)

        self.btn_clean_cache.setEnabled(True)
        self.btn_clean_cache.setText(self.tr_text("btn_clean_cache").replace("&", "&&"))

        if self.audio_manager:
            self.audio_manager.play_success()

        if freed_mb > 0.1 or count > 0:
            QMessageBox.information(
                self,
                self.tr_text("dialog_pc_space_title"),
                self.tr_text("msg_cleaned_success").format(freed_mb=freed_mb),
            )
        else:
            QMessageBox.information(
                self,
                self.tr_text("dialog_pc_space_title"),
                self.tr_text("msg_already_clean"),
            )

    def _calculate_pc_space(self):
        info = PCStorageManager.get_storage_info()
        self._update_storage_ui(info)
        if self.audio_manager:
            self.audio_manager.play_click()

    def _show_pc_storage_dialog(self):
        dlg = PCStorageDialog(self, PCStorageManager, self.tr_text)
        dlg.exec()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            is_min = self.isMinimized()
            if hasattr(self, "hero_logo") and self.hero_logo:
                self.hero_logo.set_active(not is_min)
            if hasattr(self, "header_card") and self.header_card:
                self.header_card.set_active(not is_min)
            if hasattr(self, "hero_badge") and self.hero_badge:
                self.hero_badge.set_active(not is_min)

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, "hero_logo") and self.hero_logo:
            self.hero_logo.set_active(False)
        if hasattr(self, "header_card") and self.header_card:
            self.header_card.set_active(False)
        if hasattr(self, "hero_badge") and self.hero_badge:
            self.hero_badge.set_active(False)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "hero_logo") and self.hero_logo:
            self.hero_logo.set_active(True)
        if hasattr(self, "header_card") and self.header_card:
            self.header_card.set_active(True)
        if hasattr(self, "hero_badge") and self.hero_badge:
            self.hero_badge.set_active(True)

    def closeEvent(self, event):
        self._disconnect_client()
        super().closeEvent(event)


if __name__ == "__main__":
    if os.name == "nt":
        try:
            import ctypes
            myappid = "telegram.member.manager.studio.v1"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("TelegramMemberManager")
    app_icon = TelegramMemberManager._create_app_icon()
    app.setWindowIcon(app_icon)
    window = TelegramMemberManager()
    window.setWindowIcon(app_icon)
    window.show()
    app.exec()
