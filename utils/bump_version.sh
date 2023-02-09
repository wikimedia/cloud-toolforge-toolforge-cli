#!/usr/bin/env bash

set -e errexit
set -e pipefail

if [[ "${1}" == "--no-cache" ]]; then
    no_cache="--no-cache"
fi

email="$(git config user.email)"
name="$(git config user.name)"

docker build utils/debuilder-bullseye $no_cache -t debuilder-bullseye:latest
docker run \
    --entrypoint /generate_changelog.sh \
    --volume $PWD:/src:rw \
    --env "EMAIL=${email}" \
    --env "NAME=${name}" \
    --rm \
    debuilder-bullseye:latest
