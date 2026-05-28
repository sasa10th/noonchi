import numpy as np

LEFT_EYE_IDX  = [362, 385, 387, 263, 373, 380]
RIGHT_EYE_IDX = [33, 160, 158, 133, 153, 144]

def euclidean(p1, p2):
    return np.linalg.norm(np.array(p1) - np.array(p2))

def ear_from_landmarks(landmarks, eye_idx):
    pts = [(landmarks[i].x, landmarks[i].y) for i in eye_idx]
    A = euclidean(pts[1], pts[5])
    B = euclidean(pts[2], pts[4])
    C = euclidean(pts[0], pts[3])
    if C < 1e-6:
        return 0.3
    return (A + B) / (2.0 * C)

def compute_ear(landmarks):
    left  = ear_from_landmarks(landmarks, LEFT_EYE_IDX)
    right = ear_from_landmarks(landmarks, RIGHT_EYE_IDX)
    return (left + right) / 2.0
