import os
import sys
import subprocess


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


def run_step(title, command):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    result = subprocess.run(
        command,
        cwd=BASE_DIR
    )

    if result.returncode != 0:
        print(f"\nFAILED: {title}")
        sys.exit(1)

    print(f"\nCOMPLETED: {title}")


# ============================================================
# 1. SENSOR FUSION + PREDICTION + DECISION + XAI
# ============================================================

run_step(
    "CORE AI PIPELINE",
    [
        sys.executable,
        "run_ai_pipeline.py"
    ]
)


# ============================================================
# 2. INTERVENTION
# ============================================================

run_step(
    "INTERVENTION ENGINE",
    [
        sys.executable,
        "phase7/intervention.py"
    ]
)


# ============================================================
# 3. FORENSICS
# ============================================================

run_step(
    "FORENSIC EVIDENCE",
    [
        sys.executable,
        "phase7/forensics.py"
    ]
)


# ============================================================
# 4. XAI VISUALIZATION
# ============================================================

run_step(
    "XAI VISUALIZATION",
    [
        sys.executable,
        "xai/visualize.py"
    ]
)


# ============================================================
# FINAL
# ============================================================

print("\n")
print("=" * 60)
print("INCOG AI COMPLETE PIPELINE")
print("=" * 60)
print("Sensor Fusion       : DONE")
print("TFLite Prediction   : DONE")
print("Decision Engine     : DONE")
print("SHAP                : DONE")
print("LIME                : DONE")
print("Intervention        : DONE")
print("Forensics           : DONE")
print("XAI Visualization   : DONE")
print("=" * 60)
print("SYSTEM EXECUTION COMPLETED SUCCESSFULLY")
print("=" * 60)