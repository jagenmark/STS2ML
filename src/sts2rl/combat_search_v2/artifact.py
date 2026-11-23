"""Versioned NumPy inference artifact for the completed-turn value heads."""
from dataclasses import dataclass
import hashlib

import numpy as np

from .features import FEATURE_NAMES, SCHEMA2_NAMES, VERSION, extract_leaf_features

ARTIFACT_VERSION = 1
SCHEMA_SHA256 = hashlib.sha256("\n".join(FEATURE_NAMES).encode()).hexdigest()
WIDTHS = ((), (32, 16), (64, 32))


def sigmoid(logits):
    return np.float32(1) / (np.float32(1) + np.exp(-np.clip(logits, -30, 30)))


@dataclass(frozen=True, slots=True)
class CombatValueModel:
    mean: np.ndarray
    scale: np.ndarray
    layers: tuple[tuple[np.ndarray, np.ndarray], ...]
    calibration: np.ndarray
    schema: int = VERSION

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            schema = data["schema"].item()
            names = {2: SCHEMA2_NAMES, VERSION: FEATURE_NAMES}.get(schema)
            if (data["version"].item() != ARTIFACT_VERSION or names is None
                    or data["schema_sha256"].item() != hashlib.sha256("\n".join(names).encode()).hexdigest()):
                raise ValueError("Incompatible combat value v2 feature schema")
            widths = tuple(data["widths"].tolist())
            if widths not in WIDTHS:
                raise ValueError("Unsupported combat value v2 model shape")

            def array(key, shape):
                vector = data[key]
                if vector.dtype != np.float32 or vector.shape != shape or not np.isfinite(vector).all():
                    raise ValueError(f"Invalid combat value v2 parameter {key}")
                vector.flags.writeable = False
                return vector

            dimensions = (len(names), *widths, 2)
            n = dimensions[0]
            layers = tuple((array(f"w{i}", (left, right)), array(f"b{i}", (right,)))
                           for i, (left, right) in enumerate(zip(dimensions, dimensions[1:])))
            model = cls(array("mean", (n,)), array("scale", (n,)), layers, array("calibration", (2,)), schema)
            if np.any(model.scale <= 0) or model.calibration[0] <= 0:
                raise ValueError("Invalid combat value v2 normalization")
            return model

    def predict(self, features):
        values = (features - self.mean) * self.scale
        for weights, bias in self.layers[:-1]:
            values = np.maximum(values @ weights + bias, np.float32(0))
        weights, bias = self.layers[-1]
        logits = values @ weights + bias
        logits[..., 0] = logits[..., 0] * self.calibration[0] + self.calibration[1]
        return sigmoid(logits)

    def leaf(self, state):
        probability, fraction = self.predict(extract_leaf_features(state, schema=self.schema))
        return float(probability), float(fraction)


def export_model(path, mean, scale, layers, calibration, widths):
    arrays = {key: value for i, (w, b) in enumerate(layers) for key, value in ((f"w{i}", w), (f"b{i}", b))}
    np.savez_compressed(path, version=ARTIFACT_VERSION, schema=VERSION, schema_sha256=SCHEMA_SHA256,
                        widths=np.array(widths, dtype=np.int32), mean=mean, scale=scale,
                        calibration=np.asarray(calibration, dtype=np.float32), **arrays)
