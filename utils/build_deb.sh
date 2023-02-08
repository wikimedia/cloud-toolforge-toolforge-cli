#!/bin/bash

set -o pipefail
set -o errexit


if [[ "${1}" == "--no-cache" ]]; then
    no_cache="--no-cache"
fi

docker build utils/debuilder-bullseye $no_cache -t debuilder-bullseye:latest
docker run --volume $PWD:/src:rw --rm debuilder-bullseye:latest
