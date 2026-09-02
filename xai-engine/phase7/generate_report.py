import json
import os
from datetime import datetime


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)

OUTPUT_PATH = os.path.join(
    DATA_DIR,
    "final_system_report.json"
)


def load_json(filename):

    path = os.path.join(
        DATA_DIR,
        filename
    )

    with open(path, "r") as file:
        return json.load(file)


feature_path = os.path.join(
    DATA_DIR,
    "feature_vector.csv"
)

decision = load_json("decision.json")
xai = load_json("xai_output.json")
intervention = load_json("intervention.json")
metrics = load_json("tflite_model_metrics.json")

report = {
    "ReportTimestamp": datetime.now().isoformat(),

    "System": "INCOG AI",

    "FeatureVectorAvailable":
        os.path.exists(feature_path),

    "Prediction": {
        "Class": decision["Prediction"],
        "Confidence": decision["Confidence"]
    },

    "Decision": {
        "EmergencyStatus":
            decision["EmergencyStatus"],
        "Threshold":
            decision["Threshold"]
    },

    "XAI": {
        "SHAP": "SHAP" in xai,
        "LIME": "LIME" in xai
    },

    "Intervention": intervention["Intervention"],

    "Forensics": {
        "EvidenceManifest":
            os.path.exists(
                os.path.join(
                    DATA_DIR,
                    "forensic_evidence",
                    "evidence_manifest.json"
                )
            )
    },

    "ModelMetrics": metrics,

    "SystemStatus": "SUCCESS"
}


# Tie the whole report back to the originating Ghost State session when the
# real SensorPacket path produced it (absent for the CSV prototype path).
if "SessionID" in decision:
    report["SessionID"] = decision["SessionID"]
    report["SessionTimestampMs"] = decision["TimestampMs"]


with open(
    OUTPUT_PATH,
    "w"
) as file:

    json.dump(
        report,
        file,
        indent=4
    )


print("\nFINAL SYSTEM REPORT")
print("=" * 60)
print(json.dumps(report, indent=4))

print("\nReport saved to:")
print(OUTPUT_PATH)