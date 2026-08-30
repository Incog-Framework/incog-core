import json
import subprocess
import sys
import os


BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)


def run_module(module_name):

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            module_name
        ],
        cwd=BASE_DIR,
        capture_output=True,
        text=True
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"{module_name} execution failed."
        )


# ============================================================
# 1. Run SHAP
# ============================================================

print("\nRunning SHAP...")

run_module(
    "xai.explain"
)


# ============================================================
# 2. Run LIME
# ============================================================

print("\nRunning LIME...")

run_module(
    "xai.lime_explain"
)


# ============================================================
# 3. Load decision
# ============================================================

decision_path = os.path.join(
    DATA_DIR,
    "decision.json"
)

with open(
    decision_path,
    "r"
) as file:

    decision = json.load(file)


# ============================================================
# 4. Load SHAP output
# ============================================================

shap_path = os.path.join(
    DATA_DIR,
    "shap_output.json"
)

with open(
    shap_path,
    "r"
) as file:

    shap_data = json.load(file)


# ============================================================
# 5. Load LIME output
# ============================================================

lime_path = os.path.join(
    DATA_DIR,
    "lime_output.json"
)

with open(
    lime_path,
    "r"
) as file:

    lime_data = json.load(file)


# ============================================================
# 6. Build final XAI output
# ============================================================

xai_output = {

    "Prediction": decision["Prediction"],

    "Confidence": decision["Confidence"],

    "EmergencyStatus": decision["EmergencyStatus"],

    "DecisionThreshold": decision["Threshold"],

    "SHAP": shap_data["SHAP"],

    "LIME": lime_data["LIME"]

}

# Carried through only when the real SensorPacket path populated them
# (see phase6/decision_engine.py) - absent for the CSV prototype path.
if "SessionID" in decision:
    xai_output["SessionID"] = decision["SessionID"]
    xai_output["TimestampMs"] = decision["TimestampMs"]


# ============================================================
# 7. Save final output
# ============================================================

output_path = os.path.join(
    DATA_DIR,
    "xai_output.json"
)

with open(
    output_path,
    "w"
) as file:

    json.dump(
        xai_output,
        file,
        indent=4
    )


# ============================================================
# 8. Display
# ============================================================

print("\nXAI pipeline completed.")

print("\nOutput:")

print(
    json.dumps(
        xai_output,
        indent=4
    )
)

print("\nSaved to:")

print(output_path)

print("\nGenerating human-readable explanation...")

result = subprocess.run(
    [
        sys.executable,
        "-m",
        "xai.explanation_generator"
    ],
    cwd=BASE_DIR
)

if result.returncode != 0:

    raise RuntimeError(
        "Human explanation generation failed."
    )

print(
    "Human-readable explanation generated successfully."
)