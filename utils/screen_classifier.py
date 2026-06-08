import os

import cv2


class ScreenClassifier:
    def __init__(self, model_path: str | None = None):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        self.model_path = model_path or os.path.normpath(
            os.path.join(base_dir, "screen_resnet18_best.pt")
        )
        self.device = None
        self.model = None
        self.class_names = []
        self.transform = None
        self.load_error = ""
        self._torch = None
        self._image_cls = None
        self._load_model()

    @property
    def available(self) -> bool:
        return self.model is not None

    def _load_model(self):
        try:
            import torch
            import torch.nn as nn
            from PIL import Image
            from torchvision import models, transforms
        except ImportError as exc:  # pragma: no cover
            self.load_error = f"torch dependencies unavailable: {exc}"
            return

        if not os.path.exists(self.model_path):
            self.load_error = f"model file not found: {self.model_path}"
            return

        try:
            self._torch = torch
            self._image_cls = Image
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            checkpoint = torch.load(self.model_path, map_location=self.device, weights_only=False)
            self.class_names = list(checkpoint["class_names"])

            model = models.resnet18(weights=None)
            model.fc = nn.Linear(model.fc.in_features, len(self.class_names))
            model.load_state_dict(checkpoint["model_state_dict"])
            model = model.to(self.device)
            model.eval()

            self.model = model
            self.transform = transforms.Compose(
                [
                    transforms.Resize((224, 224)),
                    transforms.ToTensor(),
                    transforms.Normalize(
                        [0.485, 0.456, 0.406],
                        [0.229, 0.224, 0.225],
                    ),
                ]
            )
        except Exception as exc:  # pragma: no cover
            self.model = None
            self.load_error = str(exc)

    def classify(self, frame_bgr):
        if not self.available:
            return "unknown", 0.0, self.load_error or "screen model unavailable"

        try:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            image = self._image_cls.fromarray(rgb)
            x = self.transform(image).unsqueeze(0).to(self.device)

            with self._torch.no_grad():
                output = self.model(x)
                prob = self._torch.softmax(output, dim=1)[0]
                pred = int(self._torch.argmax(prob).item())

            label = self.class_names[pred]
            confidence = float(prob[pred].item())
            return label, confidence, f"classifier: {label} ({confidence:.1%})"
        except Exception as exc:
            return "unknown", 0.0, f"classifier error: {exc}"
