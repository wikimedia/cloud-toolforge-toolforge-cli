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
