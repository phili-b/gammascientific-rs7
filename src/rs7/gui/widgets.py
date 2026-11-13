"""Spectrum plot and CIE 1931 chart, drawn with QPainter (no plotting library needed)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..spectrum import SPECTRAL_LOCUS, cct_to_xy, wavelength_to_rgb

Series = list[tuple[float, float]]


def wavelength_color(nm: float) -> QColor:
    return QColor(*wavelength_to_rgb(nm))


class SpectrumPlot(QWidget):
    """Output spectrum (white), optional per-channel spectra (their color) and target (blue)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(400, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.start, self.end = 380, 780
        self.output: Series = []
        self.channels: list[tuple[Series, QColor]] = []
        self.target: Series = []

    def set_data(self, start: int, end: int, output: Series, channels: list[tuple[Series, QColor]], target: Series):
        self.start, self.end = start, end
        self.output, self.channels, self.target = output, channels, target
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#101010"))
        left, bottom, top, right = 55, 24, 10, 10
        w, h = self.width(), self.height()
        series = [(self.output, QColor("white")), *self.channels, (self.target, QColor("#4080ff"))]
        ymax = max((v for s, _ in series for _, v in s), default=0) or 1.0
        span = max(self.end - self.start, 1)

        def pt(nm: float, v: float) -> QPointF:
            return QPointF(
                left + (nm - self.start) / span * (w - left - right), h - bottom - v / ymax * (h - bottom - top)
            )

        grey = QColor("#808080")
        p.setPen(QPen(grey))
        p.drawLine(left, top, left, h - bottom)
        p.drawLine(left, h - bottom, w - right, h - bottom)
        font = p.font()
        font.setPointSizeF(7.5)
        p.setFont(font)
        p.setPen(QColor("#c0c0c0"))
        for nm in range(self.start - self.start % 50 + 50, self.end, 50):
            x = pt(nm, 0).x()
            p.drawLine(QPointF(x, h - bottom), QPointF(x, h - bottom + 4))
            p.drawText(QRectF(x - 20, h - bottom + 5, 40, 16), Qt.AlignmentFlag.AlignCenter, str(nm))
        for i in range(5):
            y = pt(0, ymax * i / 4).y()
            p.drawText(
                QRectF(0, y - 8, left - 5, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{ymax * i / 4:.3g}",
            )
        for s, color in series:
            if len(s) > 1:
                path = QPainterPath(pt(*s[0]))
                for nm, v in s[1:]:
                    path.lineTo(pt(nm, v))
                p.setPen(QPen(color, 1.5))
                p.drawPath(path)


class CieChart(QWidget):
    """CIE 1931 x,y chart with the present chromaticity; clicking emits the x,y clicked."""

    clicked = Signal(float, float)
    X_MAX, Y_MAX = 0.8, 0.9

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(290, 320)
        self.xy: tuple[float, float] | None = None
        self.target: tuple[float, float] | None = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("Click to change the color of the output")

    def set_xy(self, xy: tuple[float, float] | None):
        self.xy = xy
        self.update()

    def set_target(self, xy: tuple[float, float] | None):
        """Mark the target's chromaticity (blue cross); ``None`` hides it."""
        self.target = xy
        self.update()

    def _to_px(self, x: float, y: float) -> QPointF:
        return QPointF(
            10 + x / self.X_MAX * (self.width() - 20), self.height() - 10 - y / self.Y_MAX * (self.height() - 20)
        )

    def _to_xy(self, px: QPointF) -> tuple[float, float]:
        x = (px.x() - 10) / (self.width() - 20) * self.X_MAX
        y = (self.height() - 10 - px.y()) / (self.height() - 20) * self.Y_MAX
        return round(x, 4), round(y, 4)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor("black"), 1))
        p.setBrush(QColor("#e8e8e8"))
        p.drawPolygon(QPolygonF([self._to_px(x, y) for _, x, y in SPECTRAL_LOCUS]))
        font = p.font()
        font.setPointSizeF(7)
        p.setFont(font)
        for nm, x, y in SPECTRAL_LOCUS:
            if 460 <= nm <= 620 and nm % 20 == 0:
                pos = self._to_px(x, y)
                dx = -26 if x < 0.3 and pos.x() > 34 else 6
                p.setPen(wavelength_color(nm).darker(130))
                p.drawText(QRectF(pos.x() + dx, pos.y() - 7, 22, 14), Qt.AlignmentFlag.AlignCenter, str(nm))
        # Planckian (black-body) locus with a few temperatures
        temps = [1667 * (25000 / 1667) ** (i / 60) for i in range(61)]
        p.setPen(QPen(QColor("#555555"), 1))
        p.drawPolyline(QPolygonF([self._to_px(*cct_to_xy(t)) for t in temps]))
        p.setPen(QColor("#333333"))
        for t, label in ((2000, "2000K"), (3000, "3000"), (4000, "4000"), (6500, "6500"), (10000, "10k")):
            pos = self._to_px(*cct_to_xy(t))
            p.drawLine(pos + QPointF(0, -3), pos + QPointF(0, 3))
            p.drawText(QRectF(pos.x() - 18, pos.y() + 3, 36, 12), Qt.AlignmentFlag.AlignCenter, label)
        if self.target:
            t = self._to_px(*self.target)
            p.setPen(QPen(QColor("#2060ff"), 2))
            p.drawLine(t + QPointF(-6, -6), t + QPointF(6, 6))
            p.drawLine(t + QPointF(-6, 6), t + QPointF(6, -6))
        if self.xy:
            p.setPen(QPen(QColor("black"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(self._to_px(*self.xy), 5, 5)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(*self._to_xy(event.position()))
