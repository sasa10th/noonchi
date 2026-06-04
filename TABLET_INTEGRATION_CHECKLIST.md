# Tablet Integration Checklist

1. Keep the existing webcam flow untouched.
   Add tablet logic only after the existing webcam state is computed.

2. Define the tablet pipeline as separate modules.
   Suggested files:
   `utils/screen_capture.py`
   `utils/screen_classifier.py`
   `utils/screen_ocr.py`
   `utils/screen_pipeline.py`

3. Add tablet capture as a best-effort feature.
   If the `iPad` window is missing or capture fails, the app should continue running in webcam-only mode.

4. Load tablet dependencies lazily.
   Do not import or initialize `torch`, OCR engines, or screen capture code at app startup.
   Initialize them only when needed during a running session.

5. Keep the final decision rule simple.
   First compute webcam state.
   Only if webcam state is `focused`, evaluate the tablet state.

6. Use these tablet states internally.
   `study`
   `distracted`
   `unknown`

7. Map final states like this.
   Webcam `distracted` wins over everything.
   Webcam `focused` + tablet `study` => final `focused`
   Webcam `focused` + tablet `distracted` => final `screen_distracted`
   Webcam `focused` + tablet `unknown` => keep `focused` unless a stricter policy is chosen later

8. Use OCR only as a fallback.
   Run OCR only when the image classifier returns `unknown`.

9. Keep OCR keyword lists configurable.
   Separate `study_words` and `bad_words`.
   Make it easy to edit them without changing app logic.

10. Do not block app startup on OCR installation.
    If Tesseract or another OCR engine is missing, tablet OCR should degrade to `unknown` instead of crashing.

11. Do not block app startup on model loading.
    If the screen classifier model is missing, tablet logic should degrade gracefully and leave webcam logic intact.

12. Add minimal frontend changes only.
    The existing UI should remain the same except for optionally showing `screen_distracted`.

13. Add logging before full integration.
    Log:
    webcam state
    tablet classifier result
    OCR fallback result
    final merged state

14. Test in this order.
    Webcam-only boot
    Webcam-only run with tablet logic unavailable
    iPad window capture success
    Screen classifier success
    OCR fallback success
    Final merged decision

15. Re-check environment assumptions before integrating.
    Python interpreter
    MediaPipe version/API
    OCR engine installation
    Window title used for iPad capture
    Model file path
