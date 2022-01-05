#!/bin/bash -e

black \
    --check \
    --diff \
    . \
|| {
    echo "You can autoformat your code running:"
    echo "    tox -e format"
    exit 1
}
isort \
    --check-only \
    --diff \
    . \
|| {
    echo "You can autoformat your code running:"
    echo "    tox -e format"
    exit 1
}
