import cv2
import numpy as np
import mediapipe as mp
import time
import math
import threading
import base64
import json
from collections import deque
from flask import Flask, render_template, Response, jsonify, request
from flask_socketio import SocketIO, emit

# utils
from utils.ear_calculator import compute_ear
from utils.focus_classifier import FocusClassifier
from utils.luminance import LuminanceDetector

app = Flask(__name__)
app.config["SECRET_KEY"] = "noonchi-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# 전역 상태
state = {
    "phase": "setup",  # setup | running | paused | completed
    "goal_seconds": 1800,
    "focused_time": 0.0,
    "session_time": 0.0,
    "session_start": None,
    "last_tick": None,
    "focus_state": "no_face",  # focused | distracted | no_face | hold
    "focus_reason": "",
    "ear": 0.0,
    "pitch": 0.0,
    "yaw": 0.0,
    "distract_start": None,
    "grace_period": 2.0,
    "lum_toast_until": 0.0,
    "sessions": [],
}
state_lock = threading.Lock()

classifier = FocusClassifier()
lum_detector = LuminanceDetector()

# MediaPipe FaceMesh
mp_fm = mp.solutions.face_mesh
face_mesh = mp_fm.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

# MJPEG 프레임 버퍼
frame_lock = threading.Lock()
current_frame = None
camera_thread = None
camera_running = False
_emit_counter = 0  # 브로드캐스트 속도 제한용 (~15fps)

# 얼굴 랜드마크 오버레이
FACE_OVAL_IDX = [
    10,
    338,
    297,
    332,
    284,
    251,
    389,
    356,
    454,
    323,
    361,
    288,
    397,
    365,
    379,
    378,
    400,
    377,
    152,
    148,
    176,
    149,
    150,
    136,
    172,
    58,
    132,
    93,
    234,
    127,
    162,
    21,
    54,
    103,
    67,
    109,
]


def draw_overlay(frame, landmarks, is_focused, h, w):
    # Frame is RGB — use RGB tuples directly (matches frontend --green/#30d158 and --red/#ff453a)
    green = (48, 209, 88)
    red = (255, 69, 58)
    color = green if is_focused else red
    bgr = color

    # 랜드마크 점들 (더 작고 섬세하게)
    for lm in landmarks:
        cx, cy = int(lm.x * w), int(lm.y * h)
        cv2.circle(frame, (cx, cy), 1, bgr, -1)

    # 얼굴 윤곽선
    for i in range(len(FACE_OVAL_IDX)):
        p1i = FACE_OVAL_IDX[i]
        p2i = FACE_OVAL_IDX[(i + 1) % len(FACE_OVAL_IDX)]
        p1 = (int(landmarks[p1i].x * w), int(landmarks[p1i].y * h))
        p2 = (int(landmarks[p2i].x * w), int(landmarks[p2i].y * h))
        cv2.line(frame, p1, p2, bgr, 1)

    # 개선된 테두리: 둥근 모서리 효과 포함
    margin = 12
    radius = 20
    thickness = 3
    
    # 상단 왼쪽 모서리
    cv2.line(frame, (margin + radius, margin), (w - margin - radius, margin), bgr, thickness)
    cv2.ellipse(frame, (margin + radius, margin + radius), (radius, radius), 180, 0, 90, bgr, thickness)
    
    # 상단 오른쪽 모서리
    cv2.ellipse(frame, (w - margin - radius, margin + radius), (radius, radius), 270, 0, 90, bgr, thickness)
    
    # 하단 오른쪽 모서리
    cv2.line(frame, (w - margin, margin + radius), (w - margin, h - margin - radius), bgr, thickness)
    cv2.ellipse(frame, (w - margin - radius, h - margin - radius), (radius, radius), 0, 0, 90, bgr, thickness)
    
    # 하단 왼쪽 모서리
    cv2.line(frame, (w - margin - radius, h - margin), (margin + radius, h - margin), bgr, thickness)
    cv2.ellipse(frame, (margin + radius, h - margin - radius), (radius, radius), 90, 0, 90, bgr, thickness)
    
    # 왼쪽과 오른쪽 수직선
    cv2.line(frame, (margin, margin + radius), (margin, h - margin - radius), bgr, thickness)
    cv2.line(frame, (w - margin, margin + radius), (w - margin, h - margin - radius), bgr, thickness)
    
    return frame


# 헤드 포즈 (랜드마크 기반)
def extract_head_pose(lm, w, h):
    def pt(i):
        return np.array([lm[i].x * w, lm[i].y * h])

    nose = pt(1)
    forehead = pt(10)
    chin = pt(152)
    l_eye = pt(263)
    r_eye = pt(33)

    eye_center = (l_eye + r_eye) / 2
    eye_width = np.linalg.norm(l_eye - r_eye)
    face_height = np.linalg.norm(forehead - chin)

    yaw = float(np.clip((nose[0] - eye_center[0]) / (eye_width + 1e-6) * 55, -90, 90))
    pitch = float(
        np.clip((nose[1] - eye_center[1]) / (face_height + 1e-6) * 75, -60, 60)
    )
    return pitch, yaw


# 타이머 틱
def timer_tick(is_focused, has_face, hold):
    now = time.time()
    with state_lock:
        if state["last_tick"] is None:
            state["last_tick"] = now
            return
        dt = now - state["last_tick"]
        state["last_tick"] = now
        state["session_time"] += dt

        if not has_face or hold:
            state["distract_start"] = None
            return

        if is_focused:
            state["focused_time"] += dt
            state["distract_start"] = None
        else:
            if state["distract_start"] is None:
                state["distract_start"] = now
            if now - state["distract_start"] <= state["grace_period"]:
                state["focused_time"] += dt


# 카메라 + AI 분석 스레드
def camera_loop():
    global current_frame, camera_running, _emit_counter
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    while camera_running:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        with state_lock:
            phase = state["phase"]

        if phase == "running":
            # 조도 체크
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            lum_changed, hold = lum_detector.process(gray)
            if lum_changed:
                with state_lock:
                    state["lum_toast_until"] = time.time() + 3.0

            # MediaPipe
            result = face_mesh.process(rgb)
            has_face = False
            is_focused = False

            if result.multi_face_landmarks:
                has_face = True
                lm = result.multi_face_landmarks[0].landmark
                ear_val = compute_ear(lm)
                pitch_val, yaw_val = extract_head_pose(lm, w, h)

                with state_lock:
                    state["ear"] = round(ear_val, 3)
                    state["pitch"] = round(pitch_val, 1)
                    state["yaw"] = round(yaw_val, 1)

                if not hold:
                    # 모델 예측 (sleepy/distracted/normal)
                    focus_state, reason, confidence = classifier.classify(
                        pitch_val, yaw_val, 0.0, lm
                    )
                    # 상태 변환: model output → UI state
                    state_mapping = {
                        "sleepy": "distracted",      # 졸음 → 산만함으로 표시
                        "distracted": "distracted",
                        "normal": "focused",
                    }
                    ui_state = state_mapping.get(focus_state, "distracted")
                    is_focused = (ui_state == "focused")
                    
                    with state_lock:
                        state["focus_reason"] = reason
                        state["focus_state"] = ui_state
                else:
                    is_focused = True
                    with state_lock:
                        state["focus_state"] = "hold"

                frame_rgb = draw_overlay(rgb.copy(), lm, is_focused, h, w)
            else:
                with state_lock:
                    state["focus_state"] = "no_face"
                    state["focus_reason"] = "얼굴이 감지되지 않음"
                frame_rgb = rgb

            # 타이머 틱
            timer_tick(is_focused, has_face, hold)

            # 목표 달성 체크
            with state_lock:
                if state["focused_time"] >= state["goal_seconds"]:
                    state["sessions"].append(
                        {
                            "focused": round(state["focused_time"]),
                            "session": round(state["session_time"]),
                            "rate": round(
                                state["focused_time"]
                                / max(state["session_time"], 1)
                                * 100,
                                1,
                            ),
                            "date": time.strftime("%m/%d %H:%M"),
                        }
                    )
                    state["phase"] = "completed"

            # JPEG 인코딩
            _, buf = cv2.imencode(
                ".jpg",
                cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 75],
            )
        else:
            # running 아닐 때: 그냥 미러링만
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])

        with frame_lock:
            current_frame = buf.tobytes()

        # 상태 브로드캐스트 (~15fps — 2프레임마다 1회)
        _emit_counter += 1
        if _emit_counter % 2 == 0:
            with state_lock:
                snap = dict(state)
            socketio.emit(
                "state",
                {
                    "phase": snap["phase"],
                    "focus_state": snap["focus_state"],
                    "focus_reason": snap["focus_reason"],
                    "ear": snap["ear"],
                    "pitch": snap["pitch"],
                    "yaw": snap["yaw"],
                    "focused_time": snap["focused_time"],
                    "session_time": snap["session_time"],
                    "goal_seconds": snap["goal_seconds"],
                    "lum_toast": time.time() < snap["lum_toast_until"],
                    "sessions": snap["sessions"],
                },
            )

        time.sleep(1 / 30)

    cap.release()


# MJPEG 스트림
def generate_frames():
    while True:
        with frame_lock:
            frame = current_frame
        if frame:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        time.sleep(1 / 30)


# 라우트
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/api/start", methods=["POST"])
def api_start():
    global camera_thread, camera_running
    data = request.json

    with state_lock:
        state["goal_seconds"] = int(data.get("goal_minutes", 30)) * 60
        state["focused_time"] = 0.0
        state["session_time"] = 0.0
        state["session_start"] = time.time()
        state["last_tick"] = None
        state["distract_start"] = None
        state["focus_state"] = "no_face"
        state["focus_reason"] = ""
        state["lum_toast_until"] = 0.0
        state["phase"] = "running"

    if not camera_running:
        camera_running = True
        camera_thread = threading.Thread(target=camera_loop, daemon=True)
        camera_thread.start()

    return jsonify({"ok": True})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    with state_lock:
        state["phase"] = "paused"
        state["last_tick"] = None
    return jsonify({"ok": True})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    with state_lock:
        state["phase"] = "running"
        state["last_tick"] = None
    return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    with state_lock:
        state["phase"] = "setup"
        state["focused_time"] = 0.0
        state["session_time"] = 0.0
        state["last_tick"] = None
        state["focus_state"] = "no_face"
        state["focus_reason"] = ""
        state["distract_start"] = None
    return jsonify({"ok": True})


@app.route("/api/new_session", methods=["POST"])
def api_new_session():
    """완료 화면에서 새 세션 준비 — phase를 setup으로 되돌림"""
    with state_lock:
        state["phase"] = "setup"
        state["focused_time"] = 0.0
        state["session_time"] = 0.0
        state["last_tick"] = None
        state["focus_state"] = "no_face"
        state["focus_reason"] = ""
        state["distract_start"] = None
    return jsonify({"ok": True})


@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify(dict(state))


if __name__ == "__main__":
    print("NoonChi 서버 시작: http://localhost:5000")

    @socketio.on("connect")
    def on_connect():
        global camera_thread, camera_running
        if not camera_running:
            camera_running = True
            camera_thread = threading.Thread(target=camera_loop, daemon=True)
            camera_thread.start()

    socketio.run(
        app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True
    )
