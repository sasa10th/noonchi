import time
from dataclasses import dataclass
from typing import Optional

from utils.screen_capture import WindowScreenCapturer
from utils.screen_classifier import ScreenClassifier
from utils.screen_ocr import OCRKeywordClassifier


@dataclass
class ScreenAnalysisResult:
    state: str
    reason: str
    confidence: float = 0.0
    text_preview: str = ""
    source: str = ""
    checked_at: float = 0.0


class ScreenAnalysisPipeline:
    def __init__(self, window_keyword: str = "iPad", check_interval: float = 1.5):
        self.window_keyword = window_keyword
        self.check_interval = check_interval
        self.capturer = WindowScreenCapturer(window_keyword=window_keyword)
        self.classifier = ScreenClassifier()
        self.ocr = OCRKeywordClassifier()
        self._last_result = ScreenAnalysisResult(
            state="unknown",
            reason="screen pipeline not checked yet",
            source="init",
        )

    def maybe_analyze(self, now: Optional[float] = None):
        now = now or time.time()
        if self._last_result.checked_at and now - self._last_result.checked_at < self.check_interval:
            return self._last_result
        self._last_result = self.analyze(now=now)
        return self._last_result

    def analyze(self, now: Optional[float] = None):
        now = now or time.time()

        if not self.capturer.available:
            return ScreenAnalysisResult(
                state="unknown",
                reason="screen capture dependencies unavailable",
                source="capture",
                checked_at=now,
            )

        frame, capture_reason = self.capturer.capture()
        if frame is None:
            return ScreenAnalysisResult(
                state="unknown",
                reason=capture_reason,
                source="capture",
                checked_at=now,
            )

        label, confidence, classify_reason = self.classifier.classify(frame)
        if label == "study":
            return ScreenAnalysisResult(
                state="study",
                reason=classify_reason,
                confidence=confidence,
                source="classifier",
                checked_at=now,
            )
        if label == "distracted":
            return ScreenAnalysisResult(
                state="distracted",
                reason=classify_reason,
                confidence=confidence,
                source="classifier",
                checked_at=now,
            )

        ocr_label, ocr_reason, preview = self.ocr.classify(frame)
        if ocr_label in {"study", "distracted"}:
            return ScreenAnalysisResult(
                state=ocr_label,
                reason=ocr_reason,
                confidence=confidence,
                text_preview=preview,
                source="ocr",
                checked_at=now,
            )

        return ScreenAnalysisResult(
            state="unknown",
            reason=f"{classify_reason}; {ocr_reason}",
            confidence=confidence,
            text_preview=preview,
            source="ocr",
            checked_at=now,
        )
