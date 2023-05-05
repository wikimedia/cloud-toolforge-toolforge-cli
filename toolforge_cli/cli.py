#!/usr/bin/env python3
from __future__ import annotations

import json as json_mod
import logging
import os
import subprocess
import sys
import time
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

import click
from tabulate import tabulate

import toolforge_cli.build as toolforge_build
from toolforge_cli.config import Config, load_config
from toolforge_cli.k8sclient import K8sAPIClient, K8sError

LOGGER = logging.getLogger("toolforge" if __name__ == "__main__" else __name__)


@lru_cache(maxsize=None)
def _load_config_from_ctx() -> Config:
    ctx = click.get_current_context()
    return cast(Config, ctx.obj["config"])


@lru_cache(maxsize=None)
def get_loaded_config() -> Config:
    return load_config()


def _get_build_k8s(kubeconfig: Path) -> K8sAPIClient:
    config = _load_config_from_ctx()
    return K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=config.build.build_service_namespace)


def generate_default_image_name() -> str:
    """Get the default project.

    Currently that matches the tool account name, and the unix user, we might want to change the way we detect that
    once we have a public API.
    """
    return f"{toolforge_build.HARBOR_TOOLFORGE_PROJECT_PREFIX}-{Path('~').expanduser().absolute().name}"


def _format_headers(headers: List[str]) -> List[str]:
    return [click.style(item, bold=True) for item in headers]


def _execute_k8s_client_method(method, kwargs: Dict[str, Any]):
    try:
        return method(**kwargs)
    except K8sError as err:
        click.echo(click.style(err.to_str(), fg="red", bold=True))
    sys.exit(1)


def _run_is_ok(status_data: Dict[str, Any]) -> bool:
    return status_data["status"] == "True" or status_data["reason"] == "Running"


def _run_has_failed(status_data: Dict[str, Any]) -> bool:
    return status_data["status"] == "False"


def _get_run_status(status_data: Dict[str, str]) -> str:
    if _run_is_ok(status_data):
        return "ok"
    elif _run_has_failed(status_data):
        if status_data["reason"].endswith("Cancelled"):
            return "cancelled"
        else:
            return "error"
    else:
        return status_data["status"].lower()


def _get_status_data(run: Dict[str, Any]) -> Dict[str, str]:
    info = None
    if "status" in run:
        info = next(
            (info for info in run.get("status", {}).get("conditions", {}) if info.get("type") == "Succeeded"),
            None,
        )

    if info:
        start_time = run["status"]["startTime"]
        end_time = run["status"].get("completionTime", "running")
        status = _get_run_status(info)
        reason = info["reason"]
        message = info["message"]
    else:
        start_time = "pending"
        status = "not started"
        end_time = reason = message = "N/A"

    return {"start_time": start_time, "end_time": end_time, "status": status, "reason": reason, "message": message}


def _get_run_data(run: Dict[str, Any]) -> Dict[str, Any]:
    run_name = run["metadata"]["name"]
    app_image = next(param for param in run["spec"]["params"] if param["name"] == "APP_IMAGE")["value"]
    repo_url, image_name, image_tag = _app_image_to_parts(app_image=app_image)
    builder_image = next(param for param in run["spec"]["params"] if param["name"] == "BUILDER_IMAGE")["value"]
    source_url = next(param for param in run["spec"]["params"] if param["name"] == "SOURCE_URL")["value"]
    ref = next((param for param in run["spec"]["params"] if param["name"] == "SOURCE_REFERENCE"), {"value": "no ref"})[
        "value"
    ]
    status_data = _get_status_data(run=run)
    return {
        "name": run_name,
        **status_data,
        "params": {
            "image_name": image_name,
            "image_tag": image_tag,
            "repo_url": repo_url,
            "source_url": source_url,
            "ref": ref,
            "builder_image": builder_image,
        }
    }


def _run_to_list_entry(run_data: Dict[str, Any]) -> List[Any]:
    status_style = {
        "not started": click.style("not started", fg="white"),
        "ok": click.style("ok", fg="green"),
        "cancelled": click.style("cancelled", fg="green"),
        "error": click.style("error", fg="red"),
    }

    run_name = run_data["name"]
    status_name = run_data["status"]
    status = status_style.get(status_name, click.style(status_name, fg="yellow"))
    params = run_data["params"]
    source_url = params["source_url"]
    ref = params["ref"]
    repo_url = params["repo_url"]
    image_name = params["image_name"]
    builder_image = params["builder_image"]
    image_tag = params["image_tag"]
    start_time = run_data["start_time"]
    end_time = run_data["end_time"]

    return [
        run_name,
        status,
        start_time,
        end_time,
        source_url,
        ref,
        repo_url,
        image_name,
        image_tag,
        builder_image,
    ]


def _get_status_data_lines(status_data: Dict[str, Any]) -> List[str]:
    status_data_lines = []

    start_time = status_data["start_time"]
    end_time = status_data["end_time"]
    status = status_data["status"]
    reason = status_data["reason"]
    message = status_data["message"]

    if status == "ok" or status == "cancelled":
        status_color = "green"
    elif status == "error":
        status_color = "red"
    else:
        status_color = "yellow"

    end_time = click.style(end_time, fg="green") if end_time == "running" else end_time
    status = f"{click.style(status, fg=status_color)} ({reason})"

    status_data_lines.append(f"{click.style('Start time:', bold=True)} {start_time}")
    status_data_lines.append(f"{click.style('End time:', bold=True)} {end_time}")
    status_data_lines.append(f"{click.style('Status:', bold=True)} {status}")
    status_data_lines.append(f"{click.style('Message:', bold=True)} {message}")

    return status_data_lines


def _get_init_containers_details(
    run_name: str, task_name: str, k8s_client: K8sAPIClient
) -> List[Dict[str, Any]]:
    """Sometimes these fail before getting to any of the steps."""
    pod_name = f"{run_name}-{task_name}-pod"
    pod_data = k8s_client.get_object(kind="pods", name=pod_name)
    init_containers = []

    for init_container in pod_data["status"]["initContainerStatuses"]:
        init_container_status_str = "unknown"
        init_container_status = init_container["state"]
        if "terminated" in init_container_status and init_container_status["terminated"]["exitCode"] != 0:
            init_container_status_str = "error"
            reason = f"{init_container_status['terminated']['reason']}:{init_container_status['terminated']['message']}"
        elif "waiting" in init_container_status:
            init_container_status_str = "waiting"
            reason = init_container_status["waiting"].get("reason", "UnknownReason")
        elif "terminated" in init_container_status:
            init_container_status_str = "ok"
            reason = f"{init_container_status['terminated']['reason']}"

        init_containers.append(
            {
                "name": init_container["name"],
                "status": init_container_status_str,
                "reason": reason,
            }
        )

    return init_containers


def _get_init_containers_details_lines(init_containers: List[Dict[str, Any]]) -> List[str]:
    """Sometimes these fail before getting to any of the steps."""
    init_containers_lines = []
    status = {
        "ok": click.style("ok", fg="green"),
        "waiting": click.style("waiting", fg="white"),
        "error": click.style("error", fg="red"),
        "unknown": click.style("unknown", fg="yellow"),
    }
    for init_container in init_containers:
        init_containers_lines.append(
            f"{click.style('Init-container:', bold=True)} {init_container['name']} - "
            f"{status[init_container['status']]} ({init_container['reason']})"
        )

    return init_containers_lines


def _get_step_details(steps) -> List[Dict[str, Any]]:
    steps_details = []
    for step in steps:
        step_status = "unknown"
        reason = step
        if "terminated" in step and step["terminated"]["exitCode"] != 0:
            reason = step["terminated"]["reason"]
            if reason.endswith("Cancelled"):
                step_status = "cancelled"
            else:
                step_status = "error"
        elif "terminated" in step and step["terminated"]["exitCode"] == 0:
            step_status = "ok"
            reason = step["terminated"]["reason"]
        elif "waiting" in step:
            step_status = "waiting"
            reason = step["waiting"].get("reason", "UnknownReason")
        elif "running" in step:
            step_status = "running"
            reason = f"started at [{step['running'].get('startedAt', 'unknown')}]"

        steps_details.append({"name": step["name"], "status": step_status, "reason": reason})

    return steps_details


def _get_step_details_lines(steps: List[Dict[str, Any]]) -> List[str]:
    steps_details_lines = []
    status = {
        "ok": click.style("ok", fg="green"),
        "waiting": click.style("waiting", fg="white"),
        "running": click.style("running", fg="white"),
        "cancelled": click.style("cancelled", fg="green"),
        "error": click.style("error", fg="red"),
        "unknown": click.style("unknown", fg="yellow"),
    }

    for step in steps:
        steps_details_lines.append(
            f"{click.style('Step:', bold=True)} {step['name']} - {status[step['status']]} ({step['reason']})"
        )

    return steps_details_lines


def _get_task_details(run: Dict[str, Any], k8s_client: K8sAPIClient) -> List[Dict[str, Any]]:
    tasks_details = []

    for task in run.get("status", {}).get("taskRuns", {}).values():
        status_data = _get_status_data(run=task)

        task_details = {
            "task_name": task["pipelineTaskName"],
            **status_data
        }

        # A task can fail before any steps are executed
        if "steps" in task["status"]:
            steps_details = _get_step_details(steps=task["status"]["steps"])
            task_details["steps"] = steps_details

            if status_data["status"] in ["cancelled", "error"] and all(
                "waiting" in step for step in task["status"]["steps"]
            ):
                # Sometimes the task fails in the init containers, so if that happened, show the errors there too
                init_containers = _get_init_containers_details(
                        run_name=run["metadata"]["name"], task_name=task["pipelineTaskName"], k8s_client=k8s_client
                    )
                task_details["init_containers"] = init_containers
        tasks_details.append(task_details)

    return tasks_details


def _get_task_details_lines(tasks_details: List[Dict[str, Any]]) -> List[str]:
    tasks_details_lines = []

    for task in tasks_details:
        tasks_details_lines.append(f"{click.style('Task:', bold=True)} {task['task_name']}")
        tasks_details_lines.extend("    " + line for line in _get_status_data_lines(status_data=task))
        tasks_details_lines.append("")

        # A task can fail before any steps are executed
        if "steps" in task:
            steps_details_lines = _get_step_details_lines(steps=task["steps"])

            tasks_details_lines.append(click.style("    Steps:", bold=True))
            tasks_details_lines.extend("        " + line for line in steps_details_lines)
            tasks_details_lines.append("")

        if "init_containers" in task:
            # Sometimes the task fails in the init containers, so if that happened, show the errors there too
            init_containers_lines = _get_init_containers_details_lines(init_containers=task["init_containers"])
            tasks_details_lines.append(click.style("    Init containers:", bold=True))
            tasks_details_lines.extend(
                "        " + line
                for line in init_containers_lines
            )

    return tasks_details_lines


def _run_to_details(run: Dict[str, Any], k8s_client: K8sAPIClient, verbose: bool) -> Dict[str, Any]:
    run_details = _get_run_data(run=run)
    if verbose:
        run_details["tasks"] = _get_task_details(run=run, k8s_client=k8s_client)
    return run_details


def _run_to_details_str(run_details: Dict[str, Any]) -> str:
    status_data_lines = _get_status_data_lines(status_data=run_details)
    details_str = ""
    details_str += f"{click.style('Name:', bold=True)} {click.style(run_details['name'], fg='blue')}\n"
    details_str += "\n".join(status_data_lines) + "\n"
    details_str += click.style("Parameters:\n", bold=True)
    details_str += f"    {click.style('source_url:', bold=True)} {run_details['params']['source_url']}\n"
    details_str += f"    {click.style('ref:', bold=True)} {run_details['params']['ref']}\n"
    details_str += f"    {click.style('image_name:', bold=True)} {run_details['params']['image_name']}\n"
    details_str += f"    {click.style('image_tag:', bold=True)} {run_details['params']['image_tag']}\n"
    details_str += f"    {click.style('repo_url:', bold=True)} {run_details['params']['repo_url']}\n"
    details_str += f"    {click.style('builder_image:', bold=True)} {run_details['params']['builder_image']}\n"

    if "tasks" in run_details:
        tasks_details_lines = _get_task_details_lines(tasks_details=run_details["tasks"])

        details_str += click.style("Tasks:\n", bold=True)
        details_str += "\n".join("    " + line for line in tasks_details_lines)

    return details_str


def _app_image_to_parts(app_image: str) -> Tuple[str, str, str]:
    tag = app_image.rsplit(":", 1)[-1]
    image_name = app_image.rsplit("/", 1)[-1].split(":", 1)[0]
    repo = app_image.rsplit("/", 1)[0]
    return (repo, image_name, tag)


def _run_external_command(*args, binary: str, verbose: bool = False, debug: bool = False) -> None:
    env = os.environ.copy()
    cmd = [binary, *args]
    env["TOOLFORGE_CLI"] = "1"
    env["TOOLFORGE_VERBOSE"] = "1" if verbose else "0"
    env["TOOLFORGE_DEBUG"] = "1" if debug else "0"

    LOGGER.debug(f"Running command: {cmd}")
    proc = subprocess.Popen(
        args=cmd, bufsize=0, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, shell=False, env=env
    )
    returncode = proc.poll()
    while returncode is None:
        time.sleep(0.1)
        returncode = proc.poll()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(returncode=proc.returncode, output=None, stderr=None, cmd=cmd)


def _add_discovered_subcommands(cli: click.Group, config: Config) -> click.Group:
    bins_path = os.environ.get("PATH", ".")
    subcommands: Dict[str, Path] = {}
    LOGGER.debug("Looking for subcommands...")
    for dir_str in reversed(bins_path.split(":")):
        dir_path = Path(dir_str)
        LOGGER.debug(f"Checking under {dir_path}...")
        for command in dir_path.glob(f"{config.toolforge_prefix}*"):
            LOGGER.debug(f"Checking {command}...")
            if command.is_file() and os.access(command, os.X_OK):
                subcommand_name = command.name[len(config.toolforge_prefix) :]
                subcommands[subcommand_name] = command

    LOGGER.debug(f"Found {len(subcommands)} subcommands.")
    for name, binary in subcommands.items():
        bin_path = str(binary.resolve())

        @cli.command(
            name=name,
            context_settings=dict(
                ignore_unknown_options=True,
            ),
        )
        @click.option("--help", is_flag=True, default=False)
        @click.argument("args", nargs=-1, type=click.UNPROCESSED)
        @click.pass_context
        def _new_command(ctx, args, help: bool, bin_path: str = bin_path):  # noqa
            verbose = ctx.obj.get("verbose", False)
            debug = ctx.obj.get("debug", False)
            if help:
                args = ["--help"] + list(args)
            _run_external_command(*args, verbose=verbose, debug=debug, binary=bin_path)

    return cli


def shared_build_options(func: Callable) -> Callable:
    @click.option(
        "--kubeconfig",
        hidden=True,
        default=Path(os.environ.get("KUBECONFIG", "~/.kube/config")),
        type=Path,
    )
    @wraps(func)
    def wrapper(*args, **kwargs) -> Callable:
        return func(*args, **kwargs)

    return wrapper


@click.version_option(prog_name="Toolforge CLI")
@click.group(name="toolforge", help="Toolforge command line")
@click.option(
    "-v",
    "--verbose",
    help="Show extra verbose output. NOTE: Do no rely on the format of the verbose output",
    is_flag=True
)
@click.option(
    "-d",
    "--debug",
    help="show logs to debug the toolforge-* packages. For extra verbose output for say build or job, see --verbose",
    is_flag=True
)
@click.pass_context
def toolforge(ctx: click.Context, verbose: bool, debug: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug
    ctx.obj["config"] = get_loaded_config()
    pass


@toolforge.group(name="build", help="Build your project from source code")
def build():
    pass


@build.command(name="start", help="Start a pipeline to build a container image from source code")
@click.argument("SOURCE_GIT_URL", required=False)
@click.option(
    "-n",
    "--image-name",
    help="Image identifier for the builder that will be used to build the project (ex. python)",
    default=generate_default_image_name(),
    show_default=True,
)
@click.option(
    "-t",
    "--image-tag",
    help="Tag to tag the generated image with",
    default="latest",
    show_default=True,
)
@click.option(
    "--builder-image",
    default=get_loaded_config().build.builder_image,
    hidden=True,
)
@click.option(
    "--dest-repository",
    default=get_loaded_config().build.dest_repository,
    hidden=True,
)
@click.option(
    "--ref",
    help="Branch, tag or commit to build, by default will use the HEAD of the given repository.",
    show_default=True,
)
@shared_build_options
def build_start(
    dest_repository: str,
    source_git_url: str,
    image_name: str,
    image_tag: str,
    builder_image: str,
    kubeconfig: Path,
    ref: Optional[str] = None,
) -> None:
    if not source_git_url:
        message = (
            f"{click.style('Error:', bold=True, fg='red')} Please provide a git url for your source code.\n"
            + f"{click.style('Example:', bold=True)}"
            + " toolforge build start 'https://gitlab.wikimedia.org/toolforge-repos/my-tool'"
        )
        click.echo(message)
        return

    k8s_client = _get_build_k8s(kubeconfig=kubeconfig)
    app_image = toolforge_build.get_app_image_url(
        image_name=image_name,
        image_tag=image_tag,
        image_repository=dest_repository,
        user=k8s_client.user,
    )
    pipeline_run_spec = toolforge_build.get_pipeline_run_spec(
        source_url=source_git_url,
        builder_image=builder_image,
        app_image=app_image,
        username=k8s_client.user,
        ref=ref,
    )

    method_kwargs = {"kind": "pipelineruns", "spec": pipeline_run_spec}
    response = _execute_k8s_client_method(method=k8s_client.create_object, kwargs=method_kwargs)
    run_name = response["metadata"]["name"]
    message = (
        f"Building '{source_git_url}' -> '{app_image}'\n"
        + f"You can see the status with:\n\ttoolforge build show '{run_name}'"
    )
    click.echo(message)


@build.command(name="logs", help="Show the logs for a build (only admins for now)")
@click.argument("RUN_NAME")
@shared_build_options
def build_logs(run_name: str, kubeconfig: Path) -> None:
    config = _load_config_from_ctx()
    k8s_client = _get_build_k8s(kubeconfig=kubeconfig)

    if k8s_client.org_name in config.build.admin_group_names:
        click.echo(
            click.style(
                "This feature is not yet available for non-admin users, but will be soon!",
                fg="yellow",
                bold=True,
            ),
        )
        return

    _run_external_command(
        "pipelinerun", "logs", "--namespace", config.build.build_service_namespace, "-f", run_name, binary="tkn"
    )


@build.command(name="list", help="List builds")
@click.option(
    "--json",
    help="If set, will output in json format",
    is_flag=True,
)
@shared_build_options
def build_list(kubeconfig: Path, json: bool) -> None:
    k8s_client = _get_build_k8s(kubeconfig=kubeconfig)
    method_kwargs = {"kind": "pipelineruns", "selector": f"user={k8s_client.user}"}
    runs = _execute_k8s_client_method(method=k8s_client.get_objects, kwargs=method_kwargs)

    run_datas = [
        _get_run_data(run=run)
        for run in sorted(runs, key=lambda run: run["metadata"]["creationTimestamp"], reverse=True)
    ]

    if json:
        for run_data in run_datas:
            click.echo(json_mod.dumps(run_data, indent=4))
        return

    click.echo(
        tabulate(
            [_run_to_list_entry(run_data=run_data) for run_data in run_datas],
            headers=_format_headers([
                "run_image",
                "status",
                "start_time",
                "end_time",
                "source_url",
                "ref",
                "repo_url",
                "image_name",
                "image_tag",
                "builder_image",
            ]),
            tablefmt="plain",
        )
    )


@build.command(name="cancel", help="Cancel a running build (does nothing for stopped ones)")
@click.option(
    "--all",
    help="Cancel all the current builds.",
    is_flag=True,
)
@click.option(
    "--yes-i-know",
    "-y",
    help="Don't ask for confirmation.",
    is_flag=True,
)
@click.argument(
    "build_name",
    nargs=-1,
)
@shared_build_options
def build_cancel(kubeconfig: Path, build_name: List[str], all: bool, yes_i_know: bool) -> None:
    if not build_name and not all:
        click.echo("No run passed to cancel.")
        return

    k8s_client = _get_build_k8s(kubeconfig=kubeconfig)
    kwargs = {"kind": "pipelineruns", "selector": f"user={k8s_client.user}"}
    all_user_runs = _execute_k8s_client_method(k8s_client.get_objects, kwargs)

    runs_to_cancel = []
    for run in all_user_runs:
        if run["metadata"]["name"] in build_name or all:
            runs_to_cancel.append(run)

    if len(runs_to_cancel) == 0:
        click.echo("No runs to cancel, maybe there was a typo? (try listing them with toolforge build list)")
        return

    if not yes_i_know:
        click.confirm(f"I'm going to cancel {len(runs_to_cancel)} runs, continue?", abort=True)

    runs_to_cancel_count = len(runs_to_cancel)
    for run in runs_to_cancel:
        # see https://tekton.dev/docs/pipelines/pipelineruns/#cancelling-a-pipelinerun
        run_kwargs = {
            "kind": "pipelineruns",
            "name": run["metadata"]["name"],
            "json_patches": [{"op": "add", "path": "/spec/status", "value": "PipelineRunCancelled"}],
        }
        # We rely on patch never returning some kind of error dictionary when canceling the
        # pipelinerun no matter it's state, this might change in the future
        result = _execute_k8s_client_method(k8s_client.patch_object, run_kwargs)
        status_data = _get_status_data(run=result)
        if status_data["reason"].lower() in ["failed", "succeeded"]:
            click.echo(
                click.style(
                    f"{result['metadata']['name']} cannot be cancelled because it has already completed",
                    fg="yellow",
                    bold=True,
                )
            )
            runs_to_cancel_count -= 1
        elif status_data["reason"].lower() == "pipelineruncancelled":
            click.echo(
                click.style(
                    f"{result['metadata']['name']} cannot be cancelled again. It has already been cancelled",
                    fg="yellow",
                    bold=True,
                )
            )
            runs_to_cancel_count -= 1
    click.echo(f"Cancelled {runs_to_cancel_count} runs")


@build.command(name="delete", help="Delete a build (only admins for now)")
@click.option(
    "--all",
    help="Delete all the current builds",
    is_flag=True,
)
@click.option(
    "--yes-i-know",
    "-y",
    help="Don't ask for confirmation",
    is_flag=True,
)
@click.argument(
    "build_name",
    nargs=-1,
)
@shared_build_options
def build_delete(kubeconfig: Path, build_name: List[str], all: bool, yes_i_know: bool) -> None:
    if not build_name and not all:
        click.echo("No run passed to delete")
        return

    k8s_client = _get_build_k8s(kubeconfig=kubeconfig)
    method_kwargs = {"kind": "pipelineruns", "selector": f"user={k8s_client.user}"}
    all_user_runs = _execute_k8s_client_method(method=k8s_client.get_objects, kwargs=method_kwargs)

    runs_to_delete = []
    for run in all_user_runs:
        if run["metadata"]["name"] in build_name or all:
            runs_to_delete.append(run)

    if len(runs_to_delete) == 0:
        click.echo("No runs to delete, maybe there was a typo? (try listing them with toolforge build list)")
        return

    if not yes_i_know:
        click.confirm(f"I'm going to delete {len(runs_to_delete)} runs, continue?", abort=True)

    for run in runs_to_delete:
        k8s_client.delete_object(kind="pipelineruns", name=run["metadata"]["name"])
        # only admins can do this
        k8s_client.delete_objects(kind="pods", selector=f"tekton.dev/pipelineRun={run['metadata']['name']}")
    click.echo(f"Deleted {len(runs_to_delete)} runs.")


@build.command(name="show", help="Show details for a specific build")
@click.argument("RUN_NAME", required=False)
@click.option(
    "--json",
    help="If set, will output in json format",
    is_flag=True,
)
@shared_build_options
@click.pass_context
def build_show(ctx, run_name: str, kubeconfig: Path, json: bool) -> None:
    verbose = ctx.obj.get("verbose", False)
    k8s_client = _get_build_k8s(kubeconfig=kubeconfig)
    method_kwargs = {"kind": "pipelineruns"}
    if run_name:
        method_kwargs["name"] = run_name
        raw_run = _execute_k8s_client_method(method=k8s_client.get_object, kwargs=method_kwargs)
    else:
        method_kwargs["selector"] = f"user={k8s_client.user}"
        raw_runs = _execute_k8s_client_method(method=k8s_client.get_objects, kwargs=method_kwargs)
        raw_runs = sorted(raw_runs, key=lambda raw_run: raw_run["metadata"]["creationTimestamp"], reverse=True)
        raw_run = raw_runs[0] if len(raw_runs) > 0 else None

    if not raw_run:
        click.echo(
            click.style(
                (
                    "No builds found, you can start one using `toolforge build start`,"
                    + "run `toolforge build start --help` for more details"
                ),
                fg="yellow",
            )
        )
        return

    run_details = _run_to_details(run=raw_run, k8s_client=k8s_client, verbose=verbose)
    if not json:
        click.echo(_run_to_details_str(run_details=run_details))
    else:
        click.echo(
            json_mod.dumps(
                run_details,
                indent=4,
            )
        )


@toolforge.command(name="_commands", hidden=True)
def internal_commands():
    """Used internally for tab completion."""
    for name, command in sorted(toolforge.commands.items()):
        if command.hidden:
            continue
        click.echo(name)


def main() -> int:
    # this is needed to setup the logging before the subcommand discovery
    res = toolforge.parse_args(ctx=click.Context(command=toolforge), args=sys.argv)
    if "-d" in res or "--debug" in res:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    config = get_loaded_config()
    _add_discovered_subcommands(cli=toolforge, config=config)
    try:
        toolforge()
    except subprocess.CalledProcessError as err:
        return err.returncode

    return 0


if __name__ == "__main__":
    main()
