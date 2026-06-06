import re
from typing import Iterable, Optional

import cv2

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None


DEFAULT_STUDY_WORDS = [
    "lecture",
    "study",
    "assignment",
    "pdf",
    "강의",
    "과제",
    "수업",
    "교재",
    "문제",
]

DEFAULT_BAD_WORDS = [
    "game",
    "stock",
    "youtube",
    "게임",
    "주식",
    "유튜브",
    "인스타",
    "틱톡",
]


class OCRKeywordClassifier:
    def __init__(
        self,
        study_words: Optional[Iterable[str]] = None,
        bad_words: Optional[Iterable[str]] = None,
    ):
        self.study_words = [word.lower() for word in (study_words or DEFAULT_STUDY_WORDS)]
        self.bad_words = [word.lower() for word in (bad_words or DEFAULT_BAD_WORDS)]

    @property
    def available(self) -> bool:
        return pytesseract is not None

    def extract_text(self, frame_bgr):
        if not self.available:
            return "", "pytesseract unavailable"

        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            text = pytesseract.image_to_string(thresh, lang="kor+eng")
            return text, "ocr complete"
        except Exception as exc:
            return "", f"ocr error: {exc}"

    def rule_classify(self, text: str):
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not normalized:
            return "unknown", "ocr empty"

        bad_hits = [word for word in self.bad_words if word in normalized]
        study_hits = [word for word in self.study_words if word in normalized]

        if bad_hits:
            return "distracted", f"ocr matched distract words: {', '.join(bad_hits[:3])}"
        if study_hits:
            return "study", f"ocr matched study words: {', '.join(study_hits[:3])}"
        return "unknown", "ocr found no matching keywords"

    def classify(self, frame_bgr):
        text, extract_reason = self.extract_text(frame_bgr)
        label, reason = self.rule_classify(text)
        preview = re.sub(r"\s+", " ", text).strip()[:120]
        if not preview:
            preview = extract_reason
        return label, reason, preview
