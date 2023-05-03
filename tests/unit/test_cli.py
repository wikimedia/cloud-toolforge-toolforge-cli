import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock

import pytest


from toolforge_cli.cli import (
    _get_run_data,
    _get_status_data,
    _get_task_details,
    _get_task_details_lines
)


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


def test__get_status_data_from_sucessful_pipeline_run(successful_pipeline_run):
    actual = _get_status_data(successful_pipeline_run)
    expected = {
        "start_time": "2022-11-08T09:07:35Z",
        "end_time": "2022-11-08T09:11:06Z",
        "status": "ok",
        "reason": "Succeeded",
        "message": "Tasks Completed: 1 (Failed: 0, Cancelled 0), Skipped: 0",
    }
    assert actual == expected


def test__get_status_data_from_failed_pipeline_run(oom_pipeline_run):
    actual = _get_status_data(oom_pipeline_run)
    expected = {
        "start_time": "2022-09-27T08:09:22Z",
        "end_time": "2022-09-27T08:09:58Z",
        "status": "error",
        "reason": "Failed",
        "message": "Tasks Completed: 1 (Failed: 1, Cancelled 0), Skipped: 0",
    }
    assert actual == expected


def test__get_status_data_from_pipeline_run_without_status(pipeline_run_without_status):
    actual = _get_status_data(pipeline_run_without_status)
    expected = {"start_time": "pending", "end_time": "N/A", "status": "not started", "reason": "N/A", "message": "N/A"}
    assert actual == expected


def test__get_run_data_from_successful_pipeline_run(successful_pipeline_run):
    actual = _get_run_data(successful_pipeline_run)
    expected = {
        "name": "minikube-user-buildpacks-pipelinerun-khl99",
        "start_time": "2022-11-08T09:07:35Z",
        "end_time": "2022-11-08T09:11:06Z",
        "status": "ok",
        "reason": "Succeeded",
        "message": "Tasks Completed: 1 (Failed: 0, Cancelled 0), Skipped: 0",
        "params": {
            "image_name": "python",
            "image_tag": "snap",
            "repo_url": "192.168.65.2/minikube-user",
            "source_url": "https://github.com/david-caro/wm-lol",
            "builder_image": "docker-registry.tools.wmflabs.org/toolforge-bullseye0-builder:latest",
            "ref": "upstream_buildpacks",
        }
    }
    assert actual == expected


def test__get_run_data_from_failed_pipeline_run(oom_pipeline_run):
    actual = _get_run_data(oom_pipeline_run)
    expected = {
        "name": "test-buildpacks-pipelinerun-7h7c7",
        "start_time": "2022-09-27T08:09:22Z",
        "end_time": "2022-09-27T08:09:58Z",
        "status": "error",
        "reason": "Failed",
        "message": "Tasks Completed: 1 (Failed: 1, Cancelled 0), Skipped: 0",
        "params": {
            "image_name": "python",
            "image_tag": "snap",
            "repo_url": "harbor.toolsbeta.wmflabs.org/test",
            "source_url": "https://github.com/david-caro/wm-lol.git",
            "builder_image": "docker-registry.tools.wmflabs.org/toolforge-buster0-builder",
            "ref": "upstream_buildpacks",
        }
    }
    assert actual == expected


def test__get_run_data_from_pipeline_run_without_status(pipeline_run_without_status):
    actual = _get_run_data(pipeline_run_without_status)
    expected = {
        "name": "minikube-user-buildpacks-pipelinerun-mkgjp",
        "start_time": "pending",
        "end_time": "N/A",
        "status": "not started",
        "reason": "N/A",
        "message": "N/A",
        "params": {
            "image_name": "dcaro",
            "image_tag": "latest",
            "repo_url": "harbor.tools.wmflabs.org/minikube-user",
            "source_url": "https://github.com/david-caro/wm-lol",
            "builder_image": "docker-registry.tools.wmflabs.org/toolforge-bullseye0-builder",
            "ref": "upstream_buildpacks",
        }
    }
    assert actual == expected


def test__get_task_details_from_successful_pipeline_run(successful_pipeline_run):
    k8s_client = Mock()
    actual_json = _get_task_details(successful_pipeline_run, k8s_client)
    actual_str = _get_task_details_lines(actual_json)
    expected_str = [
        "\x1b[1mTask:\x1b[0m build-from-git",
        "    \x1b[1mStart time:\x1b[0m 2022-11-08T09:07:35Z",
        "    \x1b[1mEnd time:\x1b[0m 2022-11-08T09:11:06Z",
        "    \x1b[1mStatus:\x1b[0m \x1b[32mok\x1b[0m (Succeeded)",
        "    \x1b[1mMessage:\x1b[0m All Steps have completed executing",
        "",
        "\x1b[1m    Steps:\x1b[0m",
        "        \x1b[1mStep:\x1b[0m clone - \x1b[32mok\x1b[0m (Completed)",
        "        \x1b[1mStep:\x1b[0m prepare - \x1b[32mok\x1b[0m (Completed)",
        "        \x1b[1mStep:\x1b[0m copy-stack-toml - \x1b[32mok\x1b[0m (Completed)",
        "        \x1b[1mStep:\x1b[0m detect - \x1b[32mok\x1b[0m (Completed)",
        "        \x1b[1mStep:\x1b[0m analyze - \x1b[32mok\x1b[0m (Completed)",
        "        \x1b[1mStep:\x1b[0m restore - \x1b[32mok\x1b[0m (Completed)",
        "        \x1b[1mStep:\x1b[0m build - \x1b[32mok\x1b[0m (Completed)",
        "        \x1b[1mStep:\x1b[0m export - \x1b[32mok\x1b[0m (Completed)",
        "        \x1b[1mStep:\x1b[0m results - \x1b[32mok\x1b[0m (Completed)",
        "",
    ]
    expected_json = [
        {
            'task_name': 'build-from-git',
            'start_time': '2022-11-08T09:07:35Z',
            'end_time': '2022-11-08T09:11:06Z',
            'status': 'ok',
            'reason': 'Succeeded',
            'message': 'All Steps have completed executing',
            'steps': [
                {'name': 'clone', 'reason': 'Completed', 'status': 'ok'},
                {'name': 'prepare', 'reason': 'Completed', 'status': 'ok'},
                {'name': 'copy-stack-toml', 'reason': 'Completed', 'status': 'ok'},
                {'name': 'detect', 'reason': 'Completed', 'status': 'ok'},
                {'name': 'analyze', 'reason': 'Completed', 'status': 'ok'},
                {'name': 'restore', 'reason': 'Completed', 'status': 'ok'},
                {'name': 'build', 'reason': 'Completed', 'status': 'ok'},
                {'name': 'export', 'reason': 'Completed', 'status': 'ok'},
                {'name': 'results', 'reason': 'Completed', 'status': 'ok'}
            ],
        }
    ]

    assert actual_str == expected_str
    assert actual_json == expected_json


def test__get_task_details_from_pipeline_run_without_status(pipeline_run_without_status):
    k8s_client = Mock()
    actual_json = _get_task_details(pipeline_run_without_status, k8s_client)
    actual_str = _get_task_details_lines(actual_json)
    expected_str = []
    expected_json = []
    assert actual_str == expected_str
    assert actual_json == expected_json


def test__get_task_details_from_pipeline_run_without_steps(oom_pipeline_run):
    k8s_client = Mock()
    actual_json = _get_task_details(oom_pipeline_run, k8s_client)
    actual_str = _get_task_details_lines(actual_json)
    expected_str = [
        "\x1b[1mTask:\x1b[0m build-from-git",
        "    \x1b[1mStart time:\x1b[0m 2022-09-27T08:09:22Z",
        "    \x1b[1mEnd time:\x1b[0m 2022-09-27T08:09:58Z",
        "    \x1b[1mStatus:\x1b[0m \x1b[31merror\x1b[0m (Failed)",
        "    \x1b[1mMessage:\x1b[0m The node was low on resource: memory. Container step-export was using 7804Ki, which exceeds its request of 0. Container step-results was using 6756Ki, which exceeds its request of 0. Container step-build was using 26352Ki, which exceeds its request of 0. ",
        "",
    ]
    expected_json = [
        {
            'task_name': 'build-from-git',
            'start_time': '2022-09-27T08:09:22Z',
            'end_time': '2022-09-27T08:09:58Z',
            'status': 'error',
            'reason': 'Failed',
            'message': 'The node was low on resource: memory. Container step-export was '
                        'using 7804Ki, which exceeds its request of 0. Container '
                        'step-results was using 6756Ki, which exceeds its request of 0. '
                        'Container step-build was using 26352Ki, which exceeds its request '
                        'of 0. ',
        }
    ]

    assert actual_str == expected_str
    assert actual_json == expected_json
