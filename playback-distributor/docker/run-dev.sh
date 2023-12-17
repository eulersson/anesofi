#!/bin/bash

# Runs a development container of the Sound Player module.
#
# Intended for local container development mainly.

ANESOWA_ROOT=$(echo $(realpath $0) | sed 's|/sound-detector.*||')
PULSEAUDIO_COOKIE=${PULSEAUDIO_COOKIE:-$HOME/.config/pulse/cookie}

if [ "$(uname)" == "Linux" ]; then
  extra_flags=--add-host=host.docker.internal:host-gateway
else
  extra_flags=""
fi

docker run --rm --tty --interactive \
  --env PULSE_SERVER=host.docker.internal \
  --volume $PULSEAUDIO_COOKIE:/root/.config/pulse/cookie \
  --volume $ANESOWA_PROJECT_ROOT/playback-distributor:/anesowa/playback-distributor \
  $extra_flags \
  anesowa/playback-distributor:dev sh