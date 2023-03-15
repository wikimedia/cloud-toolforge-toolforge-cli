from copy import deepcopy
from typing import Any, Dict, Optional

ERROR_STRINGS = {
    "SERVICE_DOWN_ERROR": (
        "The build service seems to be down – please retry in a few minutes.\nIf the problem persists, " +
        "please contact us or open a bug:\nsee https://phabricator.wikimedia.org/T324822"
    ),
    "UNKOWN_ERROR": (
        "An unknown error occured while trying to perform this operation.\nIf the problem persists, " +
        "please contact us or open a bug:\nsee https://phabricator.wikimedia.org/T324822"

    )
}

PIPELINE_RUN_SKELETON = {
    "apiVersion": "tekton.dev/v1beta1",
    "kind": "PipelineRun",
    "metadata": {
        "generateName": "minikube-user-buildpacks-pipelinerun-",
        "namespace": "image-build",
        "labels": {"user": "PLACEHOLDER"},
    },
    "spec": {
        "serviceAccountName": "buildpacks-service-account",
        "pipelineRef": {"name": "buildpacks"},
        "params": [
            {"name": "BUILDER_IMAGE", "value": "docker-registry.tools.wmflabs.org/toolforge-bullseye0-builder:latest"},
            {"name": "APP_IMAGE", "value": "192.168.49.1/minikube-user/python:snap"},
            {"name": "SOURCE_URL", "value": "https://github.com/david-caro/wm-lol"},
            {"name": "USER_ID", "value": "61312"},
            {"name": "GROUP_ID", "value": "61312"},
        ],
        "workspaces": [{"name": "source-ws", "emptyDir": {}}, {"name": "cache-ws", "emptyDir": {}}],
    },
}


def get_app_image_url(
    image_name: str,
    user: str,
    image_tag: str = "latest",
    image_repository: str = "harbor.toolforge.org",
):
    return f"{image_repository}/{user}/{image_name}:{image_tag}"


def get_pipeline_run_spec(
    app_image: str, source_url: str, builder_image: str, username: str, ref: Optional[str]
) -> Dict[str, Any]:
    # TODO: rethink if there's a better way of building this object, specially the hardcoded indices
    my_pipeline: Dict[str, Any] = deepcopy(PIPELINE_RUN_SKELETON)
    my_pipeline["metadata"]["generateName"] = f"{username}-buildpacks-pipelinerun-"
    # TODO: we might want to move this to a mutator hook instead
    my_pipeline["metadata"]["labels"]["user"] = username
    my_pipeline["spec"]["params"][0]["value"] = builder_image
    my_pipeline["spec"]["params"][1]["value"] = app_image
    my_pipeline["spec"]["params"][2]["value"] = source_url
    if ref:
        my_pipeline["spec"]["params"] += [
            {
                "name": "SOURCE_REFERENCE",
                "value": ref,
            }
        ]

    return my_pipeline
