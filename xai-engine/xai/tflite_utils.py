import numpy as np
import tensorflow as tf


def make_tflite_predictor(model_path):
    """Load a TFLite model and return a batched predict(X) -> np.ndarray[N] function.

    Using this (instead of the source Keras model) as the prediction function for
    SHAP/LIME ensures explanations correspond to the exact artifact used for
    on-device inference in Phase 5, not just its Keras source model.
    """

    interpreter = tf.lite.Interpreter(model_path=model_path)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_index = input_details[0]["index"]
    output_index = output_details[0]["index"]

    def predict(data):
        data = np.asarray(data, dtype=np.float32)

        if data.ndim == 1:
            data = data.reshape(1, -1)

        outputs = np.empty(data.shape[0], dtype=np.float32)

        for i in range(data.shape[0]):
            interpreter.set_tensor(
                input_index,
                data[i:i + 1]
            )

            interpreter.invoke()

            outputs[i] = interpreter.get_tensor(output_index)[0][0]

        return outputs

    return predict
