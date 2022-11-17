import json
import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from toolforge_cli.cli import _add_discovered_subcommands, _get_run_data, _get_task_details_lines, toolforge

FIXTURES_PATH = Path(__file__).parent / "fixtures"


def _get_run_from_pipeline_k8s_object(file_path: Path) -> Dict[str, Any]:
    with open(file_path, "r") as f:
        run = json.load(f)
        return run


@pytest.fixture
def successful_pipeline_run():
    return _get_run_from_pipeline_k8s_object(FIXTURES_PATH / "pipeline_successful_run.json")


@pytest.fixture
def oom_pipeline_run():
    return _get_run_from_pipeline_k8s_object(FIXTURES_PATH / "pipeline_oom_run.json")


@pytest.fixture
def pipeline_run_without_status():
    return _get_run_from_pipeline_k8s_object(FIXTURES_PATH / "pipeline_without_status.json")


def test__get_run_data_from_successful_pipeline_run(successful_pipeline_run):
    actual = _get_run_data(successful_pipeline_run)
    expected = {
        "name": "minikube-user-buildpacks-pipelinerun-khl99",
        "params": {
            "image_name": "python",
            "image_tag": "snap",
            "repo_url": "192.168.65.2/minikube-user",
            "source_url": "https://github.com/david-caro/wm-lol",
            "builder_image": "docker-registry.tools.wmflabs.org/toolforge-bullseye0-builder:latest",
        },
        "start_time": "2022-11-08T09:07:35Z",
        "end_time": "2022-11-08T09:11:06Z",
        "status": "ok",
    }
    assert actual == expected


def test__get_run_data_from_failed_pipeline_run(oom_pipeline_run):
    actual = _get_run_data(oom_pipeline_run)
    expected = {
        "name": "test-buildpacks-pipelinerun-7h7c7",
        "params": {
            "image_name": "python",
            "image_tag": "snap",
            "repo_url": "harbor.toolsbeta.wmflabs.org/test",
            "source_url": "https://github.com/david-caro/wm-lol.git",
            "builder_image": "docker-registry.tools.wmflabs.org/toolforge-buster0-builder",
        },
        "start_time": "2022-09-27T08:09:22Z",
        "end_time": "2022-09-27T08:09:58Z",
        "status": "error",
    }
    assert actual == expected


def test__get_run_data_from_pipeline_run_without_status(pipeline_run_without_status):
    actual = _get_run_data(pipeline_run_without_status)
    expected = {
        "name": "minikube-user-buildpacks-pipelinerun-mkgjp",
        "params": {
            "image_name": "dcaro",
            "image_tag": "latest",
            "repo_url": "harbor.tools.wmflabs.org/minikube-user",
            "source_url": "https://github.com/david-caro/wm-lol",
            "builder_image": "docker-registry.tools.wmflabs.org/toolforge-bullseye0-builder",
        },
        "start_time": "pending",
        "end_time": "N/A",
        "status": "not started",
    }
    assert actual == expected


def test__get_task_details_from_successful_pipeline_run(successful_pipeline_run):
    k8s_client = Mock()
    actual = _get_task_details_lines(successful_pipeline_run, k8s_client)
    expected = [
        "\x1b[1mTask:\x1b[0m build-from-git",
        "    \x1b[1mStart time:\x1b[0m 2022-11-08T09:07:35Z",
        "    \x1b[1mEnd time:\x1b[0m 2022-11-08T09:11:06Z",
        "    \x1b[1mStatus:\x1b[0m \x1b[32mok\x1b[0m(Succeeded)",
        "    \x1b[1mMessage:\x1b[0m All Steps have completed executing",
        "",
        "\x1b[1m    Steps:\x1b[0m",
        "        \x1b[1mStep:\x1b[0m clone - \x1b[32mok\x1b[0m(Completed)",
        "        \x1b[1mStep:\x1b[0m prepare - \x1b[32mok\x1b[0m(Completed)",
        "        \x1b[1mStep:\x1b[0m copy-stack-toml - \x1b[32mok\x1b[0m(Completed)",
        "        \x1b[1mStep:\x1b[0m detect - \x1b[32mok\x1b[0m(Completed)",
        "        \x1b[1mStep:\x1b[0m analyze - \x1b[32mok\x1b[0m(Completed)",
        "        \x1b[1mStep:\x1b[0m restore - \x1b[32mok\x1b[0m(Completed)",
        "        \x1b[1mStep:\x1b[0m build - \x1b[32mok\x1b[0m(Completed)",
        "        \x1b[1mStep:\x1b[0m export - \x1b[32mok\x1b[0m(Completed)",
        "        \x1b[1mStep:\x1b[0m results - \x1b[32mok\x1b[0m(Completed)",
        "",
    ]
    assert actual == expected


def test__get_task_details_from_pipeline_run_without_steps(oom_pipeline_run):
    k8s_client = Mock()
    actual = _get_task_details_lines(oom_pipeline_run, k8s_client)
    expected = [
        "\x1b[1mTask:\x1b[0m build-from-git",
        "    \x1b[1mStart time:\x1b[0m 2022-09-27T08:09:22Z",
        "    \x1b[1mEnd time:\x1b[0m 2022-09-27T08:09:58Z",
        "    \x1b[1mStatus:\x1b[0m \x1b[31merror\x1b[0m(Failed)",
        "    \x1b[1mMessage:\x1b[0m The node was low on resource: memory. Container step-export was using 7804Ki, which exceeds its request of 0. Container step-results was using 6756Ki, which exceeds its request of 0. Container step-build was using 26352Ki, which exceeds its request of 0. ",
        "",
    ]
    assert actual == expected


def test_add_discovered_subcommands_returns_the_passed_cli():
    mycommand = Mock(spec=toolforge)
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
