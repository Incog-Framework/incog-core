import json
import numpy as np
import pandas as pd
import shap

from xai.config import (
    TFLITE_MODEL_PATH,
    DATASET_PATH,
    FEATURE_PATH,
    FEATURES,
    XAI_OUTPUT_PATH
)
from xai.tflite_utils import make_tflite_predictor


# ============================================================
# 1. Load model (the actual on-device TFLite artifact, so the
#    explanation matches what Phase 5 inference actually runs)
# ============================================================

predict = make_tflite_predictor(TFLITE_MODEL_PATH)


# ============================================================
# 2. Load training dataset
# ============================================================

training_data = pd.read_csv(DATASET_PATH)

training_data["PossibleFall"] = (
    training_data["PossibleFall"].astype(float)
)

X_train = training_data[FEATURES].astype(np.float32)


# ============================================================
# 3. Load current feature vector
# ============================================================

current_data = pd.read_csv(FEATURE_PATH)

current_data["PossibleFall"] = (
    current_data["PossibleFall"].astype(float)
)

X_current = current_data[FEATURES].astype(np.float32)


# ============================================================
# 5. SHAP
# ============================================================

background = X_train.sample(
    min(10, len(X_train)),
    random_state=42
).values

explainer = shap.KernelExplainer(
    predict,
    background
)

shap_values = explainer.shap_values(
    X_current.values,
    nsamples=100
)


# ============================================================
# 6. Handle SHAP output
# ============================================================

if isinstance(shap_values, list):

    values = np.asarray(shap_values[0])

else:

    values = np.asarray(shap_values)


values = values.reshape(
    X_current.shape[1]
)


# ============================================================
# 7. Build SHAP result
# ============================================================

shap_result = {}

for feature, value in zip(
    FEATURES,
    values
):

    shap_result[feature] = round(
        float(value),
        6
    )


# ============================================================
# 8. Prediction
# ============================================================

probability = float(
    predict(
        X_current.values
    )[0]
)

prediction = (
    "Emergency"
    if probability >= 0.5
    else "Normal"
)


# ============================================================
# 9. Print
# ============================================================

print("\nSHAP Explanation")
print("=" * 50)

for feature, value in shap_result.items():

    sign = "+" if value >= 0 else ""

    print(
        f"{feature}: "
        f"{sign}{value:.6f}"
    )

print("\nPrediction:")
print(prediction)

print("\nConfidence:")
print(
    f"{probability * 100:.2f}%"
)


# ============================================================
# 10. Save SHAP output
# ============================================================

output = {
    "Prediction": prediction,
    "Confidence": round(probability, 6),
    "SHAP": shap_result
}

shap_output_path = XAI_OUTPUT_PATH.replace(
    "xai_output.json",
    "shap_output.json"
)

with open(
    shap_output_path,
    "w"
) as file:

    json.dump(
        output,
        file,
        indent=4
    )


print("\nSHAP output saved to:")
print(shap_output_path)