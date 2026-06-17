import time
import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

from utils.focus_classifier import FocusClassifier

app = Flask(__name__)
app.config['SECRET_KEY'] = 'noonchi-web-secret'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

state = {
    'phase': 'setup',
    'goal_seconds': 1800,
    'focused_time': 0.0,
    'session_time': 0.0,
    'last_tick': None,
    'focus_state': 'no_face',
    'focus_reason': '',
    'ear': 0.0,
    'pitch': 0.0,
    'yaw': 0.0,
    'distract_start': None,
    'grace_period': 2.0,
    'sessions': [],
}
state_lock = threading.Lock()
classifier = FocusClassifier()
_emit_counter = 0


class _LM:
    __slots__ = ('x', 'y', 'z')
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


class LandmarkProxy:
    """JS landmark dict {idx: {x,y,z}} → MediaPipe-compatible list interface."""
    def __init__(self, data):
        self._d = {int(k): _LM(v['x'], v['y'], v.get('z', 0.0)) for k, v in data.items()}

    def __getitem__(self, i):
        return self._d.get(i, _LM(0.5, 0.5, 0.0))


def timer_tick(is_focused, has_face):
    now = time.time()
    with state_lock:
        if state['last_tick'] is None:
            state['last_tick'] = now
            return
        dt = now - state['last_tick']
        state['last_tick'] = now
        state['session_time'] += dt
        if not has_face:
            state['distract_start'] = None
            return
        if is_focused:
            state['focused_time'] += dt
            state['distract_start'] = None
        else:
            if state['distract_start'] is None:
                state['distract_start'] = now
            if now - state['distract_start'] <= state['grace_period']:
                state['focused_time'] += dt


def emit_state():
    with state_lock:
        s = dict(state)
    socketio.emit('state', {
        'phase':        s['phase'],
        'focus_state':  s['focus_state'],
        'focus_reason': s['focus_reason'],
        'ear':          s['ear'],
        'pitch':        s['pitch'],
        'yaw':          s['yaw'],
        'focused_time': s['focused_time'],
        'session_time': s['session_time'],
        'goal_seconds': s['goal_seconds'],
        'lum_toast':    False,
        'sessions':     s['sessions'],
        'screen_state': 'unknown',
        'screen_reason': '',
    })


@socketio.on('connect')
def on_connect():
    emit_state()


@socketio.on('face_data')
def handle_face_data(data):
    global _emit_counter

    with state_lock:
        phase = state['phase']
    if phase != 'running':
        return

    has_face = bool(data.get('has_face', False))
    pitch    = float(data.get('pitch', 0.0))
    yaw      = float(data.get('yaw',   0.0))
    ear      = float(data.get('ear',   0.0))
    raw_lm   = data.get('landmarks', {})

    with state_lock:
        state['ear']   = round(ear, 3)
        state['pitch'] = round(pitch, 1)
        state['yaw']   = round(yaw, 1)

    if has_face and raw_lm:
        lm = LandmarkProxy(raw_lm)
        focus_state, reason, _ = classifier.classify(pitch, yaw, 0.0, lm)
        ui = {'sleepy': 'sleepy', 'distracted': 'distracted', 'normal': 'focused'}.get(focus_state, 'distracted')
        with state_lock:
            state['focus_state']  = ui
            state['focus_reason'] = reason
        is_focused = (ui == 'focused')
    else:
        with state_lock:
            state['focus_state']  = 'no_face'
            state['focus_reason'] = '얼굴이 감지되지 않음'
        is_focused = False

    timer_tick(is_focused, has_face)

    with state_lock:
        if state['phase'] == 'running' and state['focused_time'] >= state['goal_seconds']:
            state['sessions'].append({
                'focused': round(state['focused_time']),
                'session': round(state['session_time']),
                'rate':    round(state['focused_time'] / max(state['session_time'], 1) * 100, 1),
                'date':    time.strftime('%m/%d %H:%M'),
            })
            state['phase'] = 'completed'

    _emit_counter += 1
    if _emit_counter % 2 == 0:
        emit_state()


@app.route('/')
def index():
    return render_template('index_web.html')


@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.json or {}
    with state_lock:
        state.update({
            'goal_seconds':  int(data.get('goal_minutes', 30)) * 60,
            'focused_time':  0.0,
            'session_time':  0.0,
            'last_tick':     None,
            'distract_start': None,
            'focus_state':   'no_face',
            'focus_reason':  '',
            'phase':         'running',
        })
    return jsonify({'ok': True})


@app.route('/api/pause', methods=['POST'])
def api_pause():
    with state_lock:
        state['phase'] = 'paused'
        state['last_tick'] = None
    return jsonify({'ok': True})


@app.route('/api/resume', methods=['POST'])
def api_resume():
    with state_lock:
        state['phase'] = 'running'
        state['last_tick'] = None
    return jsonify({'ok': True})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    with state_lock:
        state.update({
            'phase': 'setup', 'focused_time': 0.0, 'session_time': 0.0,
            'last_tick': None, 'distract_start': None,
            'focus_state': 'no_face', 'focus_reason': '',
        })
    return jsonify({'ok': True})


@app.route('/api/new_session', methods=['POST'])
def api_new_session():
    return api_reset()


@app.route('/api/state')
def api_state():
    with state_lock:
        return jsonify(dict(state))


if __name__ == '__main__':
    print('NoonChi Web: http://localhost:5000')
    # 배포 시: gunicorn -k eventlet -w 1 web_app:app
    socketio.run(app, host='0.0.0.0', port=5000, debug=False,
                 use_reloader=False, allow_unsafe_werkzeug=True)
