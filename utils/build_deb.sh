#!/bin/bash

set -o pipefail
set -o nounset
set -o errexit


docker build utils/debuilder-bullseye -t debuilder-bullseye:latest
docker run --volume $PWD:/src:rw --rm debuilder-bullseye:latest
