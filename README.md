# NoonChi

세종과학예술영재학교 2026학년도 1학기 인공지능프로젝트

---

## 설치 및 실행

```bash
pip install -r requirements.txt
python app.py
```

브라우저에서 `http://localhost:5000` 접속

---

## 기술 스택

| 구성 | 기술 |
|------|------|
| 백엔드 | Flask + Flask-SocketIO |
| 영상 스트리밍 | MJPEG (multipart/x-mixed-replace) |
| 실시간 통신 | WebSocket (Socket.IO) |
| 얼굴 분석 | MediaPipe FaceMesh 0.10.13 |
| 영상 처리 | OpenCV |
| 프론트엔드 | HTML + CSS + Vanilla JS |
| 차트 | Chart.js |

---

## 파일 구조

```
focuslock/
├── app.py                    # Flask 서버 + 카메라 루프 + AI 분석
├── requirements.txt
├── templates/
│   └── index.html            # 4개 뷰 (setup/focus/completed/report)
├── static/
│   ├── css/style.css         # 다크 테마 스타일
│   └── js/main.js            # SocketIO + UI 로직
└── utils/
    ├── __init__.py
    ├── ear_calculator.py     # EAR 계산
    ├── focus_classifier.py   # 집중 판정 + 스무딩
    └── luminance.py          # 조도 변화 감지
```

---

## 주의사항

- 웹캠이 연결되어 있어야 합니다.
- mediapipe는 **반드시 0.10.13** 버전을 사용하세요.
- 실행 후 브라우저에서 `http://localhost:5000` 으로 접속하세요.
