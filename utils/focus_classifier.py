from collections import deque
from dataclasses import dataclass, field
from typing import Deque

@dataclass
class FocusClassifier:
    ear_threshold: float = 0.21
    pitch_down_max: float = 25.0
    pitch_up_max: float = 20.0
    yaw_max: float = 30.0
    smooth_window: int = 15

    _history: Deque[bool] = field(default_factory=lambda: deque(maxlen=15))

    def __post_init__(self):
        self._history = deque(maxlen=self.smooth_window)

    def update_params(self, ear_threshold, pitch_down_max, pitch_up_max, yaw_max, smooth_window):
        self.ear_threshold = ear_threshold
        self.pitch_down_max = pitch_down_max
        self.pitch_up_max = pitch_up_max
        self.yaw_max = yaw_max
        if smooth_window != self.smooth_window:
            self.smooth_window = smooth_window
            old = list(self._history)
            self._history = deque(old, maxlen=smooth_window)

    def classify(self, ear: float, pitch: float, yaw: float) -> tuple[bool, str]:
        """Returns (is_focused, reason_text)"""
        if ear < self.ear_threshold:
            reason = f"눈 감음 EAR {ear:.2f}"
            self._history.append(False)
            return self._smooth(), reason

        if pitch > self.pitch_down_max:
            reason = f"고개 숙임 {pitch:.1f}°"
            self._history.append(False)
            return self._smooth(), reason

        if pitch < -self.pitch_up_max:
            reason = f"고개 젖힘 {pitch:.1f}°"
            self._history.append(False)
            return self._smooth(), reason

        if abs(yaw) > self.yaw_max:
            direction = "왼쪽" if yaw > 0 else "오른쪽"
            reason = f"고개 {direction} {abs(yaw):.1f}°"
            self._history.append(False)
            return self._smooth(), reason

        self._history.append(True)
        return self._smooth(), "집중 중"

    def _smooth(self) -> bool:
        if not self._history:
            return True
        focused_count = sum(1 for v in self._history if v)
        return focused_count > len(self._history) / 2

SENSITIVITY_PRESETS = {
    "낮음": {
        "ear_threshold": 0.18,
        "pitch_down_max": 30.0,
        "pitch_up_max": 25.0,
        "yaw_max": 40.0,
    },
    "보통": {
        "ear_threshold": 0.21,
        "pitch_down_max": 25.0,
        "pitch_up_max": 20.0,
        "yaw_max": 30.0,
    },
    "높음": {
        "ear_threshold": 0.24,
        "pitch_down_max": 18.0,
        "pitch_up_max": 15.0,
        "yaw_max": 22.0,
    },
}
