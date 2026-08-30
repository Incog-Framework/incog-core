import json
import numpy as np
import pandas as pd

from lime.lime_tabular import LimeTabularExplainer

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
# 2. Load training data
# ============================================================

training_data = pd.read_csv(
    DATASET_PATH
)

training_data["PossibleFall"] = (
    training_data["PossibleFall"].astype(float)
)

X_train = training_data[
    FEATURES
].astype(np.float32).values


# ============================================================
# 3. Load current feature vector
# ============================================================

current_data = pd.read_csv(
    FEATURE_PATH
)

current_data["PossibleFall"] = (
    current_data["PossibleFall"].astype(float)
)

instance = current_data[
    FEATURES
].iloc[0].astype(np.float32).values


# ============================================================
# 4. Prediction function
# ============================================================

def predict_proba(data):

    emergency_probability = predict(data)

    normal_probability = (
        1.0 - emergency_probability
    )

    return np.column_stack(
        [
            normal_probability,
            emergency_probability
        ]
    )


# ============================================================
# 5. Create LIME explainer
# ============================================================

explainer = LimeTabularExplainer(
    X_train,
    feature_names=FEATURES,
    class_names=[
        "Normal",
        "Emergency"
    ],
    mode="classification",
    discretize_continuous=True,
    random_state=42
)


# ============================================================
# 6. Generate explanation
# ============================================================

explanation = explainer.explain_instance(
    instance,
    predict_proba,
    num_features=len(FEATURES)
)


# ============================================================
# 7. Build LIME result
# ============================================================

lime_result = {}

for feature, contribution in explanation.as_list(
    label=1
):

    lime_result[feature] = round(
        float(contribution),
        6
    )


# ============================================================
# 8. Prediction
# ============================================================

probability = float(
    predict(
        instance.reshape(1, -1)
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

print("\nLIME Explanation")
print("=" * 50)

for feature, contribution in lime_result.items():

    sign = "+" if contribution >= 0 else ""

    print(
        f"{feature}: "
        f"{sign}{contribution:.6f}"
    )

print("\nPrediction:")
print(prediction)

print("\nConfidence:")
print(
    f"{probability * 100:.2f}%"
)


# ============================================================
# 10. Save LIME output
# ============================================================

output = {
    "Prediction": prediction,
    "Confidence": round(probability, 6),
    "LIME": lime_result
}

lime_output_path = XAI_OUTPUT_PATH.replace(
    "xai_output.json",
    "lime_output.json"
)

with open(
    lime_output_path,
    "w"
) as file:

    json.dump(
        output,
        file,
        indent=4
    )


print("\nLIME output saved to:")
print(lime_output_path)