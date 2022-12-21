from pytest import fixture

from toolforge_cli.build import get_app_image_url, get_pipeline_run_spec


@fixture
def pipeline_run_spec():
    return get_pipeline_run_spec(
        app_image="dummy-image",
        source_url="http://dummy.source.url",
        builder_image="dummy-builder-image",
        username="dummy-username",
        ref="dummy-ref",
    )


def test_get_app_image_url_image_repository_defaults_to_harbor():
    assert (
        get_app_image_url(image_name="dummy-image", user="dummy-user", image_tag="dummy-tag")
        == "harbor.toolforge.org/dummy-user/dummy-image:dummy-tag"
    )


def test_get_app_image_url_default_tag_defaults_to_latest():
    assert (
        get_app_image_url(image_name="dummy-image", user="dummy-user", image_repository="dummy-repo")
        == "dummy-repo/dummy-user/dummy-image:latest"
    )


def test_get_pipeline_run_spec_sets_generated_name_prefixed_by_user(pipeline_run_spec):
    assert pipeline_run_spec["metadata"]["generateName"] == "dummy-username-buildpacks-pipelinerun-"


def test_get_pipeline_run_spec_sets_user_label(pipeline_run_spec):
    assert pipeline_run_spec["metadata"]["labels"]["user"] == "dummy-username"


def test_get_pipeline_run_spec_sets_builder_image(pipeline_run_spec):
    assert pipeline_run_spec["spec"]["params"][0]["value"] == "dummy-builder-image"
    assert (
        pipeline_run_spec["spec"]["params"][0]["name"] == "BUILDER_IMAGE"
    ), "The pipeline run spec changed and the builder image is not the first parameter anymore, please ensure the code is still correct."


def test_get_pipeline_run_spec_sets_app_image(pipeline_run_spec):
    assert pipeline_run_spec["spec"]["params"][1]["value"] == "dummy-image"
    assert (
        pipeline_run_spec["spec"]["params"][1]["name"] == "APP_IMAGE"
    ), "The pipeline run spec changed and the app image is not the second parameter anymore, please ensure the code is still correct."


def test_get_pipeline_run_spec_sets_source_url(pipeline_run_spec):
    assert pipeline_run_spec["spec"]["params"][2]["value"] == "http://dummy.source.url"
    assert (
        pipeline_run_spec["spec"]["params"][2]["name"] == "SOURCE_URL"
    ), "The pipeline run spec changed and the source url is not the third parameter anymore, please ensure the code is still correct."
