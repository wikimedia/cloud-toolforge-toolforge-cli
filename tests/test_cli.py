import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from toolforge_cli.cli import _add_discovered_subcommands, toolforge

FIXTURES_PATH = Path(__file__).parent / "fixtures"


def test_add_discovered_subcommands_returns_the_passed_cli():
    mycommand = MagicMock(spec=toolforge)
    with patch.dict(os.environ, {"PATH": str(FIXTURES_PATH)}):
        result = _add_discovered_subcommands(cli=mycommand)

    assert result is mycommand


def test_add_discovered_subcommands_finds_single_binary_in_path():
    mycommand = MagicMock(spec=toolforge)
    with patch.dict(os.environ, {"PATH": str(FIXTURES_PATH / "single_binary")}):
        _add_discovered_subcommands(cli=mycommand)

    mycommand.command.assert_called_once_with(name="binary")


def test_add_discovered_subcommands_finds_multiple_binaries_in_path():
    mycommand = MagicMock(spec=toolforge)
    with patch.dict(os.environ, {"PATH": str(FIXTURES_PATH / "multiple_binaries")}):
        _add_discovered_subcommands(cli=mycommand)

    mycommand.command.assert_has_calls(calls=[call(name="one"), call(name="two")], any_order=True)


def test_add_discovered_subcommands_finds_nested_binaries_in_path():
    mycommand = MagicMock(spec=toolforge)
    with patch.dict(
        os.environ, {"PATH": f"{FIXTURES_PATH / 'nested_binaries'}:{FIXTURES_PATH / 'nested_binaries' / 'nested_dir'}"}
    ):
        _add_discovered_subcommands(cli=mycommand)

    mycommand.command.assert_has_calls(calls=[call(name="nested"), call(name="simple")], any_order=True)


def test_add_discovered_subcommands_finds_mixed_files_in_path():
    mycommand = MagicMock(spec=toolforge)
    with patch.dict(os.environ, {"PATH": str(FIXTURES_PATH / "mixed_files")}):
        _add_discovered_subcommands(cli=mycommand)

    mycommand.command.assert_called_once_with(name="plugin")
