import subprocess
import sys


steps = [
    (
        "PHASE 4 - Sensor Fusion",
        "phase4/sensor_processing.py"
    ),
    (
        "PHASE 5 - TFLite Prediction",
        "phase5/tflite_predict.py"
    ),
    (
        "PHASE 6 - Decision Engine",
        "phase6/decision_engine.py"
    ),
    (
        "XAI - SHAP + LIME",
        "xai/xai_pipeline.py"
    )
]


for name, script in steps:

    print("\n")
    print("=" * 60)
    print(name)
    print("=" * 60)

    result = subprocess.run(
        [
            sys.executable,
            script
        ]
    )

    if result.returncode != 0:

        print(
            f"\nFAILED: {name}"
        )

        sys.exit(
            result.returncode
        )


print("\n")
print("=" * 60)
print("INC0G AI PIPELINE COMPLETED SUCCESSFULLY")
print("=" * 60)

print("\nGenerating XAI visualizations...")

visualization_result = subprocess.run(
    [
        sys.executable,
        "-m",
        "xai.visualize"
    ]
)

if visualization_result.returncode != 0:
    raise RuntimeError(
        "XAI visualization failed."
    )

print("XAI visualizations generated successfully.")