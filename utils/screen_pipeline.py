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
    # 연속 캡처 실패가 이 횟수 이상일 때만 "미연결"로 표시
    DISCONNECT_THRESHOLD = 3

    def __init__(self, window_keyword: str = None, check_interval: float = 1.5):
        self.window_keyword = window_keyword  # None이면 DEFAULT_KEYWORDS 전체 사용
        self.check_interval = check_interval
        self.capturer = WindowScreenCapturer(window_keyword=window_keyword)
        self.classifier = ScreenClassifier()
        self.ocr = OCRKeywordClassifier()
        self._last_result = ScreenAnalysisResult(
            state="unknown",
            reason="",
            source="init",
        )
        self._consecutive_failures = 0  # 연속 캡처 실패 횟수

    def maybe_analyze(self, now: Optional[float] = None):
        now = now or time.time()
        if self._last_result.checked_at and now - self._last_result.checked_at < self.check_interval:
            return self._last_result
        self._last_result = self.analyze(now=now)
        return self._last_result

    def analyze(self, now: Optional[float] = None):
        now = now or time.time()
        try:
            result = self._analyze_inner(now)
            return result
        except Exception as exc:
            print(f"[Screen] analyze 예외 (무시됨): {exc}")
            self._consecutive_failures += 1
            return self._unknown_result(f"analyze error: {exc}", now)

    def _unknown_result(self, reason: str, now: float) -> ScreenAnalysisResult:
        """실패 횟수가 임계값 미만이면 이전 결과를 유지하고, 초과하면 unknown 반환."""
        if self._consecutive_failures < self.DISCONNECT_THRESHOLD:
            # 화면 전환 등 일시적 실패 — 마지막 정상 결과를 유지
            prev = self._last_result
            return ScreenAnalysisResult(
                state=prev.state,
                reason=prev.reason,
                confidence=prev.confidence,
                source=prev.source,
                checked_at=now,
            )
        # 3회 이상 연속 실패 → 진짜 연결 끊김으로 판단
        return ScreenAnalysisResult(
            state="unknown",
            reason="iPad 창 없음",
            source="capture",
            checked_at=now,
        )

    def _analyze_inner(self, now: float):
        if not self.capturer.available:
            self._consecutive_failures += 1
            return self._unknown_result("screen capture dependencies unavailable", now)

        frame, capture_reason = self.capturer.capture()
        if frame is None:
            self._consecutive_failures += 1
            return self._unknown_result(capture_reason, now)

        # 캡처 성공 → 실패 카운터 초기화
        self._consecutive_failures = 0

        # 매칭된 기기명을 reason 앞에 붙여 UI에서 표시
        device_tag = f"[{self.capturer._matched_keyword}] " if self.capturer._matched_keyword else ""

        label, confidence, classify_reason = self.classifier.classify(frame)
        if label == "study":
            return ScreenAnalysisResult(
                state="study",
                reason=f"{device_tag}{classify_reason}",
                confidence=confidence,
                source="classifier",
                checked_at=now,
            )
        if label == "distracted":
            return ScreenAnalysisResult(
                state="distracted",
                reason=f"{device_tag}{classify_reason}",
                confidence=confidence,
                source="classifier",
                checked_at=now,
            )

        ocr_label, ocr_reason, preview = self.ocr.classify(frame)
        if ocr_label in {"study", "distracted"}:
            return ScreenAnalysisResult(
                state=ocr_label,
                reason=f"{device_tag}{ocr_reason}",
                confidence=confidence,
                text_preview=preview,
                source="ocr",
                checked_at=now,
            )

        return ScreenAnalysisResult(
            state="unknown",
            reason=f"{device_tag}{classify_reason}; {ocr_reason}",
            confidence=confidence,
            text_preview=preview,
            source="ocr",
            checked_at=now,
        )
