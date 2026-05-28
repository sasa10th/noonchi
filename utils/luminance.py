import numpy as np
from collections import deque

class LuminanceDetector:
    def __init__(self, check_interval=30, delta_threshold=40, hold_frames=30):
        self.check_interval = check_interval
        self.delta_threshold = delta_threshold
        self.hold_frames = hold_frames

        self._frame_count = 0
        self._prev_lum = None
        self._hold_remaining = 0

    def process(self, frame_gray: np.ndarray) -> tuple[bool, bool]:
        """
        Returns (lighting_changed, should_hold).
        lighting_changed: True on the frame the change was detected.
        should_hold: True while holding (skip focus judgment).
        """
        self._frame_count += 1
        lighting_changed = False

        if self._frame_count % self.check_interval == 0:
            lum = float(frame_gray.mean())
            if self._prev_lum is not None:
                delta = abs(lum - self._prev_lum)
                if delta > self.delta_threshold:
                    lighting_changed = True
                    self._hold_remaining = self.hold_frames
            self._prev_lum = lum

        if self._hold_remaining > 0:
            self._hold_remaining -= 1
            return lighting_changed, True

        return lighting_changed, False
