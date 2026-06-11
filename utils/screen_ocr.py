"""
화면 OCR 분류기
  1. Windows 내장 OCR (winrt) — Tesseract 대체, 별도 바이너리 불필요
  2. Sentence-Transformers 의미 분류 — 키워드 리스트에 없는 단어도 포착
  3. 키워드 룰 — SBERT 미설치 시 최종 폴백

우선순위: SBERT 의미 분류 → 키워드 룰 → unknown
"""

import re
import asyncio
import cv2
from typing import Iterable, Optional

# ── Windows OCR ───────────────────────────────────────────────────────────
try:
    from winrt.windows.media.ocr import OcrEngine                       # type: ignore
    from winrt.windows.graphics.imaging import BitmapDecoder            # type: ignore
    from winrt.windows.storage.streams import (                         # type: ignore
        InMemoryRandomAccessStream, DataWriter,
    )
    _WINRT_OK = True
except ImportError:
    _WINRT_OK = False

# ── Sentence Transformers (lazy load) ─────────────────────────────────────
_sbert_model      = None
_sbert_study_vec  = None
_sbert_bad_vec    = None
_SBERT_LOADED     = False   # 로드 시도 여부 (실패해도 다시 시도 안 함)
_SBERT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# 의미 분류 기준 앵커 문장
_STUDY_ANCHOR    = (
    "수학 공부 강의 문제풀이 과제 교재 수업 학습 필기 증명 정리 해설 광합성 "
    "lecture study assignment pdf math physics chemistry biology"
)
_DISTRACT_ANCHOR = (
    "게임 유튜브 인스타그램 SNS 웹툰 주식 쇼핑 영화 드라마 마인크래프트 롤 배그 오버워치 "
    "game youtube instagram webtoon stock shopping entertainment minecraft league valorant "

)

# SBERT 판정 파라미터
_SIM_GAP_MIN        = 0.03   # 두 유사도 차이가 이 값 미만이면 ambiguous
_SIM_WIN_MIN        = 0.15   # 이긴 쪽 유사도가 이 값 미만이면 ambiguous
_SIM_DISTRACT_FORCE = 0.30   # 딴짓 유사도가 이 값 이상이면 공부가 이겨도 딴짓 판정
_TEXT_LEN_MIN       = 5      # 이 글자 수 미만 텍스트는 SBERT 생략


# ── 키워드 리스트 ─────────────────────────────────────────────────────────
DEFAULT_STUDY_WORDS = [
    "lecture", "study", "assignment", "pdf",
    "강의", "과제", "수업", "교재", "문제",
    "연속", "함수", "설명", "증명", "풀이", "해설",
    "vector", "행렬", "thm", "lemma", "검정교배",
]

DEFAULT_BAD_WORDS = [
    "game", "stock", "마인크래프트"
    "게임", "주식", "인스타", "웹툰", "리뷰",
]




def _load_sbert() -> bool:
    """sentence-transformers 모델을 한 번만 로드."""
    global _sbert_model, _sbert_study_vec, _sbert_bad_vec, _SBERT_LOADED
    if _SBERT_LOADED:
        return _sbert_model is not None
    _SBERT_LOADED = True
    try:
        from sentence_transformers import SentenceTransformer
        print("[OCR] sentence-transformers 모델 로딩 중…")
        _sbert_model      = SentenceTransformer(_SBERT_MODEL_NAME)
        _sbert_study_vec  = _sbert_model.encode(_STUDY_ANCHOR,   convert_to_tensor=True)
        _sbert_bad_vec    = _sbert_model.encode(_DISTRACT_ANCHOR, convert_to_tensor=True)
        print("[OCR] sentence-transformers 로드 완료")
        return True
    except Exception as exc:
        print(f"[OCR] sentence-transformers 없음 → 키워드 모드: {exc}")
        return False


def _run_async(coro):
    """스레드에서 asyncio 코루틴을 동기적으로 실행."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _windows_ocr_async(frame_bgr) -> str:
    """Windows 내장 OCR로 텍스트 추출."""
    # BGR → PNG 인메모리 인코딩
    _, png_buf = cv2.imencode(".png", frame_bgr)
    png_bytes  = bytearray(png_buf)

    # InMemoryRandomAccessStream 에 PNG 데이터 쓰기
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png_bytes)
    await writer.store_async()
    stream.seek(0)

    # BitmapDecoder → SoftwareBitmap
    decoder = await BitmapDecoder.create_async(stream)
    bitmap  = await decoder.get_software_bitmap_async()

    # OCR 실행 (사용자 프로필 언어 자동 선택)
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return ""
    result = await engine.recognize_async(bitmap)
    return result.text if result else ""


# ── 공개 클래스 ───────────────────────────────────────────────────────────

class OCRKeywordClassifier:
    def __init__(
        self,
        study_words: Optional[Iterable[str]] = None,
        bad_words:   Optional[Iterable[str]] = None,
    ):
        self.study_words = [w.lower() for w in (study_words or DEFAULT_STUDY_WORDS) if w]
        self.bad_words   = [w.lower() for w in (bad_words   or DEFAULT_BAD_WORDS)   if w]

    @property
    def available(self) -> bool:
        return _WINRT_OK

    # ── 텍스트 추출 ──────────────────────────────────────────────────────

    def extract_text(self, frame_bgr) -> tuple[str, str]:
        if not _WINRT_OK:
            return "", (
                "Windows OCR 미설치 — "
                "pip install winrt-Windows.Media.Ocr "
                "winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams"
            )
        try:
            text = _run_async(_windows_ocr_async(frame_bgr))
            return text, "ocr complete"
        except Exception as exc:
            return "", f"ocr error: {exc}"

    # ── SBERT 의미 분류 ──────────────────────────────────────────────────

    def semantic_classify(self, text: str) -> tuple[Optional[str], str]:
        """
        sentence-transformers 코사인 유사도로 study / distracted / unknown 반환.
        SBERT 미설치 또는 텍스트가 짧으면 None 반환 → 키워드 폴백.
        """
        if not _load_sbert() or _sbert_model is None:
            return None, "sbert unavailable"

        stripped = text.strip()
        if len(stripped) < _TEXT_LEN_MIN:
            return None, "text too short for semantic"

        try:
            from sentence_transformers import util as st_util
            text_vec   = _sbert_model.encode(stripped[:512], convert_to_tensor=True)
            sim_study  = float(st_util.cos_sim(text_vec, _sbert_study_vec))
            sim_bad    = float(st_util.cos_sim(text_vec, _sbert_bad_vec))

            gap       = abs(sim_study - sim_bad)
            win_score = max(sim_study, sim_bad)

            # 딴짓 유사도가 강제 임계값 이상이면 공부가 이겨도 딴짓으로 판정
            # (공부 앱 위에 딴짓 앱이 겹쳐 있는 경우 포착)
            if sim_bad >= _SIM_DISTRACT_FORCE:
                return "distracted", (
                    f"sbert 딴짓 강제 (딴짓={sim_bad:.2f}≥{_SIM_DISTRACT_FORCE}, 공부={sim_study:.2f})"
                )

            winner = "study" if sim_study >= sim_bad else "distracted"

            if gap < _SIM_GAP_MIN or win_score < _SIM_WIN_MIN:
                return "unknown", (
                    f"sbert 판정 불명확 "
                    f"(공부={sim_study:.2f}, 딴짓={sim_bad:.2f})"
                )

            reason = (
                f"sbert 공부 유사도={sim_study:.2f} > 딴짓={sim_bad:.2f}"
                if winner == "study" else
                f"sbert 딴짓 유사도={sim_bad:.2f} > 공부={sim_study:.2f}"
            )
            return winner, reason

        except Exception as exc:
            return None, f"sbert error: {exc}"

    # ── 키워드 룰 (폴백) ─────────────────────────────────────────────────

    def rule_classify(self, text: str) -> tuple[str, str]:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not normalized:
            return "unknown", "ocr 텍스트 없음"

        bad_hits   = [w for w in self.bad_words   if w in normalized]
        study_hits = [w for w in self.study_words if w in normalized]

        if bad_hits:
            return "distracted", f"키워드 매칭: {', '.join(bad_hits[:3])}"
        if study_hits:
            return "study",      f"키워드 매칭: {', '.join(study_hits[:3])}"
        return "unknown", "매칭 키워드 없음"

    # ── 메인 진입점 ──────────────────────────────────────────────────────

    def classify(self, frame_bgr) -> tuple[str, str, str]:
        """
        Returns (label, reason, text_preview).
        label: "study" | "distracted" | "unknown"
        """
        text, extract_reason = self.extract_text(frame_bgr)
        preview = re.sub(r"\s+", " ", text).strip()[:120] or extract_reason

        # 1순위: SBERT 의미 분류
        label, reason = self.semantic_classify(text)
        if label in {"study", "distracted"}:
            return label, reason, preview

        # 2순위: 키워드 룰
        label, reason = self.rule_classify(text)
        return label, reason, preview
