"""
A binary classification retrained model for identifying high-heels.
"""

import logging
import os
import shutil

from numpy.typing import NDArray

from sound_detector.config import config
from sound_detector.exceptions import TaconezException
from sound_detector.models.yamnet import YAMNetModel

if not config.use_tflite:
    import tensorflow as tf

class RetrainedModel:
    """
    Wrapper to train and use the binary classification model specific for high-heels.
    """

    saved_model_path = os.path.join(os.path.dirname(__file__), "custom", "saved_model")
    tflite_model_path = os.path.join(
        os.path.dirname(__file__), "custom", "retrained.tflite"
    )

    def __init__(self):
        self.initialized = False

    def initialize(self):
        if config.use_tflite:
            if not os.path.exists(self.tflite_model_path):
                raise TaconezException(
                    "The 'TFLite' model file for the retrained model does not exist. "
                    "You might probably need to retrain the model to generate one with "
                    "`python main.py retrain` or by calling `.build_and_retrain()` "
                    "method on the `RetrainedModel` instance."
                )
            import tflite_runtime.interpreter as tflite

            self.model = tflite.Interpreter(self.tflite_model_path)
        else:
            if not os.path.exists(self.saved_model_path):
                raise TaconezException(
                    "The 'saved_model' model file for the retrained model does not exist. "
                    "You might probably need to retrain the model to generate one with "
                    "`python main.py retrain` or by calling `.build_and_retrain()` "
                    "method on the `RetrainedModel` instance."
                )
            self.model = tf.saved_model.load(self.saved_model_path)

        logging.info("Retrained model initialized successfully and ready to use.")
        self.initialized = True

    def predict(self, waveform: NDArray) -> float:
        """
        Given a waveform, run inference on the retrained model and return the prediction
        as an unnormalized score.
        """
        if config.use_tflite:
            interpreter = self.model
            signature = interpreter.get_signature_runner()
            output = signature(audio=waveform)
            top_score = output["classifier"][0]

            logging.debug(f"Top score (high-heel) (tflite): {top_score}")
            prediction = top_score
        else:
            output = self.model(waveform)[0]

            logging.debug(f"Output (high-heel) (saved_model): {output}")
            prediction = output

        return prediction

    def build_and_retrain(self):
        """
        Extract the embeddings from YAMNet model and use it as inputs to a model we
        create. Then train the new model with our labeled sound data under `dataset`.

        Note that this won't work if the TensorFlow libraries aren't installed (e.g.
        when using the `USE_TFLITE=1` build arg for the docker image).

        For an explanatory notebook check
        `modules/sound-detector/transference-learning-high-heels.ipynb`.
        """
        logging.info("Building and retraining model...")

        train_ds, val_ds, test_ds = self.prepare_datasets()
        retrained_model = tf.keras.Sequential(
            [
                tf.keras.layers.Input(
                    shape=(1024), dtype=tf.float32, name="input_embedding"
                ),
                tf.keras.layers.Dense(512, activation="relu"),
                tf.keras.layers.Dense(200, activation="relu"),
                tf.keras.layers.Dense(1),
            ],
            name="retrained_model",
        )
        retrained_model.compile(
            loss=tf.keras.losses.BinaryCrossentropy(from_logits=True),
            optimizer="adam",
            metrics=["accuracy"],
        )

        callback = tf.keras.callbacks.EarlyStopping(
            monitor="loss", patience=3, restore_best_weights=True
        )

        # NOTE: The history is not used here but it's ideal to see the training curves
        # (model accuracy and loss).
        history = retrained_model.fit(
            train_ds, epochs=20, validation_data=val_ds, callbacks=callback
        )

        loss, accuracy = retrained_model.evaluate(test_ds)
        logging.info(f"Loss: {loss}")
        logging.info(f"Accuracy: {accuracy}")

        self.save_model(retrained_model)

    def save_model(self, retrained_model):
        """Saves a 'saved_model' and a 'tflite' model for the retrained model."""

        # Delete any model files that might exist before saving new ones.
        if os.path.exists(self.saved_model_path):
            shutil.rmtree(self.saved_model_path)

        if os.path.exists(self.tflite_model_path):
            os.remove(self.tflite_model_path)

        # TODO: See if using ReduceMaxLayer and using `reduce_max()` performs better.
        # https://github.com/eulersson/taconez/issues/112
        class ReduceMeanLayer(tf.keras.layers.Layer):
            def __init__(self, axis=0, **kwargs):
                super(ReduceMeanLayer, self).__init__(**kwargs)
                self.axis = axis

            def call(self, input):
                return tf.math.reduce_mean(input, axis=self.axis)

        # Save first a non-TFLite version.
        input_segment = tf.keras.layers.Input(shape=(), dtype=tf.float32, name="audio")

        import tensorflow_hub as tfhub

        embedding_extraction_layer = tfhub.KerasLayer(
            YAMNetModel.model_handle, trainable=False, name="yamnet"
        )

        _, embeddings_output, _ = embedding_extraction_layer(input_segment)
        serving_outputs = retrained_model(embeddings_output)
        serving_outputs = ReduceMeanLayer(axis=0, name="classifier")(serving_outputs)
        serving_model = tf.keras.Model(input_segment, serving_outputs)
        serving_model.save(self.saved_model_path, include_optimizer=False)

        # Now save the TFLite version
        converter = tf.lite.TFLiteConverter.from_saved_model(self.saved_model_path)
        tflite_model = converter.convert()

        # Save the model.
        with open(self.tflite_model_path, "wb") as f:
            f.write(tflite_model)

    def prepare_datasets(self):
        import tensorflow as tf
        import tensorflow_io as tfio

        # TensorFlow imports will only work if not using USE_TFLITE, and since this
        # method `prepare_datasets` will always be run under USE_TFLITE=1 that's why
        # why we import these here instead of at the top of the `sound_detector/audio.py`
        # module.
        @tf.function
        def load_wav_16k_mono(filename):
            """
            Load a WAV file, convert it to a float tensor, resample to 16 kHz
            single-channel audio.
            """
            file_contents = tf.io.read_file(filename)
            wav, sample_rate = tf.audio.decode_wav(file_contents, desired_channels=1)
            wav = tf.squeeze(wav, axis=-1)
            sample_rate = tf.cast(sample_rate, dtype=tf.int64)
            wav = tfio.audio.resample(wav, rate_in=sample_rate, rate_out=16000)
            return wav

        app_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        pos_dir = os.path.join(app_root, "dataset", "positive")
        neg_dir = os.path.join(app_root, "dataset", "negative")

        pos = tf.data.Dataset.list_files(pos_dir + os.path.sep + "*.wav").map(
            load_wav_16k_mono
        )
        neg = tf.data.Dataset.list_files(neg_dir + os.path.sep + "*.wav").map(
            load_wav_16k_mono
        )

        positives = tf.data.Dataset.zip(
            (pos, tf.data.Dataset.from_tensor_slices(tf.ones(len(pos))))
        )

        negatives = tf.data.Dataset.zip(
            (neg, tf.data.Dataset.from_tensor_slices(tf.zeros(len(neg))))
        )

        main_ds = positives.concatenate(negatives).shuffle(1000)
        main_ds_len = len(main_ds)
        logging.info(f"Prepared a dataset of length {main_ds_len}")

        yamnet_model = YAMNetModel()
        yamnet_model.initialize()

        def extract_embedding(wav_data, label):
            embeddings = yamnet_model.predict(wav_data, return_embeddings=True)
            num_embeddings = tf.shape(embeddings)[0]
            return (embeddings, tf.repeat(label, num_embeddings))

        main_ds = main_ds.map(extract_embedding).unbatch()
        logging.info(f"Element spec: {main_ds.element_spec}")

        cached_ds = main_ds.cache()

        num_train = int(main_ds_len * 0.8)
        num_test = int(main_ds_len * 0.1)
        num_val = main_ds_len - num_train - num_test

        logging.info(
            f"Dataset sizes: train ({num_train}), test ({num_test}), val ({num_val})"
        )

        train_ds = cached_ds.take(num_train)
        test_ds = cached_ds.skip(num_train).take(num_test)
        val_ds = cached_ds.skip(num_train + num_test).take(num_val)

        train_ds = train_ds.cache().shuffle(1000).batch(16).prefetch(tf.data.AUTOTUNE)
        val_ds = val_ds.cache().batch(16).prefetch(tf.data.AUTOTUNE)
        test_ds = test_ds.cache().batch(16).prefetch(tf.data.AUTOTUNE)

        return train_ds, val_ds, test_ds
