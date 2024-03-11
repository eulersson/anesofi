"""
Runs inference continuously on the sound detector model to get scores (predictions).
"""

import logging
import os
import time

from datetime import datetime

from typing import Any, List, Optional, Tuple

import zmq

import numpy as np
import tflite_runtime.interpreter as tflite

from numpy.typing import NDArray
from slugify import slugify

from sound_detector.audio import record_audio, write_audio
from sound_detector.config import config
from sound_detector.db import write_db_entry
from sound_detector.events import PlayEventsManager
from sound_detector.models.retrained import RetrainedModel
from sound_detector.models.yamnet import YAMNetModel


def run_loop():
    play_events_manager = None
    push_socket = None

    if config.skip_detection_notification:
        logging.info("Upon detections the distributor won't be notified.")
    else:
        logging.info("Upon detections the distributor will be notified.")

        context = zmq.Context()

        play_events_manager = PlayEventsManager(context)

        # Connect to the distributor that will be notified upon detection:
        push_addr = config.zmq_distributor_push_addr
        push_socket = context.socket(zmq.PUSH)

        logging.info(f"Connecting to sound distribution broker at {push_addr}.")
        push_socket.connect(push_addr)
        logging.info(f"Connected ZMQ PUSH socket ({push_addr}).")

    if config.use_retrained_model:
        model = RetrainedModel()
    else:
        model = YAMNetModel()

    model.initialize()

    while True:
        run(model, play_events_manager=play_events_manager, zmq_push_socket=push_socket)


def run(
    model: Any,
    play_events_manager: Optional[PlayEventsManager] = None,
    zmq_push_socket: Optional[zmq.Socket] = None,
):
    """Records audio segments form the microphone and passes it to the model to see if
    the prediction catches the specific sound.

    If a detection happens the analyzed audio file is written down to an NFS-shared
    folder and the subsequent parts of the pipeline are notified.

    Args:
        model: Model to use for detection. It can be either an instance of our wrapper
            `YAMNetModel`, a `tflite.Interpreter` object or a trackable object (the
            returned value of `tf.saved_model.load`).
        labels: Class names of the categories the model can recognize.
        zmq_socket: Used to notify the distributor a sound has been detected.
    """
    logging.info("Running inference...")

    waveforms, waveform_binary = record_audio()

    if (
        play_events_manager
        and play_events_manager.has_been_recording_while_sound_was_playing()
    ):
        logging.info(
            "[last_play_*] Skipping sound processing because sound was being played "
            "during recording and might cause feedback."
        )
        return

    if config.use_retrained_model:
        result = run_retrained_inference(model)
        detected_sound_name = "high-heel"
    else:
        result = run_yamnet_inference(model)
        if result:
            slugified_resolved_class_name = result
            detected_sound_name = slugified_resolved_class_name

    if result and not config.skip_recording:
        # Save the file to the NFS share.
        file_path = write_audio(waveform_binary, suffix=slugified_resolved_class_name)
        relative_sound_path = os.path.relpath(file_path, config.detected_recordings_dir)

        if config.influx_db_token:
            # Write the detection to the database.
            write_db_entry(detected_sound_name, relative_sound_path)
        else:
            logging.info("Not writing database entry.")

        if not config.skip_detection_notification and zmq_push_socket:
            logging.info("Notifying distributor about detected sound")
            # Playback the sound to all slaves.
            zmq_push_socket.send_json(
                {
                    "sound_file_path": relative_sound_path,
                    "when": round(time.time()),
                }
            )


def run_retrained_inference(retrained_model, waveforms: List[NDArray]):
    """Runs inference on the network that was retrained into a binary classifier to
    discriminate high-heel sounds.

    Args:
        retrained_model: The retrained model to use for inference. If using TFLite it
            will be a `tflite.Interpreter` object, otherwise it will be a trackable
            object (the returned value of `tf.saved_model.load`).
        waveforms: The audio waveforms to run inference on. We usually record in 10
            stripes that we will iteratively run inference on and reduce the results.

    Returns:
        True if the sound is detected, False otherwise.
    """
    for waveform in waveforms:
        prediction = retrained_model.predict(waveform)

        # At the first occurrence we can return True and stop the inference.
        if prediction == True:
            return True

    return False


def run_yamnet_inference(yamnet_model: YAMNetModel, waveforms: List[NDArray]):
    """Runs inference on the YAMNet model to see if any of the sounds we are interested
    in are detected and if so the average score of the detection is returned.

    Args:
        yamnet_model: The YAMNet model to use for inference.
        waveforms: The audio waveforms to run inference on. We usually record in 10
            stripes that we will iteratively run inference on and reduce the results.

    However if the `ONLY_MONITOR_NO_DETECT` is set, then it only logs the detected
    sounds that are not in the `IGNORE_SOUNDS` list.
    """
    # Run inference on the model to see what sound hsa been detected.
    predictions: List[Tuple[str, float]] = []
    specific_sound_highest_scores = dict(
        (n, 0.0) for n in config.multiclass_detect_sounds
    )

    top_class_name = None
    for i, waveform in enumerate(waveforms):
        log_prefix = f"[{i + 1}/{len(waveforms)}]"

        scores = yamnet_model.predict(waveform)
        class_scores = np.mean(scores, axis=0)
        top_class_index = np.argmax(class_scores)
        top_score = class_scores[top_class_index]
        top_class_name = yamnet_model.labels[top_class_index]

        if top_class_name not in config.multiclass_ignore_sounds:
            predictions.append((top_class_name, top_score))

            if config.multiclass_only_monitor_no_detect:
                logging.debug(
                    f"{log_prefix} Main sound: {top_class_name} (score {top_score})"
                )

        for sound_to_detect in config.multiclass_detect_sounds:
            sound_index = yamnet_model.class_names.index(sound_to_detect)
            sound_score = class_scores[sound_index]

            specific_sound_highest_scores[sound_to_detect] = max(
                specific_sound_highest_scores[sound_to_detect], sound_score
            )

            if sound_score > 0:
                if config.multiclass_only_monitor_no_detect:
                    logging.debug(
                        f"{log_prefix} Specific sound ({sound_to_detect}) score: {sound_score}"
                    )

    if len(predictions):
        if config.multiclass_only_monitor_no_detect:
            logging.debug(f"Batch predictions: {predictions}")
            logging.debug(f"Batch highest scores: {specific_sound_highest_scores}")

    # TODO: Right now we will consider detection whenever we detect sounds that are not
    # in the IGNORE_SOUNDS list. It will be good to collect detections we can train
    # a retrained network with.
    #
    # - Produce a jupyter notebook showing how to do transfer learning
    #   https://github.com/eulersson/taconez/issues/59
    #
    # - Switch to use either normal or retrained network
    #   https://github.com/eulersson/taconez/issues/80
    #
    if config.multiclass_only_monitor_no_detect:
        detected = len(predictions)
    else:
        detected = any(
            [
                category in config.multiclass_detect_sounds
                and score > config.multiclass_detection_threshold
                for category, score in predictions
            ]
        )

    if not detected:
        return

    resolved_class_name = ""
    if top_class_name not in config.multiclass_ignore_sounds:
        resolved_class_name = top_class_name
        resolved_score = top_score
    else:
        for prediction_name, prediction_value in sorted(
            predictions, key=lambda x: x[1]
        ):
            if prediction_name not in config.multiclass_ignore_sounds:
                resolved_class_name = prediction_name
                resolved_score = prediction_value
                break

    now = datetime.now().isoformat()
    logging.info(f"DETECTION {now} {resolved_class_name} {resolved_score}")
    slugified_resolved_class_name = slugify(resolved_class_name, separator="_")

    return slugified_resolved_class_name
