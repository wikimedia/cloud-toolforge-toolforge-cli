#!/usr/bin/env python3
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict

import click

TOOLFORGE_PREFIX = "toolforge-"
LOGGER = logging.getLogger("toolforge" if __name__ == "__main__" else __name__)


@click.group(name="toolforge", help="Toolforge command line")
@click.option("-v", "--verbose", help="Show extra verbose output", is_flag=True)
def toolforge(verbose: bool) -> None:
    pass


def _add_discovered_subcommands(cli: click.Group) -> click.Group:
    bins_path = os.environ.get("PATH", ".")
    subcommands: Dict[str, Path] = {}
    LOGGER.debug("Looking for subcommands...")
    for dir_str in bins_path.split(":"):
        dir_path = Path(dir_str)
        LOGGER.debug(f"Checking under {dir_path}...")
        for command in dir_path.glob(f"{TOOLFORGE_PREFIX}*"):
            LOGGER.debug(f"Checking {command}...")
            if command.is_file() and os.access(command, os.X_OK):
                subcommand_name = command.name[len(TOOLFORGE_PREFIX) :]
                subcommands[subcommand_name] = command

    print(f"Found {len(subcommands)} subcommands.")
    for name, binary in subcommands.items():

        @cli.command(name=name)
        @click.option("-h", "--help", is_flag=True, default=False)
        @click.argument("args", nargs=-1, type=click.UNPROCESSED)
        def _new_command(args, help: bool):  # noqa
            if help:
                args = ["--help"] + list(args)

            cmd = [binary, *args]
            proc = subprocess.Popen(
                args=cmd, bufsize=0, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, shell=False
            )
            returncode = proc.poll()
            while returncode is None:
                time.sleep(0.1)
                returncode = proc.poll()

            if proc.returncode != 0:
                raise subprocess.CalledProcessError(returncode=proc.returncode, output=None, stderr=None, cmd=cmd)

    return cli


def main():
    # this is needed to setup the logging before the subcommand discovery
    res = toolforge.parse_args(ctx=click.Context(command=toolforge), args=sys.argv)
    if "-v" in res or "--verbose" in res:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    _add_discovered_subcommands(cli=toolforge)
    toolforge()


if __name__ == "__main__":
    main()
