from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional, Dict
import numpy as np
import os

@dataclass
class FocusClassifier:
    """
    RandomForest 기반 사용자 집중 상태 분류기.
    
    모델: user_state_rf.pkl (joblib)
    입력: 3-5초 시간 윈도우의 집계 통계 특성
    출력: sleepy / distracted / normal
    """
    window_size: int = 45  # 30fps에서 3초 ≈ 90프레임
    
    _model = None
    _feature_names = None
    _classes = None
    _model_loaded = False
    
    # 프레임 버퍼 (landmarks, head_pose, motion)
    _frame_buffer: Deque[Dict] = field(default_factory=lambda: deque(maxlen=90))
    
    def __post_init__(self):
        self._frame_buffer = deque(maxlen=self.window_size)
        self._load_model()

    def _load_model(self):
        """joblib을 사용하여 RandomForest 모델 로드"""
        if self._model_loaded:
            return
        
        try:
            import joblib
        except ImportError:
            print("joblib을 설치해주세요: pip install joblib")
            self._model_loaded = True
            return
        
        model_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            "user_state_rf.pkl"
        )
        
        try:
            model_data = joblib.load(model_path)
            self._model = model_data["model"]
            self._feature_names = model_data["features"]
            self._classes = model_data["classes"]
            self._model_loaded = True
            print(f"✓ 모델 로드 성공: {model_path}")
            print(f"  - 특성: {len(self._feature_names)}개")
            print(f"  - 클래스: {list(self._classes)}")
        except Exception as e:
            print(f"✗ 모델 로드 실패: {e}")
            self._model_loaded = True

    def update_frame(self, landmarks, pitch: float, yaw: float, roll: float = 0.0):
        """
        새로운 프레임의 landmarks와 head pose를 버퍼에 추가.
        
        Args:
            landmarks: MediaPipe face landmarks (객체)
            pitch: 고개 위/아래 (도)
            yaw: 고개 좌/우 (도)
            roll: 고개 기울임 (도)
        """
        if landmarks is None:
            return
        
        try:
            # EAR 계산
            from utils.ear_calculator import compute_ear
            ear = compute_ear(landmarks)
            
            frame_data = {
                "ear": ear,
                "pitch": pitch,
                "yaw": yaw,
                "roll": roll,
                "landmarks": landmarks
            }
            
            self._frame_buffer.append(frame_data)
        except Exception as e:
            print(f"프레임 업데이트 에러: {e}")

    def _compute_features(self) -> Optional[Dict[str, float]]:
        """
        버퍼에서 시간 윈도우 특성 계산.
        """
        try:
            if len(self._frame_buffer) < 10:  # 최소 프레임 필요
                return None
            
            ears = np.array([f["ear"] for f in self._frame_buffer])
            pitches = np.array([f["pitch"] for f in self._frame_buffer])
            yaws = np.array([f["yaw"] for f in self._frame_buffer])
            rolls = np.array([f["roll"] for f in self._frame_buffer])
            
            features = {}
            
            # EAR 통계
            features["mean_ear"] = float(np.mean(ears))
            features["std_ear"] = float(np.std(ears))
            features["min_ear"] = float(np.min(ears))
            features["max_ear"] = float(np.max(ears))
            features["ear_variance"] = float(np.var(ears))
            
            # Blink 빈도 (EAR < 0.2를 drowsy로 간주)
            low_ear_frames = np.sum(ears < 0.2)
            features["low_ear_ratio"] = float(low_ear_frames / len(ears))
            features["blink_frequency"] = float(low_ear_frames)
            
            # Head pose 통계
            features["mean_pitch"] = float(np.mean(pitches))
            features["std_pitch"] = float(np.std(pitches))
            features["min_pitch"] = float(np.min(pitches))
            features["max_pitch"] = float(np.max(pitches))
            
            features["mean_yaw"] = float(np.mean(yaws))
            features["std_yaw"] = float(np.std(yaws))
            features["min_yaw"] = float(np.min(yaws))
            features["max_yaw"] = float(np.max(yaws))
            
            features["mean_roll"] = float(np.mean(rolls))
            features["std_roll"] = float(np.std(rolls))
            
            # Motion (frame-to-frame landmark 변화)
            motion_magnitudes = []
            for i in range(1, len(self._frame_buffer)):
                try:
                    prev_frame = self._frame_buffer[i-1]
                    curr_frame = self._frame_buffer[i]
                    
                    if prev_frame["landmarks"] and curr_frame["landmarks"]:
                        prev_nose = np.array([
                            prev_frame["landmarks"][1].x, 
                            prev_frame["landmarks"][1].y
                        ])
                        curr_nose = np.array([
                            curr_frame["landmarks"][1].x, 
                            curr_frame["landmarks"][1].y
                        ])
                        motion = float(np.linalg.norm(curr_nose - prev_nose))
                        motion_magnitudes.append(motion)
                except (AttributeError, IndexError, TypeError):
                    continue
            
            if motion_magnitudes:
                motion_array = np.array(motion_magnitudes)
                features["motion_mean"] = float(np.mean(motion_array))
                features["motion_std"] = float(np.std(motion_array))
                features["motion_max"] = float(np.max(motion_array))
                features["motion_variance"] = float(np.var(motion_array))
            else:
                features["motion_mean"] = 0.0
                features["motion_std"] = 0.0
                features["motion_max"] = 0.0
                features["motion_variance"] = 0.0
            
            # Gaze stability (eye center consistency)
            eye_positions = []
            for f in self._frame_buffer:
                try:
                    landmarks = f["landmarks"]
                    if landmarks:
                        l_eye = np.array([landmarks[263].x, landmarks[263].y])
                        r_eye = np.array([landmarks[33].x, landmarks[33].y])
                        eye_center = (l_eye + r_eye) / 2
                        eye_positions.append(eye_center)
                except (AttributeError, IndexError, TypeError):
                    continue
            
            if eye_positions:
                eye_positions_array = np.array(eye_positions)
                gaze_variance = float(np.var(eye_positions_array))
                features["gaze_variance"] = gaze_variance
                features["gaze_stability"] = float(1.0 / (1.0 + gaze_variance))
            else:
                features["gaze_variance"] = 0.0
                features["gaze_stability"] = 0.0
            
            return features
        except Exception as e:
            print(f"특성 계산 에러: {e}")
            return None

    def classify(self, pitch: float, yaw: float, roll: float = 0.0, landmarks=None) -> tuple[str, str, float]:
        """
        사용자 상태 분류 (sleepy / distracted / normal).
        
        Args:
            pitch, yaw, roll: head pose (도)
            landmarks: MediaPipe landmarks
            
        Returns:
            (state, reason, confidence)
            state: "sleepy" / "distracted" / "normal"
            reason: 상태 설명
            confidence: 신뢰도 (0-100%)
        """
        # 새 프레임 추가
        self.update_frame(landmarks, pitch, yaw, roll)
        
        # 모델 미로드
        if self._model is None:
            return "normal", "모델 미로드", 0.0
        
        # 특성 계산
        features = self._compute_features()
        if features is None:
            return "normal", "수집 중...", 0.0
        
        try:
            # 특성 벡터 구성 (feature_names 순서대로)
            X = np.array([[features.get(name, 0.0) for name in self._feature_names]])
            
            # 예측
            prediction = self._model.predict(X)[0]
            probabilities = self._model.predict_proba(X)[0]
            
            # 신뢰도 (최대 클래스 확률)
            confidence = float(max(probabilities) * 100)
            
            # 상태별 메시지
            state_messages = {
                "sleepy": f"졸음 상태 (신뢰도: {confidence:.1f}%)",
                "distracted": f"산만함 (신뢰도: {confidence:.1f}%)",
                "normal": f"집중 중 (신뢰도: {confidence:.1f}%)",
            }
            
            reason = state_messages.get(prediction, "알 수 없음")
            
            return prediction, reason, confidence
            
        except Exception as e:
            print(f"예측 오류: {e}")
            return "normal", f"예측 오류: {e}", 0.0

    def update_params(self, *args, **kwargs):
        """호환성 유지 (더 이상 사용되지 않음)"""
        pass

