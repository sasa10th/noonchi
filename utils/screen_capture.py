import ctypes
from typing import Optional

import cv2
import numpy as np
from PIL import Image

try:
    import win32gui
    import win32ui
except ImportError:  # pragma: no cover
    win32gui = None
    win32ui = None


class WindowScreenCapturer:
    # 지원할 태블릿/미러링 창 키워드 (우선순위 순)
    DEFAULT_KEYWORDS = [
        "iPad",           # Apple iPad 미러링
        "Samsung DeX",    # 갤럭시탭 DeX 무선/유선
        "Samsung Flow",   # Samsung Flow 앱
        "scrcpy",         # scrcpy 오픈소스 미러링
        "Phone Link",     # Windows Link to Windows
        "SM-",            # 갤럭시 기기명 접두어 (SM-X710 등)
        "Galaxy Tab",     # 일부 앱이 기기명 그대로 표시
        "Tab",
        "무선 디스플레이",
    ]

    def __init__(self, window_keyword: str = None, window_keywords: list = None):
        # 단일 키워드(하위 호환) 또는 리스트 모두 지원
        if window_keywords:
            self.window_keywords = window_keywords
        elif window_keyword:
            self.window_keywords = [window_keyword]
        else:
            self.window_keywords = self.DEFAULT_KEYWORDS

        self._hwnd = None
        self._matched_keyword = None  # 실제 매칭된 키워드 (UI 표시용)
        ctypes.windll.user32.SetProcessDPIAware()

    @property
    def available(self) -> bool:
        return win32gui is not None and win32ui is not None

    def _find_window(self) -> Optional[int]:
        """키워드 우선순위대로 창을 탐색, 첫 번째 매칭 HWND 반환."""
        if not self.available:
            return None

        # 모든 가시 창 수집
        visible = {}
        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    visible[hwnd] = title.lower()
        win32gui.EnumWindows(callback, None)

        # 키워드 우선순위대로 탐색
        for kw in self.window_keywords:
            kw_lower = kw.lower()
            for hwnd, title in visible.items():
                if kw_lower in title:
                    self._matched_keyword = kw
                    return hwnd

        self._matched_keyword = None
        return None

    def capture(self):
        hwnd = self._hwnd if self._hwnd and win32gui and win32gui.IsWindow(self._hwnd) else None
        if hwnd is None:
            hwnd = self._find_window()
            self._hwnd = hwnd
        if hwnd is None:
            return None, f"window not found: {self.window_keyword}"

        # 화면 전환 중 HWND가 무효화되면 GetWindowRect 포함 이후 모든 Win32 호출이
        # 예외를 던질 수 있으므로 전체를 감싼다. 실패 시 캐시도 초기화.
        hwnd_dc = None
        mfc_dc = None
        save_dc = None
        bitmap = None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                return None, "invalid window size"

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
            if result != 1:
                return None, f"PrintWindow failed: {result}"

            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)
            img = Image.frombuffer(
                "RGB",
                (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                bmpstr,
                "raw",
                "BGRX",
                0,
                1,
            )
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            return frame, "captured"

        except Exception as exc:
            # 화면 전환 등으로 캡처 실패 → 캐시 초기화 후 다음 틱에서 재탐색
            self._hwnd = None
            return None, f"capture error (screen transition?): {exc}"

        finally:
            try:
                if bitmap is not None:
                    win32gui.DeleteObject(bitmap.GetHandle())
                if save_dc is not None:
                    save_dc.DeleteDC()
                if mfc_dc is not None:
                    mfc_dc.DeleteDC()
                if hwnd_dc is not None:
                    win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass  # 정리 실패는 무시
