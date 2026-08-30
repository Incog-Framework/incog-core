import json
import os
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

INPUT_PATH = os.path.join(
    BASE_DIR,
    "data",
    "xai_output.json"
)

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "data",
    "xai_visualizations"
)

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)

with open(INPUT_PATH, "r") as file:
    data = json.load(file)

# ============================================================
# SHAP
# ============================================================

shap_data = data.get("SHAP", {})

if shap_data:
    features = list(shap_data.keys())
    values = list(shap_data.values())

    plt.figure(figsize=(10, 6))

    plt.barh(
        features,
        values
    )

    plt.xlabel("SHAP Contribution")
    plt.ylabel("Features")
    plt.title("SHAP Feature Contributions")

    plt.tight_layout()

    shap_path = os.path.join(
        OUTPUT_DIR,
        "shap_explanation.png"
    )

    plt.savefig(
        shap_path,
        dpi=300
    )

    plt.close()

    print("SHAP visualization saved:")
    print(shap_path)


# ============================================================
# LIME
# ============================================================

lime_data = data.get("LIME", {})

if lime_data:
    features = list(lime_data.keys())
    values = list(lime_data.values())

    plt.figure(figsize=(10, 6))

    plt.barh(
        features,
        values
    )

    plt.xlabel("LIME Contribution")
    plt.ylabel("Features")
    plt.title("LIME Feature Contributions")

    plt.tight_layout()

    lime_path = os.path.join(
        OUTPUT_DIR,
        "lime_explanation.png"
    )

    plt.savefig(
        lime_path,
        dpi=300
    )

    plt.close()

    print("LIME visualization saved:")
    print(lime_path)


print("\nXAI visualizations completed.")