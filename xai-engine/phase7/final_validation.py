import json
import os


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)


required_files = [
    "feature_vector.csv",
    "prediction_tflite.json",
    "decision.json",
    "xai_output.json",
    "intervention.json",
    "tflite_model_metrics.json",
    "final_system_report.json",
    os.path.join(
        "forensic_evidence",
        "evidence_manifest.json"
    ),
    os.path.join(
        "xai_visualizations",
        "shap_explanation.png"
    ),
    os.path.join(
        "xai_visualizations",
        "lime_explanation.png"
    )
]


print("\nFINAL SYSTEM VALIDATION")
print("=" * 60)

all_passed = True


for filename in required_files:

    path = os.path.join(
        DATA_DIR,
        filename
    )

    if os.path.exists(path):

        print(
            f"[PASS] {filename}"
        )

    else:

        print(
            f"[FAIL] {filename}"
        )

        all_passed = False


print("\n" + "=" * 60)

if all_passed:

    print("ALL REQUIRED COMPONENTS PASSED")
    print("INCOG AI PROJECT VALIDATION: SUCCESS")

else:

    print("VALIDATION FAILED")
    raise SystemExit(1)

print("=" * 60)