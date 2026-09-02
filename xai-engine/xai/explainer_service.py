"""Callable SHAP/LIME explainer — the server-side entry point for the backend.

WHY THIS EXISTS
---------------
xai/explain.py and xai/lime_explain.py do their work at IMPORT time and talk
to the rest of the system through files in data/. That is fine for a local
pipeline run and unusable from a web service: importing them runs a full
explanation, and the only way to pass input is to write data/feature_vector.csv
first.

This module exposes the same capability as a plain function:

    from xai.explainer_service import explain

    result = explain(
        features={"PeakAcceleration": 24.1, "MotionVariance": 33.6,
                  "AudioEnergy": 0.66, "GPSVelocity": 0.0,
                  "PossibleFall": True},
        session={"SessionID": "SESS-...", "TimestampMs": 1734900000000}
    )

No files are read or written. The returned dict is the same shape as
data/xai_output.json, so anything already consuming that artifact keeps
working.

WHERE THIS RUNS
---------------
Server-side, after evidence arrives — never on the phone. The blocker is the
dependency stack (Python + shap + lime + TensorFlow) and the need for the
training background distribution, NOT latency: measured warm cost is ~60 ms
per explanation with LIME on, because the model is tiny. Run
`python -m xai.explainer_service --benchmark` to re-measure on the host that
will actually serve it.

That cost means the backend can afford to call this synchronously inside a
request handler; it does not have to be queued.

The explainer holds a TFLite interpreter and a background sample; both are
built once and reused. It is NOT thread-safe — a TFLite interpreter cannot
be driven from two threads at once. Use one instance per worker process, or
serialise calls behind a lock/queue.
"""

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from xai.config import (                    # noqa: E402
    DATASET_PATH,
    FEATURES,
    TFLITE_MODEL_PATH
)
from xai.explanation_generator import (     # noqa: E402
    build_explanation,
    rank_contributions
)
from xai.tflite_utils import make_tflite_predictor   # noqa: E402

CLASSIFICATION_THRESHOLD = 0.50
DECISION_THRESHOLD = 0.80

# KernelExplainer sample budget. 100 matches what the file-based pipeline
# uses, so explanations from either path are comparable.
SHAP_SAMPLES = 100
BACKGROUND_SIZE = 10


class Explainer:
    """Holds the model + background data so they are loaded once.

    Not thread-safe (see the module docstring).
    """

    def __init__(self, model_path=None, dataset_path=None):
        self._model_path = str(model_path or TFLITE_MODEL_PATH)
        self._dataset_path = str(dataset_path or DATASET_PATH)
        self._lock = threading.Lock()

        self._predict = None
        self._background = None
        self._shap_explainer = None
        self._lime_explainer = None

    # ---------- lazy construction ----------

    def _ensure_model(self):
        if self._predict is None:
            self._predict = make_tflite_predictor(self._model_path)

        return self._predict

    def _ensure_background(self):
        if self._background is None:
            training = pd.read_csv(self._dataset_path)
            training["PossibleFall"] = training["PossibleFall"].astype(float)
            self._background = training[FEATURES].astype(np.float32)

        return self._background

    def _ensure_shap(self):
        if self._shap_explainer is None:
            import shap

            background = self._ensure_background()

            self._shap_explainer = shap.KernelExplainer(
                self._ensure_model(),
                background.sample(
                    min(BACKGROUND_SIZE, len(background)),
                    random_state=42
                ).values
            )

        return self._shap_explainer

    def _ensure_lime(self):
        if self._lime_explainer is None:
            from lime.lime_tabular import LimeTabularExplainer

            self._lime_explainer = LimeTabularExplainer(
                self._ensure_background().values,
                feature_names=FEATURES,
                class_names=["Normal", "Emergency"],
                mode="classification",
                discretize_continuous=True,
                random_state=42
            )

        return self._lime_explainer

    # ---------- public API ----------

    def predict(self, features):
        """Confidence for one feature dict, through the deployed TFLite graph."""

        row = to_model_row(features)

        return float(self._ensure_model()(row.reshape(1, -1))[0])

    def explain(self, features, prediction=None, session=None,
                include_lime=True):
        """Full explanation for one decision.

        Args:
            features: the five features, by name. PossibleFall may be bool
                or 0/1.
            prediction: optional {"Confidence": float, ...} from the phone.
                When given, the phone's confidence is authoritative and is
                NOT recomputed - the explanation must describe the decision
                that was actually made on-device. A mismatch against this
                model is surfaced as ConfidenceMismatch rather than hidden.
            session: optional {"SessionID": str, "TimestampMs": int}.
            include_lime: LIME roughly doubles the cost; skip it for a
                cheaper SHAP-only explanation.

        Returns:
            dict shaped exactly like data/xai_output.json.
        """

        with self._lock:
            return self._explain_locked(
                features, prediction, session, include_lime
            )

    def _explain_locked(self, features, prediction, session, include_lime):
        feature_values = normalise_features(features)
        row = to_model_row(feature_values)

        local_confidence = float(self._ensure_model()(row.reshape(1, -1))[0])

        # Prefer full-precision ConfidenceRaw, but fall back to Confidence
        # when the key is absent OR present-but-null - a JSON bridge that
        # emits `"ConfidenceRaw": null` must not blow up here.
        confidence = local_confidence

        if prediction:
            raw = prediction.get("ConfidenceRaw")

            if raw is None:
                raw = prediction.get("Confidence")

            if raw is not None:
                confidence = float(raw)

        emergency_status = confidence >= DECISION_THRESHOLD

        label = (
            "Emergency"
            if confidence >= CLASSIFICATION_THRESHOLD
            else "Normal"
        )

        # ---- SHAP ----

        shap_values = self._ensure_shap().shap_values(
            row.reshape(1, -1),
            nsamples=SHAP_SAMPLES,
            silent=True
        )

        values = np.asarray(
            shap_values[0] if isinstance(shap_values, list) else shap_values
        ).reshape(len(FEATURES))

        shap_result = {
            feature: round(float(value), 6)
            for feature, value in zip(FEATURES, values)
        }

        # ---- LIME ----

        lime_result = {}

        if include_lime:
            def predict_proba(data):
                emergency = self._ensure_model()(data)
                return np.column_stack([1.0 - emergency, emergency])

            explanation = self._ensure_lime().explain_instance(
                row,
                predict_proba,
                num_features=len(FEATURES)
            )

            lime_result = {
                str(name): round(float(weight), 6)
                for name, weight in explanation.as_list(label=1)
            }

        # ---- assemble, same shape as data/xai_output.json ----

        document = {
            "Prediction": label,
            "Confidence": round(confidence, 4),
            "EmergencyStatus": emergency_status,
            "DecisionThreshold": DECISION_THRESHOLD,
            "SHAP": shap_result,
            "LIME": lime_result
        }

        if session:
            if session.get("SessionID") is not None:
                document["SessionID"] = session["SessionID"]
            if session.get("TimestampMs") is not None:
                document["TimestampMs"] = int(session["TimestampMs"])

        document["FeatureValues"] = feature_values

        narrative = build_explanation(document, feature_values)

        document["TopContributingFeatures"] = rank_contributions(
            shap_result, feature_values
        )
        document["Explanation"] = {
            "Title": narrative["Title"],
            "Message": narrative["Message"],
            "Reasons": narrative["Reasons"]
        }

        # If the phone's confidence and this model's disagree, the phone is
        # probably running a different .tflite. Surface it loudly - silently
        # explaining a different model than the one that decided would make
        # the explanation misleading.
        if abs(local_confidence - confidence) > 1e-3:
            document["ConfidenceMismatch"] = {
                "reported_by_device": round(confidence, 6),
                "recomputed_by_explainer": round(local_confidence, 6),
                "note": (
                    "the explainer's model disagrees with the device - check "
                    "that mobile-client ships the same emergency_model.tflite"
                )
            }

        return document


# ============================================================
# Feature helpers
# ============================================================

def normalise_features(features):
    """Validate and coerce a feature dict to the model's contract."""

    missing = [name for name in FEATURES if name not in features]

    if missing:
        raise ValueError(
            f"missing features {missing}; expected all of {FEATURES}"
        )

    normalised = {}

    for name in FEATURES[:-1]:
        value = features[name]

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number, got {value!r}")

        normalised[name] = round(float(value), 4)

    fall = features["PossibleFall"]

    if isinstance(fall, str):
        raise ValueError(
            f"PossibleFall must be a boolean or 0/1, got {fall!r}"
        )

    normalised["PossibleFall"] = bool(fall)

    return normalised


def to_model_row(features):
    """Feature dict -> float32 vector in the model's fixed order."""

    values = normalise_features(features)

    return np.array(
        [
            values["PeakAcceleration"],
            values["MotionVariance"],
            values["AudioEnergy"],
            values["GPSVelocity"],
            1.0 if values["PossibleFall"] else 0.0
        ],
        dtype=np.float32
    )


# ============================================================
# Module-level convenience (one shared instance)
# ============================================================

_DEFAULT = None


def get_explainer():
    global _DEFAULT

    if _DEFAULT is None:
        _DEFAULT = Explainer()

    return _DEFAULT


def explain(features, prediction=None, session=None, include_lime=True):
    """Explain one decision using the shared explainer instance."""

    return get_explainer().explain(
        features,
        prediction=prediction,
        session=session,
        include_lime=include_lime
    )


def explain_evidence(evidence):
    """Explain a decrypted evidence package from the security module.

    Accepts the AIResult-shaped payload the backend receives:

        {"SessionID": ..., "TimestampMs": ..., "Prediction": ...,
         "Confidence": ..., "EmergencyStatus": ...,
         "FeatureValues" | "Features": {...}}
    """

    features = evidence.get("FeatureValues") or evidence.get("Features")

    if not features:
        raise ValueError(
            "evidence must carry FeatureValues (or Features) with the five "
            "model inputs"
        )

    return explain(
        features,
        prediction={
            "Confidence": evidence.get("Confidence"),
            "ConfidenceRaw": evidence.get("ConfidenceRaw")
        } if evidence.get("Confidence") is not None else None,
        session={
            "SessionID": evidence.get("SessionID"),
            "TimestampMs": evidence.get("TimestampMs")
        }
    )


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        help="path to an evidence/AIResult JSON file to explain"
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="measure explanation latency (what the backend must budget for)"
    )
    parser.add_argument("--no-lime", action="store_true")
    arguments = parser.parse_args()

    sample = {
        "PeakAcceleration": 24.0967,
        "MotionVariance": 33.5643,
        "AudioEnergy": 0.6561,
        "GPSVelocity": 0.0,
        "PossibleFall": True
    }

    if arguments.evidence:
        evidence = json.loads(
            Path(arguments.evidence).read_text(encoding="utf-8")
        )
        result = explain_evidence(evidence)
    else:
        result = explain(
            sample,
            session={
                "SessionID": "SESS-CLI-DEMO",
                "TimestampMs": 1_734_900_000_000
            },
            include_lime=not arguments.no_lime
        )

    print(json.dumps(result, indent=4))

    if arguments.benchmark:
        explainer = get_explainer()

        # warm caches first so the numbers reflect steady state
        explainer.explain(sample, include_lime=not arguments.no_lime)

        timings = []

        for _ in range(3):
            started = time.perf_counter()
            explainer.explain(sample, include_lime=not arguments.no_lime)
            timings.append(time.perf_counter() - started)

        print(
            f"\nWarm latency over {len(timings)} runs: "
            f"min={min(timings):.3f}s median={sorted(timings)[1]:.3f}s "
            f"max={max(timings):.3f}s  (LIME "
            f"{'off' if arguments.no_lime else 'on'})"
        )
        print(
            "Cheap enough to run synchronously in a request handler if the "
            "backend wants to - the model is tiny, so KernelExplainer's few "
            "hundred evaluations cost very little.\n"
            "Note this does NOT mean it could run on-device: the blocker is "
            "the dependency stack (Python + shap + lime + TensorFlow) and the "
            "need for the training background distribution, not the latency."
        )


if __name__ == "__main__":
    main()
