#!/usr/bin/env python3
import json as json_mod
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import click

from toolforge_cli.build import get_app_image_url, get_pipeline_run_spec
from toolforge_cli.k8sclient import K8sAPIClient

TOOLFORGE_PREFIX = "toolforge-"
TBS_NAMESPACE = "image-build"
LOGGER = logging.getLogger("toolforge" if __name__ == "__main__" else __name__)


def _run_is_ok(status_data: Dict[str, Any]) -> bool:
    return status_data["status"] == "True" or status_data["reason"] == "Running"


def _run_has_failed(status_data: Dict[str, Any]) -> bool:
    return status_data["status"] == "False"


def _run_to_short_str(run: Dict[str, Any]) -> str:
    status_data = next(condition for condition in run["status"]["conditions"] if condition["type"] == "Succeeded")
    if _run_is_ok(status_data):
        status_color = "green"
        status_name = "ok"
    elif _run_has_failed(status_data):
        if status_data["reason"].endswith("Cancelled"):
            status_color = "green"
            status_name = "cancelled"
        else:
            status_color = "red"
            status_name = "error"
    else:
        status_color = "yellow"
        status_name = status_data["status"].lower()

    status = click.style(status_name, fg=status_color)
    run_name = run["metadata"]["name"]
    start_time = run["status"]["startTime"]
    end_time = run["status"].get("completionTime", click.style("running", fg="green"))
    app_image = next(param for param in run["spec"]["params"] if param["name"] == "APP_IMAGE")["value"]
    repo_url, image_name, image_tag = _app_image_to_parts(app_image)
    builder_image = next(param for param in run["spec"]["params"] if param["name"] == "BUILDER_IMAGE")["value"]
    source_url = next(param for param in run["spec"]["params"] if param["name"] == "SOURCE_URL")["value"]
    return f"{run_name}\t{status}\t{start_time}\t{end_time}\t{source_url}\t{repo_url}\t{image_name}\t{image_tag}\t{builder_image}"


def _get_status_data_lines(k8s_obj: Dict[str, Any]) -> List[str]:
    status_data_lines = []
    status_data = next(condition for condition in k8s_obj["status"]["conditions"] if condition["type"] == "Succeeded")
    start_time = k8s_obj["status"]["startTime"]
    status_data_lines.append(f"{click.style('Start time:', bold=True)} {start_time}")
    end_time = k8s_obj["status"].get("completionTime", click.style("running", fg="green"))
    status_data_lines.append(f"{click.style('End time:', bold=True)} {end_time}")

    if _run_is_ok(status_data):
        status_color = "green"
        status_name = "ok"
    elif _run_has_failed(status_data):
        if status_data["reason"].endswith("Cancelled"):
            status_color = "green"
            status_name = "cancelled"
        else:
            status_color = "red"
            status_name = "error"
    else:
        status_color = "yellow"
        status_name = status_data["status"].lower()

    status = f"{click.style(status_name, fg=status_color)}({status_data['reason']})"
    status_data_lines.append(f"{click.style('Status:', bold=True)} {status}")
    status_data_lines.append(f"{click.style('Message:', bold=True)} {status_data['message']}")

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
            f"{click.style('Init-container:', bold=True)} {init_container['name']} - {init_container_status_str}({reason})"
        )

    return init_containers_lines


def _get_step_details_lines(task: Dict[str, Any]) -> List[str]:
    steps_details_lines = []
    for step in task["status"]["steps"]:
        step_status = click.style("unknown", fg="yellow")
        reason = step
        if "terminated" in step and step["terminated"]["exitCode"] != 0:
            reason = step["terminated"]["reason"]
            if reason.endswith("Cancelled"):
                step_status = click.style("cancelled", fg="green")
            else:
                step_status = click.style("error", fg="red")
        elif "terminated" in step and step["terminated"]["exitCode"] == 0:
            step_status = click.style("ok", fg="green")
            reason = step["terminated"]["reason"]
        elif "waiting" in step:
            step_status = click.style("waiting", fg="white")
            reason = step["waiting"].get("reason", "UnownReason")
        elif "running" in step:
            step_status = click.style("running", fg="white")
            reason = f"started at [{step['running'].get('startedAt', 'unknown')}]"

        steps_details_lines.append(f"{click.style('Step:', bold=True)} {step['name']} - {step_status}({reason})")

    return steps_details_lines


def _get_task_details_lines(run: Dict[str, Any], k8s_client: K8sAPIClient) -> List[str]:
    tasks_details_lines = []
    for task in run["status"]["taskRuns"].values():
        tasks_details_lines.append(f"{click.style('Task:', bold=True)} {task['pipelineTaskName']}")
        tasks_details_lines.extend("    " + line for line in _get_status_data_lines(k8s_obj=task))
        tasks_details_lines.append("")
        tasks_details_lines.append(click.style("    Steps:", bold=True))
        tasks_details_lines.extend("        " + line for line in _get_step_details_lines(task=task))
        tasks_details_lines.append("")

        status_data = next(condition for condition in task["status"]["conditions"] if condition["type"] == "Succeeded")
        if _run_has_failed(status_data) and all("waiting" in step for step in task["status"]["steps"]):
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
    details_str += click.style("Parameters:\n", bold=True)
    details_str += f"    {click.style('source_url:', bold=True)} {source_url}\n"
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


def _run_external_command(*args, binary: str) -> None:
    cmd = [binary, *args]
    LOGGER.debug("Running command: {cmd}")
    proc = subprocess.Popen(args=cmd, bufsize=0, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, shell=False)
    returncode = proc.poll()
    while returncode is None:
        time.sleep(0.1)
        returncode = proc.poll()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(returncode=proc.returncode, output=None, stderr=None, cmd=cmd)


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

    LOGGER.debug(f"Found {len(subcommands)} subcommands.")
    for name, binary in subcommands.items():

        @cli.command(name=name)
        @click.option("-h", "--help", is_flag=True, default=False)
        @click.argument("args", nargs=-1, type=click.UNPROCESSED)
        def _new_command(args, help: bool):  # noqa
            if help:
                args = ["--help"] + list(args)

            _run_external_command(*args, binary=str(binary.resolve()))

    return cli


@toolforge.command(name="build", help="Build your project to run on toolforge.")
@click.argument("SOURCE_GIT_URL")
@click.option(
    "-n",
    "--image-name",
    help="Image identifier for the builder that will be used to build the project (ex. python).",
    required=True,
    show_default=True,
)
@click.option(
    "-t",
    "--image-tag",
    help="Tag to tag the generated image with.",
    default="latest",
    show_default=True,
)
@click.option(
    "--builder-image",
    help="This is the image identifier for the buildpack builder, without protocol (no http/https).",
    default="docker-registry.tools.wmflabs.org/toolforge-buster0-builder",
    show_default=True,
)
@click.option(
    "--dest-repository",
    help="FQDN to the OIC repository to push the image to, without the protocol (no http/https)",
    default="harbor.toolsbeta.wmflabs.org",
    show_default=True,
)
@click.option(
    "--kubeconfig",
    help="Path to the kubeconfig file.",
    default=Path(os.environ.get("KUBECONFIG", "~/.kube/config")),
    type=Path,
    show_default=True,
)
def build(
    dest_repository: str, source_git_url: str, image_name: str, image_tag: str, builder_image: str, kubeconfig: Path
) -> None:

    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    app_image = get_app_image_url(
        image_name=image_name, image_tag=image_tag, image_repository=dest_repository, user=k8s_client.user
    )
    pipeline_run_spec = get_pipeline_run_spec(
        source_url=source_git_url, builder_image=builder_image, app_image=app_image, username=k8s_client.user
    )
    response = k8s_client.create_object(kind="pipelineruns", spec=pipeline_run_spec)
    run_name = response["metadata"]["name"]
    click.echo(
        f"Building '{source_git_url}' -> '{app_image}'\nYou can see the logs with:\n\ttoolforge build-logs '{run_name}'"
    )


@toolforge.command(name="build-logs", help="Shows the logs for a build, only admins for now.")
@click.argument("RUN_NAME")
def build_logs(run_name: str):
    _run_external_command("pipelinerun", "logs", "--namespace", TBS_NAMESPACE, "-f", run_name, binary="tkn")


@toolforge.command(name="build-list")
@click.option(
    "--kubeconfig",
    help="Path to the kubeconfig file.",
    default=Path(os.environ.get("KUBECONFIG", "~/.kube/config")),
    type=Path,
    show_default=True,
)
@click.option(
    "--json",
    help="If set, will output in json format.",
    is_flag=True,
)
def build_list(kubeconfig: Path, json: bool) -> None:
    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    runs = k8s_client.get_objects(kind="pipelineruns", selector=f"user={k8s_client.user}")
    if not json:
        click.echo(
            click.style(
                "run_name\tstatus\tstart_time\tend_time\tsource_url\trepo_url\timage_name\timage_tag\tbuilder_image",
                bold=True,
            ),
        )

    for run in sorted(runs, key=lambda run: run["status"]["startTime"], reverse=True):
        app_image = next(param for param in run["spec"]["params"] if param["name"] == "APP_IMAGE")["value"]
        repo_url, image_name, image_tag = _app_image_to_parts(app_image=app_image)
        if not json:
            click.echo(_run_to_short_str(run=run))
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
                            "stated_at": run["status"]["startTime"],
                            "end_time": run["status"].get("completionTime", "running"),
                        },
                    },
                    indent=4,
                )
            )


@toolforge.command(name="build-cancel", help="Cancels a running build, though does nothing for stopped ones.")
@click.option(
    "--kubeconfig",
    help="Path to the kubeconfig file.",
    default=Path(os.environ.get("KUBECONFIG", "~/.kube/config")),
    type=Path,
    show_default=True,
)
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
def build_cancel(
    kubeconfig: Path,
    build_name: List[str],
    all: bool,
    yes_i_know: bool,
) -> None:
    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    all_user_runs = k8s_client.get_objects(kind="pipelineruns", selector=f"user={k8s_client.user}")

    if not build_name and not all:
        click.echo("No run passed to cancel.")
        return

    runs_to_cancel = []
    for run in all_user_runs:
        if run["metadata"]["name"] in build_name or all:
            runs_to_cancel.append(run)

    if len(runs_to_cancel) == 0:
        click.echo("No runs to cancel, maybe there was a typo? (try listing them with toolforge build-list)")
        return

    if not yes_i_know:
        click.confirm(f"I'm going to cancel {len(runs_to_cancel)} runs, continue?", abort=True)

    for run in runs_to_cancel:
        # see https://tekton.dev/docs/pipelines/pipelineruns/#cancelling-a-pipelinerun
        k8s_client.patch_object(
            kind="pipelineruns",
            name=run["metadata"]["name"],
            json_patches=[{"op": "add", "path": "/spec/status", "value": "PipelineRunCancelled"}],
        )

    click.echo(f"Cancelled {len(runs_to_cancel)} runs.")


@toolforge.command(name="build-delete", help="Deletes a build, only admins can do it for now.")
@click.option(
    "--kubeconfig",
    help="Path to the kubeconfig file.",
    default=Path(os.environ.get("KUBECONFIG", "~/.kube/config")),
    type=Path,
    show_default=True,
)
@click.option(
    "--all",
    help="Delete all the current builds.",
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
def build_delete(
    kubeconfig: Path,
    build_name: List[str],
    all: bool,
    yes_i_know: bool,
) -> None:
    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    all_user_runs = k8s_client.get_objects(kind="pipelineruns", selector=f"user={k8s_client.user}")

    if not build_name and not all:
        click.echo("No run passed to delete.")
        return

    runs_to_delete = []
    for run in all_user_runs:
        if run["metadata"]["name"] in build_name or all:
            runs_to_delete.append(run)

    if len(runs_to_delete) == 0:
        click.echo("No runs to delete, maybe there was a typo? (try listing them with toolforge build-list)")
        return

    if not yes_i_know:
        click.confirm(f"I'm going to delete {len(runs_to_delete)} runs, continue?", abort=True)

    for run in runs_to_delete:
        k8s_client.delete_object(kind="pipelineruns", name=run["metadata"]["name"])
        # only admins can do this
        k8s_client.delete_objects(kind="pods", selector=f"tekton.dev/pipelineRun={run['metadata']['name']}")
    click.echo(f"Deleted {len(runs_to_delete)} runs.")


@toolforge.command(name="build-show")
@click.argument("RUN_NAME")
@click.option(
    "--kubeconfig",
    help="Path to the kubeconfig file.",
    default=Path(os.environ.get("KUBECONFIG", "~/.kube/config")),
    type=Path,
    show_default=True,
)
@click.option(
    "--json",
    help="If set, will output in json format.",
    is_flag=True,
)
def build_show(run_name: str, kubeconfig: Path, json: bool) -> None:
    k8s_client = K8sAPIClient.from_file(kubeconfig=kubeconfig, namespace=TBS_NAMESPACE)
    run = k8s_client.get_object(kind="pipelineruns", name=run_name)
    app_image = next(param for param in run["spec"]["params"] if param["name"] == "APP_IMAGE")["value"]
    repo_url, image_name, image_tag = _app_image_to_parts(app_image=app_image)
    status = next(condition for condition in run["status"]["conditions"] if condition["type"] == "Succeeded")
    if not json:
        click.echo(_run_to_details_str(run=run, k8s_client=k8s_client))
    else:
        json_mod.dumps(
            {
                "name": run["metadata"]["name"],
                "params": {
                    "image_name": image_name,
                    "image_tag": image_tag,
                    "repo_url": repo_url,
                },
                "status": {
                    "succeeded": status["Status"],
                    "message": status["Message"],
                    "reason": status["Reason"],
                },
            },
            indent=4,
        )


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
