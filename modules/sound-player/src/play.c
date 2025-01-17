// Copyright 2024 Ramon Blanquer Ruiz
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <pulse/error.h>
#include <pulse/simple.h>

#define BUFSIZE 2048

// The sample format to use.
static const pa_sample_spec ss = {
    .format = PA_SAMPLE_S16LE, .rate = 16000, .channels = 1};

// Uses PulseAudio simple API to play a sound. The input given to it is an
// absolute file path of a .wav file.
int play_sound(char *sound_file) {
  printf("[player] Playing sound file: %s\n", sound_file);

  pa_simple *s = NULL;
  int ret = 1;
  int error;

  int fd;

  if ((fd = open(sound_file, O_RDONLY)) < 0) {
    fprintf(stderr, __FILE__ ": open() failed: %s\n", strerror(errno));
    return errno;
  }

  if (dup2(fd, STDIN_FILENO) < 0) {
    fprintf(stderr, __FILE__ ": dup2() failed: %s\n", strerror(errno));
    return errno;
  }

  close(fd);

  // Create a new playback stream.
  if (!(s = pa_simple_new(NULL, sound_file, PA_STREAM_PLAYBACK, NULL,
                          "playback", &ss, NULL, NULL, &error))) {
    fprintf(stderr, __FILE__ ": pa_simple_new() failed: %s\n",
            pa_strerror(errno));
  }

  for (;;) {
    uint8_t buf[BUFSIZE];
    ssize_t r;

    // Read some data.
    if ((r = read(STDIN_FILENO, buf, sizeof(buf))) <= 0) {
      if (r == 0) {
        break;
      }
      fprintf(stderr, __FILE__ ": read() failed: %s\n", strerror(errno));
      return errno;
    }

    // And play it.
    if (pa_simple_write(s, buf, (size_t)r, &error) < 0) {
      fprintf(stderr, __FILE__ ": pa_simple_write() failed: %s",
              pa_strerror(error));
      return error;
    }
  }

  return EXIT_SUCCESS;
}
