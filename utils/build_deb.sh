#!/bin/bash

set -o pipefail
set -o errexit


if [[ "${1}" == "--no-cache" ]]; then
    no_cache="--no-cache"
    shift
fi

if [[ "${1}" == "buster" ]] || [[ "${1}" == "bullseye" ]]; then
    distro="${1}"
    shift
else
    distro="bullseye"
fi

if [[ $distro == "buster" ]]; then
    echo "We can't build on buster for now as it needs poetry that needs python>3.7"
    exit 1
fi


docker build "utils/debuilder-${distro}" $no_cache -t "debuilder-${distro}:latest"
docker run --volume $PWD:/src:rw --rm "debuilder-${distro}:latest"
