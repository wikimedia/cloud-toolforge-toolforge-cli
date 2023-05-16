#!/bin/bash

set -o pipefail
set -o nounset
set -o errexit

DEST_DISTRO=buster

restore_user() {
    current_user=$(stat . --format=%u)
    current_group=$(stat . --format=%g)
    find . -user root -exec chown $current_user:$current_group {} \;
}

trap restore_user EXIT

cd /src
git config --global --add safe.directory /src
echo "Updating changelog..."
new_version="${1:+"--new-version=$1"}"
EDITOR=true gbp dch \
    --release \
    $new_version

cur_version="$(dpkg-parsechangelog -S version)"
sed -i -e "s/^version =.*/version = \"$cur_version\"/" pyproject.toml

echo "Now you can send this patch for review,"\
    "remember to create a tag named 'debian/$cur_version' and pushing it when publishing the package."
