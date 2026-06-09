import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='google.protobuf')

import cv2
import numpy as np
import mediapipe as mp
import time
import math
import re
import threading
import base64
import json
from collections import deque
from flask import Flask, render_template, Response, jsonify, request
from flask_socketio import SocketIO, emit

try:
    import speech_recognition as sr
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    print("[Voice] SpeechRecognition 미설치 — pip install SpeechRecognition PyAudio")

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
    "screen_state": "unknown",   # study | distracted | unknown
    "screen_reason": "",
}
state_lock = threading.Lock()

classifier = FocusClassifier()
lum_detector = LuminanceDetector()
screen_pipeline = None

# 태블릿 분석 전용 스레드 — 카메라 루프와 완전히 분리
_screen_thread = None
_screen_thread_running = False
_screen_cache_lock = threading.Lock()
_screen_cache = {"state": "unknown", "reason": ""}  # 카메라 루프가 읽는 캐시

SCREEN_ANALYSIS_INTERVAL = 2.0  # 초 (ResNet+OCR+SBERT 합산 시간보다 충분히 길게)

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

# 오버레이 표시 여부
show_overlay = True

# 음성 인식
voice_running = False
voice_mode    = 'active'   # 'active' | 'wake'  (thread 내부 모드)
voice_thread_obj = None

# 음성 켜기/끄기 키워드 (active→wake, wake→active)
VOICE_SLEEP_WORDS = [
    # 기본형 및 명사형 종료
    '음성 꺼', '마이크 꺼', '음성 종료', '음성 비활성화', '마이크 비활성화',
    # 조사 포함 및 구어체
    '음성 꺼줘', '마이크 꺼줘', '음성 기능 꺼', '마이크 차단', '마이크 잠금',
    # 유사 발음 및 오인식 방지
    '음성꺼', '마이크꺼', '음성종료', '마크 꺼'
]

VOICE_WAKE_WORDS = [
    # 기본형 및 명사형 활성화
    '음성 켜', '마이크 켜', '음성 시작', '음성 활성화', '마이크 활성화',
    # 조사 포함 및 구어체
    '음성 켜줘', '마이크 켜줘', '음성 기능 켜', '마이크 해제', '음성 인식 시작',
    # 유사 발음 및 오인식 방지
    '음성켜', '마이크켜', '음성시작', '마크 켜'
]

VOICE_COMMANDS = {
    # -----------------------------------------------------------------
    # START (시작 / 집중)
    # -----------------------------------------------------------------
    '시작': 'start', '시작해': 'start', '시작해줘': 'start', '고': 'start',
    '집중 시작': 'start', '집중해': 'start', '집중': 'start', '집중 모드': 'start',
    '공부 시작': 'start', '타이머 시작': 'start', '시작하자': 'start',
    
    # -----------------------------------------------------------------
    # PAUSE (일시정지 / 멈춤)
    # -----------------------------------------------------------------
    '일시정지': 'pause', '일시 정지': 'pause', '일시정지해줘': 'pause',
    '멈춰': 'pause', '정지': 'pause', '멈춤': 'pause', '잠깐': 'pause', 
    '잠시만': 'pause', '잠깐만': 'pause', '기다려': 'pause', '타임': 'pause',
    '쉬기': 'pause', '휴식': 'pause',
    
    # -----------------------------------------------------------------
    # RESUME (재개 / 다시 시작)
    # -----------------------------------------------------------------
    '재개': 'resume', '다시 재개': 'resume', '계속': 'resume', '계속해': 'resume', 
    '계속하자': 'resume', '다시': 'resume', '다시 시작': 'resume', '다시시작': 'resume', 
    '이어서': 'resume', '이어서 시작': 'resume', '플레이': 'resume',
    
    # -----------------------------------------------------------------
    # RESET (초기화 / 종료)
    # -----------------------------------------------------------------
    '초기화': 'reset', '리셋': 'reset', '리셋해줘': 'reset', '처음부터': 'reset',
    '종료': 'reset', '종료해': 'reset', '끝내': 'reset', '끝': 'reset', 
    '그만': 'reset', '그만해': 'reset', '취소': 'reset', '클리어': 'reset',
    
    # -----------------------------------------------------------------
    # OVERLAY ON (마스크 / 필터 켜기)
    # -----------------------------------------------------------------
    '마스크 켜': 'overlay_on', '마스크 켜줘': 'overlay_on', '마스크 표시': 'overlay_on', 
    '필터 켜': 'overlay_on', '필터 켜줘': 'overlay_on', '필터 표시': 'overlay_on',
    '화면 마스크': 'overlay_on', '화면 필터': 'overlay_on', '마스크 보이기': 'overlay_on',
    # 띄어쓰기 오류 방지
    '마스크켜': 'overlay_on', '필터켜': 'overlay_on',
    
    # -----------------------------------------------------------------
    # OVERLAY OFF (마스크 / 필터 끄기)
    # -----------------------------------------------------------------
    '마스크 꺼': 'overlay_off', '마스크 꺼줘': 'overlay_off', '마스크 숨겨': 'overlay_off', 
    '필터 꺼': 'overlay_off', '필터 꺼줘': 'overlay_off', '필터 숨겨': 'overlay_off',
    '마스크 해제': 'overlay_off', '필터 해제': 'overlay_off', '마스크 안보이게': 'overlay_off',
    # 띄어쓰기 오류 방지
    '마스크꺼': 'overlay_off', '필터꺼': 'overlay_off',
    
    # -----------------------------------------------------------------
    # OVERLAY TOGGLE (마스크 전환)
    # -----------------------------------------------------------------
    '마스크': 'overlay_toggle', '필터': 'overlay_toggle', '마스크 전환': 'overlay_toggle',
    '필터 전환': 'overlay_toggle', '반전': 'overlay_toggle'
}

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


def parse_time_from_text(text):
    """한국어 음성에서 목표 시간(분)을 파싱. 없으면 None 반환."""
    m = re.search(r'(\d+)\s*시간\s*(\d+)\s*분', text)
    if m:
        return max(5, min(120, int(m.group(1)) * 60 + int(m.group(2))))
    m = re.search(r'(\d+)\s*시간', text)
    if m:
        return max(5, min(120, int(m.group(1)) * 60))
    m = re.search(r'(\d+)\s*분', text)
    if m:
        return max(5, min(120, int(m.group(1))))
    return None


def apply_voice_command(command):
    global camera_running, camera_thread
    if command == 'start':
        with state_lock:
            if state['phase'] in ('setup', 'completed'):
                state['focused_time'] = 0.0
                state['session_time'] = 0.0
                state['session_start'] = time.time()
                state['last_tick'] = None
                state['distract_start'] = None
                state['focus_state'] = 'no_face'
                state['focus_reason'] = ''
                state['lum_toast_until'] = 0.0
                state['phase'] = 'running'
        if not camera_running:
            camera_running = True
            camera_thread = threading.Thread(target=camera_loop, daemon=True)
            camera_thread.start()
        start_screen_thread()
    elif command == 'pause':
        with state_lock:
            if state['phase'] == 'running':
                state['phase'] = 'paused'
                state['last_tick'] = None
    elif command == 'resume':
        with state_lock:
            if state['phase'] == 'paused':
                state['phase'] = 'running'
                state['last_tick'] = None
    elif command == 'reset':
        with state_lock:
            state['phase'] = 'setup'
            state['focused_time'] = 0.0
            state['session_time'] = 0.0
            state['last_tick'] = None
            state['focus_state'] = 'no_face'
            state['focus_reason'] = ''
            state['distract_start'] = None
    elif command in ('overlay_on', 'overlay_off', 'overlay_toggle'):
        global show_overlay
        if command == 'overlay_on':
            show_overlay = True
        elif command == 'overlay_off':
            show_overlay = False
        else:
            show_overlay = not show_overlay
        socketio.emit('overlay_status', {'show': show_overlay})


def _emit_voice(active, mode, listening, **extra):
    socketio.emit('voice_status', {'active': active, 'mode': mode, 'listening': listening, **extra})


def voice_loop():
    global voice_running, voice_mode
    if not VOICE_AVAILABLE:
        return

    r = sr.Recognizer()
    r.dynamic_energy_threshold = True

    try:
        with sr.Microphone() as source:
            _emit_voice(True, voice_mode, False)
            r.adjust_for_ambient_noise(source, duration=1)

            while voice_running:
                is_wake = (voice_mode == 'wake')
                try:
                    if not is_wake:
                        _emit_voice(True, 'active', True)

                    audio = r.listen(source, timeout=5,
                                     phrase_time_limit=2 if is_wake else 5)

                    if not is_wake:
                        _emit_voice(True, 'active', False)

                    text = r.recognize_google(audio, language='ko-KR').strip()
                    print(f'[Voice] [{voice_mode}] 인식: {text}')

                    # ── wake 모드: 활성화 키워드만 감지 ──
                    if is_wake:
                        if any(w in text for w in VOICE_WAKE_WORDS):
                            voice_mode = 'active'
                            _emit_voice(True, 'active', False)
                        continue

                    # ── active 모드: 전체 명령 처리 ──

                    # 1) 음성 끄기
                    if any(w in text for w in VOICE_SLEEP_WORDS):
                        voice_mode = 'wake'
                        _emit_voice(True, 'wake', False)
                        socketio.emit('voice_command', {'command': 'voice_off', 'text': text})
                        continue

                    # 2) 시간 설정 (N분 / N시간 패턴 우선)
                    minutes = parse_time_from_text(text)
                    if minutes:
                        with state_lock:
                            state['goal_seconds'] = minutes * 60
                        socketio.emit('voice_command',
                                      {'command': 'set_time', 'text': text, 'minutes': minutes})
                        # 시간 설정과 함께 시작 명령도 있으면 계속 진행

                    # 3) 액션 명령
                    command = None
                    for keyword, cmd in VOICE_COMMANDS.items():
                        if keyword in text:
                            command = cmd
                            break
                    if command:
                        socketio.emit('voice_command', {'command': command, 'text': text})
                        apply_voice_command(command)

                except sr.WaitTimeoutError:
                    if not is_wake:
                        _emit_voice(True, voice_mode, False)
                except sr.UnknownValueError:
                    if not is_wake:
                        _emit_voice(True, voice_mode, False)
                except Exception as e:
                    print(f'[Voice] 오류: {e}')

    except Exception as e:
        print(f'[Voice] 마이크 오류: {e}')
        _emit_voice(False, 'active', False, error=str(e))
    finally:
        voice_running = False
        _emit_voice(False, 'active', False)


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


def get_screen_pipeline():
    global screen_pipeline
    if screen_pipeline is not None:
        return screen_pipeline

    try:
        from utils.screen_pipeline import ScreenAnalysisPipeline

        screen_pipeline = ScreenAnalysisPipeline()
        return screen_pipeline
    except Exception as e:
        print(f"[Screen] pipeline unavailable: {e}")
        screen_pipeline = False
        return None


def screen_analysis_loop():
    """
    태블릿 화면 분석 전용 스레드.
    카메라 루프(30fps)와 완전히 분리되어, 느린 ResNet/OCR/SBERT가
    카메라 프레임을 블로킹하지 않음.
    """
    global _screen_thread_running
    pipeline = get_screen_pipeline()
    if not pipeline:
        _screen_thread_running = False
        return

    while _screen_thread_running:
        t_start = time.time()
        try:
            result = pipeline.analyze()
            with _screen_cache_lock:
                _screen_cache["state"]  = result.state
                _screen_cache["reason"] = result.reason
        except Exception as e:
            print(f"[Screen] 백그라운드 분석 오류: {e}")

        # 분석에 걸린 시간만큼 인터벌 보정 (최소 0.5초 대기)
        elapsed = time.time() - t_start
        sleep_time = max(0.5, SCREEN_ANALYSIS_INTERVAL - elapsed)
        time.sleep(sleep_time)


def start_screen_thread():
    """세션 시작 시 태블릿 분석 스레드를 켠다."""
    global _screen_thread, _screen_thread_running
    if _screen_thread_running:
        return
    _screen_thread_running = True
    _screen_thread = threading.Thread(target=screen_analysis_loop, daemon=True)
    _screen_thread.start()


def apply_screen_judgment(camera_state, camera_reason):
    """
    백그라운드 스레드가 채워둔 캐시를 읽어 최종 상태 결정.
    블로킹 없음 — 캐시 읽기만 수행.

    판정 규칙:
        웹캠 distracted  → 항상 distracted (태블릿 무관)
        웹캠 focused + 태블릿 distracted → distracted
        웹캠 focused + 태블릿 study/unknown → focused 유지
    """
    with _screen_cache_lock:
        scr_state  = _screen_cache["state"]
        scr_reason = _screen_cache["reason"]

    if camera_state != "focused":
        return camera_state, camera_reason, scr_state, scr_reason

    if scr_state == "distracted":
        return "distracted", scr_reason, scr_state, scr_reason

    return camera_state, camera_reason, scr_state, scr_reason


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
                    try:
                        ui_state, reason, scr_state, scr_reason = apply_screen_judgment(
                            ui_state,
                            reason,
                        )
                    except Exception as e:
                        print(f"[Screen] apply_screen_judgment 예외 (무시됨): {e}")
                        scr_state, scr_reason = "unknown", f"error: {e}"
                    is_focused = (ui_state == "focused")

                    with state_lock:
                        state["focus_reason"] = reason
                        state["focus_state"] = ui_state
                        state["screen_state"] = scr_state
                        state["screen_reason"] = scr_reason
                else:
                    is_focused = True
                    with state_lock:
                        state["focus_state"] = "hold"
                        state["screen_state"] = "unknown"
                        state["screen_reason"] = ""

                frame_rgb = draw_overlay(rgb.copy(), lm, is_focused, h, w) if show_overlay else rgb
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
                    "screen_state": snap["screen_state"],
                    "screen_reason": snap["screen_reason"],
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

    start_screen_thread()
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


@app.route("/api/overlay/toggle", methods=["POST"])
def api_overlay_toggle():
    global show_overlay
    show_overlay = not show_overlay
    socketio.emit('overlay_status', {'show': show_overlay})
    return jsonify({"ok": True, "show": show_overlay})


@app.route("/api/voice/toggle", methods=["POST"])
def api_voice_toggle():
    global voice_running, voice_thread_obj, voice_mode
    if not VOICE_AVAILABLE:
        return jsonify({"ok": False, "error": "SpeechRecognition 미설치"})
    if voice_running:
        voice_running = False
        voice_mode = 'active'
        return jsonify({"ok": True, "active": False})
    voice_mode = 'active'
    voice_running = True
    voice_thread_obj = threading.Thread(target=voice_loop, daemon=True)
    voice_thread_obj.start()
    return jsonify({"ok": True, "active": True})


if __name__ == "__main__":
    print("NoonChi 서버 시작: http://localhost:5000")

    @socketio.on("connect")
    def on_connect():
        global camera_thread, camera_running, voice_thread_obj, voice_running, voice_mode
        if not camera_running:
            camera_running = True
            camera_thread = threading.Thread(target=camera_loop, daemon=True)
            camera_thread.start()
        start_screen_thread()
        if VOICE_AVAILABLE and not voice_running:
            voice_mode = 'active'
            voice_running = True
            voice_thread_obj = threading.Thread(target=voice_loop, daemon=True)
            voice_thread_obj.start()

    socketio.run(
        app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True
    )
