# toolforge-cli

CLI to run toolforge related commands

## Local development environment (guideline)

### Requirements

You need to have [Poetry](https://github.com/python-poetry/poetry) installed globally. While you can install it with package managers such as `pip` or `homebrew`, it's highly recommended to use the official installer:
https://python-poetry.org/docs/#installing-with-the-official-installer

### Testing with tox on debian

Clone the repo including commit hooks (instructions here https://gerrit.wikimedia.org/r/admin/repos/cloud/toolforge/toolforge-cli).

Install tox (this is the only debian-specific part):
```
~:$ apt install tox
```

Move to the directory where you cloned the repo, and run tox:
```
/path/to/repo/toolforge-cli:$ tox
```

That will run the tests and create a virtualenv that you can use to manually debug anything you need, to enter it:
```
/path/to/repo/toolforge-cli:$ source .tox/py3-tests/bin/activate
```

## Building the debian packages

The process will be:
* Bump the version
  * Update the `debian/changelog` and `pyproject.toml` (done by `bump_version.sh`)
  * Create a patch, get it reviewed and merged
* Create a tag (`debian/<new_version>`) and push
* Build the package (done by `build_deb.sh`)
* Upload the package to the toolforge repositories

Let's get started!

### Update the changelog and pyproject.toml
To do so, you can run the scrip:
```
~:$ utils/bump_version.sh
```

That will:

* create an entry in `debian/changelog` from the git log since the last `debian/*` tag
* bump the version in `pyproject.toml` too

At this point, you should create a commit and send it for review, and continue once merged.

```
~:$  git commit -m "Bumped version to <new_version>" --signoff
~:$  git review  # if you have https://opendev.org/opendev/git-review installed
```

### Get the version bump commit merged

Review the `changelog` and the `pyproject.toml` changes to make sure it's what you want (it uses your name, email, etc.), and ask
for reviews.

### Create and upload the debian tag

Once merged, you can create a tag named `debian/<new_version>` locally and push it to the repository (ex. `git push gerrit debian/<new_version>`).

### Build the package
#### With containers
This is the recommended way of building the package, as it's agnostic of the OS/distro you are using.

It will not allow you to sign your package though, so if you need that try using the manual process.

Now you can build the package with:

```
~:$ utils/build_deb.sh
```

The first time it might take a bit more time as it will build the core image to build packages, downloading many
dependencies. The next run it will not need to download all those dependencies, so it will be way faster.

**NOTE**: If it failed when installing packages, try passing `--no-cache` to force rebuilding the cached layers.

#### wmcs-package-build script
An alternative is using the wmcs-package-build.py script that you can find in
the operations/puppet repo at modules/toolforge/files

```
$ ./wmcs-package-build.py --git-repo https://gerrit.wikimedia.org/r/cloud/toolforge/toolforge-cli -a buster-toolsbeta -a bullseye-toolsbeta --git-branch main --backports --toolforge-repo=tools --build-dist=bullseye
```

The script will SSH into a build server, build the package there, and publish it
to two repos: `buster-toolsbeta` and `bullseye-tooslbeta`.

The additional params `--backports, --toolforge-repo=tools
--build-dist=bullseye` are necessary because the build requires Poetry and other
build tools not available in the buster repos.

If that command is successful, you should then copy the package from the
"toolsbeta" to the "tools" distribution:

```
ssh tools-services-05.tools.eqiad1.wikimedia.cloud
$ sudo -i
# aptly repo copy buster-toolsbeta buster-tools toolforge-cli_VERSION_all
# aptly repo copy bullseye-toolsbeta bullseye-tools toolforge-cli_VERSION_all
# aptly publish --skip-signing update buster-tools
# aptly publish --skip-signing update bullseye-tools
```

Additional documentation on the wmcs-package-build script is available at
https://wikitech.wikimedia.org/wiki/Portal:Toolforge/Admin/Packaging#wmcs-package-build

#### Manual process (only on debian)
For this you'll need debuild installed:
```
~:$ sudo apt install debuild
```

Install the build dependencies, this requires devscripts and equivs:
```
~:$ sudo apt install devscripts equivs
...
/path/to/repo/toolforge-cli:$ sudo mk-build-deps --install debian/control
```

Or just manually check the `debian/control` file `Build-Dependencies` and install them manually.

Note that it will build a debian package right there, and install it, you can remove it to clean up the dependencies any time.


Now for the actuall build:
```
/path/to/repo/toolforge-cli:$ debuild -uc -us
```

That will end up creating an unsigned package under `../toolforge-cli.*.deb`.
If you want to sign it, you will have to do something like:
```
/path/to/repo/toolforge-cli:$ debuild -kmy@key.org
```

### Uploading to the toolforge repository

Once you have built the package you want, you can uploade it following:
https://wikitech.wikimedia.org/wiki/Portal:Toolforge/Admin/Packaging#Uploading_a_package
