#!/usr/bin/env python3
import json as json_mod
import logging
import os
import subprocess
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import click
from requests.exceptions import ConnectionError, HTTPError

import toolforge_cli.build as toolforge_build
from toolforge_cli.k8sclient import K8sAPIClient

TOOLFORGE_PREFIX = "toolforge-"
TBS_NAMESPACE = "image-build"
ADMIN_GROUP_NAMES = ["admins", "system:masters"]
LOGGER = logging.getLogger("toolforge" if __name__ == "__main__" else __name__)


def _execute_k8s_client_method(method, kwargs: Dict[str, Any]):
    try:
        return method(**kwargs)
    except ConnectionError:
        click.echo(click.style(toolforge_build.ERROR_STRINGS["SERVICE_DOWN_ERROR"], fg="red", bold=True))
    except HTTPError:
        click.echo(click.style(toolforge_build.ERROR_STRINGS["UNKOWN_ERROR"], fg="red", bold=True))
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
    status_data = _get_status_data(run)
    start_time = status_data["start_time"]
    end_time = status_data["end_time"]
    status = status_data["status"]

    return {
        "name": run_name,
        "params": {
            "image_name": image_name,
            "image_tag": image_tag,
            "repo_url": repo_url,
            "source_url": source_url,
            "ref": ref,
            "builder_image": builder_image,
        },
        "start_time": start_time,
        "end_time": end_time,
        "status": status,
    }


def _run_to_short_str(run_data: Dict[str, Any]) -> str:
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

    return (
        f"{run_name}\t{status}\t{start_time}\t{end_time}\t{source_url}\t{ref}\t{repo_url}\t{image_name}"
        f"\t{image_tag}\t{builder_image}"
    )


def _get_status_data_lines(k8s_obj: Dict[str, Any]) -> List[str]:
    status_data_lines = []
    status_data = _get_status_data(k8s_obj)

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
    status = f"{click.style(status, fg=status_color)}({reason})"

    status_data_lines.append(f"{click.style('Start time:', bold=True)} {start_time}")
    status_data_lines.append(f"{click.style('End time:', bold=True)} {end_time}")
    status_data_lines.append(f"{click.style('Status:', bold=True)} {status}")
    status_data_lines.append(f"{click.style('Message:', bold=True)} {message}")

    return status_data_lines


def _get_init_containers_details(run_name: str, task_name: str, k8s_client: K8sAPIClient) -> List[str]:
    """Sometimes these fail before getting to any of the steps."""
    pod_name = f"{run_name}-{task_name}-pod"
    pod_data = k8s_client.get_object(kind="pods", name=pod_name)
    init_containers_lines = []
    for init_container in pod_data["status"]["initContainerStatuses"]:
        init_container_status_str = click.style("unknown", fg="yellow")
        init_container_status = init_container["state"]
        if "terminated" in init_container_status and init_container_status["terminated"]["exitCode"] != 0:
            init_container_status_str = click.style("error", fg="red")
            reason = f"{init_container_status['terminated']['reason']}:{init_container_status['terminated']['message']}"
        elif "waiting" in init_container_status:
            init_container_status_str = click.style("waiting", fg="white")
            reason = init_container_status["waiting"].get("reason", "UnownReason")
        elif "terminated" in init_container_status:
            init_container_status_str = click.style("ok", fg="green")
            reason = f"{init_container_status['terminated']['reason']}"

        init_containers_lines.append(
            f"{click.style('Init-container:', bold=True)} {init_container['name']} - "
            f"{init_container_status_str}({reason})"
        )

    return init_containers_lines


def _get_step_details_lines(task: Dict[str, Any]) -> List[str]:
    steps_details_lines = []
    status = {
        "ok": click.style("ok", fg="green"),
        "waiting": click.style("waiting", fg="white"),
        "running": click.style("running", fg="white"),
        "cancelled": click.style("cancelled", fg="green"),
        "error": click.style("error", fg="red"),
        "unknown": click.style("unknown", fg="yellow"),
    }

    for step in task["status"]["steps"]:
        step_status = status["unknown"]
        reason = step
        if "terminated" in step and step["terminated"]["exitCode"] != 0:
            reason = step["terminated"]["reason"]
            if reason.endswith("Cancelled"):
                step_status = status["cancelled"]
            else:
                step_status = status["error"]
        elif "terminated" in step and step["terminated"]["exitCode"] == 0:
            step_status = status["ok"]
            reason = step["terminated"]["reason"]
        elif "waiting" in step:
            step_status = status["waiting"]
            reason = step["waiting"].get("reason", "UnknownReason")
        elif "running" in step:
            step_status = status["running"]
            reason = f"started at [{step['running'].get('startedAt', 'unknown')}]"

        steps_details_lines.append(f"{click.style('Step:', bold=True)} {step['name']} - {step_status}({reason})")

    return steps_details_lines


def _get_task_details_lines(run: Dict[str, Any], k8s_client: K8sAPIClient) -> List[str]:
    tasks_details_lines = []

    for task in run.get("status", {}).get("taskRuns", {}).values():
        tasks_details_lines.append(f"{click.style('Task:', bold=True)} {task['pipelineTaskName']}")
        tasks_details_lines.extend("    " + line for line in _get_status_data_lines(k8s_obj=task))
        tasks_details_lines.append("")

        # A task can fail before any steps are executed
        if "steps" in task["status"]:
            tasks_details_lines.append(click.style("    Steps:", bold=True))
            tasks_details_lines.extend("        " + line for line in _get_step_details_lines(task=task))
            tasks_details_lines.append("")

            status_data = _get_status_data(task)
            if status_data["status"] in ["cancelled", "error"] and all(
                "waiting" in step for step in task["status"]["steps"]
            ):
                # Sometimes the task fails in the init containers, so if that happened, show the errors there too
                tasks_details_lines.append(click.style("    Init containers:", bold=True))
                tasks_details_lines.extend(
                    "        " + line
                    for line in _get_init_containers_details(
                        run_name=run["metadata"]["name"], task_name=task["pipelineTaskName"], k8s_client=k8s_client
                    )
                )

    return tasks_details_lines


def _run_to_details_str(run: Dict[str, Any], k8s_client: K8sAPIClient) -> str:
    details_str = ""
    run_name = run["metadata"]["name"]
    details_str += f"{click.style('Name:', bold=True)} {click.style(run_name, fg='blue')}\n"

    details_str += "\n".join(_get_status_data_lines(k8s_obj=run)) + "\n"

    app_image = next(param for param in run["spec"]["params"] if param["name"] == "APP_IMAGE")["value"]
    repo_url, image_name, image_tag = _app_image_to_parts(app_image)
    builder_image = next(param for param in run["spec"]["params"] if param["name"] == "BUILDER_IMAGE")["value"]
    source_url = next(param for param in run["spec"]["params"] if param["name"] == "SOURCE_URL")["value"]
    ref = next((param for param in run["spec"]["params"] if param["name"] == "SOURCE_REFERENCE"), {"value": "no ref"})[
        "value"
    ]
    details_str += click.style("Parameters:\n", bold=True)
    details_str += f"    {click.style('source_url:', bold=True)} {source_url}\n"
    details_str += f"    {click.style('ref:', bold=True)} {ref}\n"
    details_str += f"    {click.style('image_name:', bold=True)} {image_name}\n"
    details_str += f"    {click.style('image_tag:', bold=True)} {image_tag}\n"
    details_str += f"    {click.style('repo_url:', bold=True)} {repo_url}\n"
    details_str += f"    {click.style('builder_image:', bold=True)} {builder_image}\n"

    details_str += click.style("Tasks:\n", bold=True)
    details_str += "\n".join("    " + line for line in _get_task_details_lines(run=run, k8s_client=k8s_client))

    return details_str


def _app_image_to_parts(app_image: str) -> Tuple[str, str, str]:
    tag = app_image.rsplit(":", 1)[-1]
    image_name = app_image.rsplit("/", 1)[-1].split(":", 1)[0]
    repo = app_image.rsplit("/", 1)[0]
    return (repo, image_name, tag)


def _run_external_command(*args, binary: str, verbose: bool = False) -> None:
    env = os.environ.copy()
    cmd = [binary, *args]
    env["TOOLFORGE_DEBUG"] = "1" if verbose else "0"

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


def _add_discovered_subcommands(cli: click.Group) -> click.Group:
    bins_path = os.environ.get("PATH", ".")
    subcommands: Dict[str, Path] = {}
    LOGGER.debug("Looking for subcommands...")
    for dir_str in reversed(bins_path.split(":")):
        dir_path = Path(dir_str)
        LOGGER.debug(f"Checking under {dir_path}...")
        for command in dir_path.glob(f"{TOOLFORGE_PREFIX}*"):
            LOGGER.debug(f"Checking {command}...")
            if command.is_file() and os.access(command, os.X_OK):
                subcommand_name = command.name[len(TOOLFORGE_PREFIX) :]
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
            if help:
                args = ["--help"] + list(args)
            _run_external_command(*args, verbose=verbose, binary=bin_path)

    return cli


def shared_build_options(func: Callable) -> Callable:
    @click.option(
        "--kubeconfig",
        help="Path to the kubeconfig file.",
        default=Path(os.environ.get("KUBECONFIG", "~/.kube/config")),
        type=Path,
        show_default=True,
    )
    @wraps(func)
    def wrapper(*args, **kwargs) -> Callable:
        return func(*args, **kwargs)

    return wrapper


def generate_default_image_name() -> str:
    """Get the default project.

    Currently that matches the tool account name, and the unix user, we might want to change the way we detect that
    once we have a public API.
    """
    return Path("~").expanduser().absolute().name


@click.version_option()
@click.group(name="toolforge", help="Toolforge command line")
@click.option("-v", "--verbose", help="Show extra verbose output", is_flag=True)
@click.pass_context
def toolforge(ctx: click.Context, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
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
    help="This is the image identifier for the buildpack builder, without protocol (no http/https)",
    default="docker-registry.tools.wmflabs.org/toolforge-bullseye0-builder:latest",
    show_default=True,
)
@click.option(
    "--dest-repository",
    help="FQDN to the OCI repository to push the image to, without the protocol (no http/https)",
    default="harbor.tools.wmflabs.org",
    show_default=True,
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
        message = (f"{click.style('Error:', bold=True, fg='red')} Please provide a git url for your source code.\n" +
                   f"{click.style('Example:', bold=True)}" +
                   " toolforge build start 'https://gitlab.wikimedia.org/toolforge-repos/my-tool'")
        click.echo(message)
        return

    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    app_image = toolforge_build.get_app_image_url(
        image_name=image_name, image_tag=image_tag, image_repository=dest_repository, user=k8s_client.user
    )
    pipeline_run_spec = toolforge_build.get_pipeline_run_spec(
        source_url=source_git_url,
        builder_image=builder_image,
        app_image=app_image,
        username=k8s_client.user,
        ref=ref,
    )

    method_kwargs = {
        "kind": "pipelineruns",
        "spec": pipeline_run_spec
    }
    response = _execute_k8s_client_method(method=k8s_client.create_object, kwargs=method_kwargs)
    run_name = response["metadata"]["name"]
    message = (
        f"Building '{source_git_url}' -> '{app_image}'\n" +
        f"You can see the status with:\n\ttoolforge build show '{run_name}'"
    )
    click.echo(message)


@build.command(name="logs", help="Show the logs for a build (only admins for now)")
@click.argument("RUN_NAME")
@shared_build_options
def build_logs(run_name: str, kubeconfig: Path) -> None:
    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)

    if k8s_client.org_name in ADMIN_GROUP_NAMES:
        click.echo(
            click.style(
                "This feature is not yet available for non-admin users, but will be soon!",
                fg="yellow",
                bold=True,
            ),
        )
        return

    _run_external_command("pipelinerun", "logs", "--namespace", TBS_NAMESPACE, "-f", run_name, binary="tkn")


@build.command(name="list", help="List builds")
@click.option(
    "--json",
    help="If set, will output in json format",
    is_flag=True,
)
@shared_build_options
def build_list(kubeconfig: Path, json: bool) -> None:
    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    method_kwargs = {
        "kind": "pipelineruns",
        "selector": f"user={k8s_client.user}"
    }
    runs = _execute_k8s_client_method(method=k8s_client.get_objects, kwargs=method_kwargs)

    if not json:
        click.echo(
            click.style(
                (
                    "run_name\tstatus\tstart_time\tend_time\tsource_url\tref\trepo_url\timage_name\timage_tag"
                    "\tbuilder_image"
                ),
                bold=True,
            ),
        )

    for run in sorted(runs, key=lambda run: run["metadata"]["creationTimestamp"], reverse=True):
        run_data = _get_run_data(run)
        if json:
            click.echo(json_mod.dumps(run_data, indent=4))
        else:
            click.echo(_run_to_short_str(run_data))


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

    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    kwargs = {
        "kind": "pipelineruns",
        "selector": f"user={k8s_client.user}"
    }
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

    for run in runs_to_cancel:
        # see https://tekton.dev/docs/pipelines/pipelineruns/#cancelling-a-pipelinerun
        run_kwargs = {
            "kind": "pipelineruns",
            "name": run["metadata"]["name"],
            "json_patches": [{"op": "add", "path": "/spec/status", "value": "PipelineRunCancelled"}]
        }
        _execute_k8s_client_method(k8s_client.patch_object, run_kwargs)

    click.echo(f"Cancelled {len(runs_to_cancel)} runs")


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

    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    method_kwargs = {
        "kind": "pipelineruns",
        "selector": f"user={k8s_client.user}"
    }
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
def build_show(run_name: str, kubeconfig: Path, json: bool) -> None:
    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    method_kwargs = {
        "kind": "pipelineruns"
    }
    if run_name:
        method_kwargs["name"] = run_name
        run = _execute_k8s_client_method(method=k8s_client.get_object, kwargs=method_kwargs)
    else:
        method_kwargs["selector"] = f"user={k8s_client.user}"
        runs = _execute_k8s_client_method(method=k8s_client.get_objects, kwargs=method_kwargs)
        runs = sorted(runs, key=lambda run: run["metadata"]["creationTimestamp"], reverse=True)
        run = runs[0] if len(runs) > 0 else None

    if not run:
        click.echo(click.style(
            (
                "No builds found, you can start one using `toolforge build start`," +
                "run `toolforge build start --help` for more details"
            ),
            fg="yellow"
        ))
        return

    app_image = next(param for param in run["spec"]["params"] if param["name"] == "APP_IMAGE")["value"]
    repo_url, image_name, image_tag = _app_image_to_parts(app_image=app_image)
    status_data = _get_status_data(run)
    if not json:
        click.echo(_run_to_details_str(run=run, k8s_client=k8s_client))
    else:
        click.echo(
            json_mod.dumps(
                {
                    "name": run["metadata"]["name"],
                    "params": {
                        "image_name": image_name,
                        "image_tag": image_tag,
                        "repo_url": repo_url,
                    },
                    "status": {
                        "succeeded": status_data["status"],
                        "message": status_data["message"],
                        "reason": status_data["reason"],
                    },
                },
                indent=4,
            )
        )


def main() -> int:
    # this is needed to setup the logging before the subcommand discovery
    res = toolforge.parse_args(ctx=click.Context(command=toolforge), args=sys.argv)
    if "-v" in res or "--verbose" in res:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    _add_discovered_subcommands(cli=toolforge)
    try:
        toolforge()
    except subprocess.CalledProcessError as err:
        return err.returncode

    return 0


if __name__ == "__main__":
    main()
