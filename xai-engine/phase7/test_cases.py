import os
import json
import numpy as np
import tensorflow as tf
from datetime import datetime


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

MODEL_PATH = os.path.join(
    BASE_DIR,
    "data",
    "emergency_model.tflite"
)

OUTPUT_PATH = os.path.join(
    BASE_DIR,
    "data",
    "test_results.json"
)


FEATURES = [
    "PeakAcceleration",
    "MotionVariance",
    "AudioEnergy",
    "GPSVelocity",
    "PossibleFall"
]


# ============================================================
# TEST CASES
# ============================================================

test_cases = [

    {
        "id": "TC01",
        "name": "Normal condition",
        "features": [9.8, 0.25, 0.05, 1.0, 0.0],
        "expected": "Normal"
    },

    {
        "id": "TC02",
        "name": "Normal low-motion condition",
        "features": [10.2, 0.31, 0.08, 1.2, 0.0],
        "expected": "Normal"
    },

    {
        "id": "TC03",
        "name": "Emergency fall condition",
        "features": [18.2, 18.7, 0.68, 0.0, 1.0],
        "expected": "Emergency"
    },

    {
        "id": "TC04",
        "name": "High acceleration emergency",
        "features": [24.1, 33.5, 0.82, 0.2, 1.0],
        "expected": "Emergency"
    },

    {
        "id": "TC05",
        "name": "Severe emergency condition",
        "features": [26.1, 40.2, 0.91, 0.0, 1.0],
        "expected": "Emergency"
    },

    {
        "id": "TC06",
        "name": "Normal movement with GPS velocity",
        "features": [11.5, 0.45, 0.12, 2.0, 0.0],
        "expected": "Normal"
    }
]


# ============================================================
# LOAD MODEL
# ============================================================

interpreter = tf.lite.Interpreter(
    model_path=MODEL_PATH
)

interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

input_index = input_details[0]["index"]
output_index = output_details[0]["index"]


# ============================================================
# RUN TESTS
# ============================================================

results = []

passed = 0
failed = 0


print("\nTEST CASE RESULTS")
print("=" * 70)


for test in test_cases:

    input_data = np.array(
        [test["features"]],
        dtype=np.float32
    )

    interpreter.set_tensor(
        input_index,
        input_data
    )

    interpreter.invoke()

    confidence = float(
        interpreter.get_tensor(
            output_index
        )[0][0]
    )

    if confidence >= 0.5:
        prediction = "Emergency"
    else:
        prediction = "Normal"

    status = prediction == test["expected"]

    if status:
        passed += 1
        result_status = "PASS"
    else:
        failed += 1
        result_status = "FAIL"

    result = {
        "TestCase": test["id"],
        "Name": test["name"],
        "Expected": test["expected"],
        "Predicted": prediction,
        "Confidence": round(confidence, 4),
        "Status": result_status
    }

    results.append(result)

    print(
        f"{test['id']} | "
        f"{test['name']} | "
        f"Expected: {test['expected']} | "
        f"Predicted: {prediction} | "
        f"Confidence: {confidence:.4f} | "
        f"{result_status}"
    )


# ============================================================
# SUMMARY
# ============================================================

total = len(test_cases)

test_accuracy = passed / total


output = {
    "Timestamp": datetime.now().isoformat(),
    "TotalTests": total,
    "Passed": passed,
    "Failed": failed,
    "TestAccuracy": round(test_accuracy, 4),
    "Results": results
}


with open(
    OUTPUT_PATH,
    "w"
) as file:

    json.dump(
        output,
        file,
        indent=4
    )


print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)

print("Total Tests:", total)
print("Passed:", passed)
print("Failed:", failed)
print(
    "Test Accuracy:",
    f"{test_accuracy * 100:.2f}%"
)

print("\nResults saved to:")
print(OUTPUT_PATH)