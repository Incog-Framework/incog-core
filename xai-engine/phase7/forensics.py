import json
import os
import hashlib
from datetime import datetime


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)

FORENSIC_DIR = os.path.join(
    DATA_DIR,
    "forensic_evidence"
)

os.makedirs(
    FORENSIC_DIR,
    exist_ok=True
)


FILES = [
    "feature_vector.csv",
    "prediction_tflite.json",
    "decision.json",
    "xai_output.json",
    "intervention.json"
]


evidence = {
    "EvidenceID": datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    ),
    "Timestamp": datetime.now().isoformat(),
    "Files": []
}


for filename in FILES:

    path = os.path.join(
        DATA_DIR,
        filename
    )

    if not os.path.exists(path):
        continue

    with open(path, "rb") as file:
        content = file.read()

    sha256_hash = hashlib.sha256(
        content
    ).hexdigest()

    evidence["Files"].append(
        {
            "filename": filename,
            "sha256": sha256_hash,
            "size_bytes": len(content)
        }
    )


output_path = os.path.join(
    FORENSIC_DIR,
    "evidence_manifest.json"
)

with open(output_path, "w") as file:
    json.dump(
        evidence,
        file,
        indent=4
    )


print("\nFORENSIC EVIDENCE")
print("=" * 50)

print(json.dumps(evidence, indent=4))

print("\nEvidence manifest saved to:")
print(output_path)