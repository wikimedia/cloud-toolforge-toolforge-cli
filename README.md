# toolforge-cli

CLI to run toolforge related commands

## Local development environment (guideline)

### Tox on debian testing

Clone the repo including commit hooks (instructions here https://gerrit.wikimedia.org/r/admin/repos/cloud/toolforge/toolforge-cli).

Install tox:
```
~:$ apt install tox
```

Move to the directory where you cloned the repo, and run tox:
```
/path/to/repo/toolforge-cli:$ tox
```

That will run the tests and create a virtualenv that you can use to manually debug anything you need, to enter it:
```
/path/to/repo/toolforge-cli:$ source .tox/py-tests/bin/activate
```

## Building the debian packages
### Using docker
This is the recommended way of building the packages, as it's agnostic of the OS/distro you are using.

It will not allow you to sign your package though, so if you need that try using the manual process.

```
~:$ utils/build_deb.sh
```

The first time it might take a bit more time as it will build the core image to build packages, downloading many
dependencies. The next run it will not need to download all those dependencies, so it will be way faster.

### Manual process
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
