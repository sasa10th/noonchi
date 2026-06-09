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
    def __init__(self, window_keyword: str = "iPad"):
        self.window_keyword = window_keyword
        self._hwnd = None
        ctypes.windll.user32.SetProcessDPIAware()

    @property
    def available(self) -> bool:
        return win32gui is not None and win32ui is not None

    def _find_window(self) -> Optional[int]:
        if not self.available:
            return None

        matches = []

        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if self.window_keyword.lower() in title.lower():
                matches.append(hwnd)

        win32gui.EnumWindows(callback, None)
        return matches[0] if matches else None

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
