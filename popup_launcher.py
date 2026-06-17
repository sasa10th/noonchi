import sys
import webview

_window = None


class PopupAPI:
    def close_popup(self):
        if _window:
            _window.destroy()

    def move_window(self, dx, dy):
        if _window:
            try:
                _window.move(_window.x + int(dx), _window.y + int(dy))
            except Exception:
                pass

    def resize_window(self, height):
        if _window:
            try:
                _window.resize(180, int(height))
            except Exception:
                pass


def main():
    global _window
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    api = PopupAPI()
    _window = webview.create_window(
        '눈치',
        url=f'http://localhost:{port}/popup',
        width=180,
        height=212,
        frameless=True,
        on_top=True,
        transparent=True,
        min_size=(100, 100),
        js_api=api,
    )
    webview.start()


if __name__ == '__main__':
    main()
