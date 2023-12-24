#!/bin/bash

# Runs a production container of the Sound Player module.
#
# This script will be launched by the Raspberry Pi systemd service's ExecStart:
#
# - sound-player/service/anesowa-sound-player.service
# - sound-player/service/exec-start.sh
#
# You can also launch it from the local machine instead too for debugging purposes.

ANESOWA_ROOT=$(echo $(realpath $0) | sed 's|/sound-detector.*||')

# If launched by the systemd service these two variables will be set.
ANESOWA_CONTAINER_NAME=${ANESOWA_CONTAINER_NAME:-anesowa-sound-player}
ANESOWA_VERSION=${ANESOWA_VERSION:-prod}
PULSEAUDIO_COOKIE=${PULSEAUDIO_COOKIE:-$HOME/.config/pulse/cookie}

if [ "$(uname)" == "Linux" ]; then
	extra_flags="--add-host=host.docker.internal:host-gateway"
else
	extra_flags=""
fi

set -x # Print commands as they run.

docker run \
	--tty \
	--name $ANESOWA_CONTAINER_NAME \
	--env PULSE_SERVER=host.docker.internal \
	--volume $PULSEAUDIO_COOKIE:/root/.config/pulse/cookie \
	--volume /mnt/nfs/anesowa:/anesowa/recordings:ro \
	$extra_flags \
	anesowa/sound-player:$ANESOWA_VERSION

set +x
