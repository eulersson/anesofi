"""
Utility functions for processing audio data.
"""

import os
import wave

from datetime import datetime
from typing import List, Optional, Tuple

import pyaudio

import numpy as np

from numpy.typing import NDArray

from sound_detector.config import config

import logging


def record_audio(pyaudio_instance: pyaudio.PyAudio) -> Tuple[List[NDArray], bytes]:
    """Records audio from microphone returning an array of frames.

    The underlying neural network model is YAMNet and it has the following input
    requirements:

    > The model accepts a 1-D float32 Tensor or NumPy array of length 15600 containing
    > a 0.975 second waveform represented as mono 16 kHz samples in the range [-1.0, +1.0].

    Returns:
        A list of `AUDIO_INFERENCE_BATCH_SIZE` arrays of shape (15600,)
        values of which ranging [-1.0, 1.0] and the whole stripe binary audio as
        bytes.
    """
    stream = pyaudio_instance.open(
        format=config.audio_format,
        channels=config.audio_channels,
        rate=config.audio_rate,
        input=True,
        frames_per_buffer=config.audio_chunk,
    )

    waveforms: List[NDArray] = []
    waveform_binary = b""

    for _ in range(config.audio_inference_batch_size):
        binary_frames = []
        samples_processed = 0
        while samples_processed < config.audio_inference_samples:
            samples_to_read = max(
                config.audio_chunk, config.audio_inference_samples - samples_processed
            )
            data = stream.read(samples_to_read)
            binary_frames.append(data)
            samples_processed += samples_to_read

        partial_waveform_binary = b"".join(binary_frames)
        waveform = np.frombuffer(partial_waveform_binary, dtype=np.int16)
        waveform = waveform / 32768
        waveform = waveform.astype(np.float32)

        waveforms.append(waveform)
        waveform_binary += partial_waveform_binary

    stream.stop_stream()
    stream.close()

    return waveforms, waveform_binary


def write_audio(
    pyaudio_instance: pyaudio.PyAudio, frames: bytes, suffix: Optional[str] = ""
) -> str:
    """Writes audio frames as bytes to a file.

    Args:
        p: The PyAudio instance to use.
        frames: The audio binary content to write.
        suffix: To suffix the resulting file with.

    Returns:
        The filename where the .wav file is saved.

    https://gist.github.com/kepler62f/9d5836a1eff8b372ddf6de43b5b74d95

    """
    if suffix:
        suffix = f"_{suffix}"

    now_dt = datetime.now()

    # E.g. '2023-12-10T17:05:52.578411_knock.wav'
    file_name = now_dt.strftime("%Y-%m-%dT%H-%M-%S") + f"{suffix}.wav"

    # E.g. '2023/12/22'
    year_month_day_folder = now_dt.strftime("%Y/%m/%d")

    # E.g. '2023/12/22/2023-12-10T17:05:52.578411_knock.wav'
    relative_file_path = os.path.join(year_month_day_folder, file_name)

    # E.g. '/recordings/2023/12/22/2023-12-10T17:05:52.578411_knock.wav'
    absolute_file_path = os.path.join(
        config.detected_recordings_dir, relative_file_path
    )

    os.makedirs(os.path.dirname(absolute_file_path), exist_ok=True)

    wave_file = wave.open(absolute_file_path, "wb")
    wave_file.setnchannels(config.audio_channels)
    wave_file.setsampwidth(pyaudio_instance.get_sample_size(pyaudio.paInt16))
    wave_file.setframerate(config.audio_rate)
    wave_file.writeframes(frames)
    wave_file.close()

    logging.info(f"Saved sound to {absolute_file_path}.")

    return absolute_file_path