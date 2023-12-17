#!/bin/bash

# Builds a development image of the Sound Player module.
#
# Intended for local container development mainly.

ANESOWA_ROOT=$(echo $(realpath $0) | sed 's|/sound-player.*||')

docker build \
  --build-arg DEBUG=1 \
  --tag anesowa/sound-player:dev \
  --file $ANESOWA_ROOT/sound-player/Dockerfile \
  $ANESOWA_ROOT

