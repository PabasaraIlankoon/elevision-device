"""
ONNX Elephant Detector for Raspberry Pi
Handles all common YOLOv8 ONNX output formats.
No PyTorch needed — uses onnxruntime CPU only.
"""

import onnxruntime as ort
import numpy as np
import cv2
import logging
import os

log = logging.getLogger('elevision')


class ONNXElephantDetector:

    def __init__(self, model_path, confidence_threshold=0.55):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.session = None
        self.input_name = None
        self.input_height = 640
        self.input_width = 640
        self._load_model()

    def _load_model(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f'Model not found: {self.model_path}')

        mb = os.path.getsize(self.model_path) / 1024 / 1024
        log.info(f'Loading ONNX model ({mb:.1f} MB)...')

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3

        self.session = ort.InferenceSession(
            self.model_path,
            sess_options=opts,
            providers=['CPUExecutionProvider']
        )

        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = inp.shape
        if len(shape) == 4:
            if isinstance(shape[2], int) and shape[2] > 0:
                self.input_height = shape[2]
            if isinstance(shape[3], int) and shape[3] > 0:
                self.input_width = shape[3]

        outputs = [(o.name, o.shape) for o in self.session.get_outputs()]
        log.info(f'Model loaded. Input: {self.input_name} {inp.shape}')
        log.info(f'Model outputs: {outputs}')

    def preprocess(self, frame):
        resized = cv2.resize(frame, (self.input_width, self.input_height))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        normalized = rgb.astype(np.float32) / 255.0
        transposed = normalized.transpose(2, 0, 1)
        return np.expand_dims(transposed, axis=0)

    def _parse_output(self, outputs):
        best_conf = 0.0
        detections = []
        raw = outputs[0]

        if raw.ndim == 3:
            pred = raw[0]
            if pred.shape[0] < pred.shape[1]:
                pred = pred.T
            for row in pred:
                if len(row) < 5:
                    continue
                scores = row[4:]
                conf = float(np.max(scores))
                if conf >= self.confidence_threshold:
                    detections.append({'confidence': conf, 'class_id': int(np.argmax(scores))})
                    if conf > best_conf:
                        best_conf = conf

        elif raw.ndim == 2:
            for row in raw:
                if len(row) < 5:
                    continue
                scores = row[4:]
                conf = float(np.max(scores))
                if conf >= self.confidence_threshold:
                    detections.append({'confidence': conf, 'class_id': int(np.argmax(scores))})
                    if conf > best_conf:
                        best_conf = conf

        return detections, best_conf

    def detect(self, frame):
        result = {'detected': False, 'confidence': 0.0, 'count': 0}
        try:
            tensor = self.preprocess(frame)
            outputs = self.session.run(None, {self.input_name: tensor})
            detections, best_conf = self._parse_output(outputs)
            if detections:
                result['detected'] = True
                result['confidence'] = best_conf
                result['count'] = len(detections)
        except Exception as e:
            log.error(f'Detection error: {e}')
        return result

    def warmup(self):
        log.info('Running model warmup...')
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        self.detect(dummy)
        log.info('Warmup complete')
