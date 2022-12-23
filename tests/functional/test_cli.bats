#!/usr/bin/env bats

bats_require_minimum_version 1.5.0


@test "single binary is found" {
    export PATH=$BATS_TEST_DIRNAME/fixtures/single_binary:$PATH

    run toolforge --help

    [[ "$status" == "0" ]]
    [[ "$output" =~ .*^\ *binary ]]

    run toolforge binary

    [[ "$status" == "0" ]]
    [[ "$output" == "single-binary executed" ]]
}


@test "multiple binaries are found" {
    export PATH=$BATS_TEST_DIRNAME/fixtures/multiple_binaries:$PATH

    run toolforge --help

    [[ "$status" == "0" ]]
    [[ "$output" =~ .*^\ *one ]]
    [[ "$output" =~ .*^\ *two ]]

    run toolforge one

    [[ "$status" == "0" ]]
    [[ "$output" == "toolforge-one executed" ]]

    run toolforge two

    [[ "$status" == "0" ]]
    [[ "$output" == "toolforge-two executed" ]]
}


@test "nested binaries are found" {
    export PATH=$BATS_TEST_DIRNAME/fixtures/nested_binaries:$PATH
    export PATH=$BATS_TEST_DIRNAME/fixtures/nested_binaries/nested_dir:$PATH

    run toolforge --help

    [[ "$status" == "0" ]]
    [[ "$output" =~ .*^\ *simple ]]
    [[ "$output" =~ .*^\ *nested ]]

    run toolforge simple

    [[ "$status" == "0" ]]
    [[ "$output" == "toolforge-simple executed" ]]

    run toolforge nested

    [[ "$status" == "0" ]]
    [[ "$output" == "toolforge-nested executed" ]]
}


@test "non-toolforge binaries are not found" {
    export PATH=$BATS_TEST_DIRNAME/fixtures/mixed_files:$PATH

    run toolforge --help

    [[ "$status" == "0" ]]
    [[ "$output" =~ .*^\ *plugin ]]
    ! [[ "$output" =~ .*^\ *nonplugin ]]

    run toolforge plugin

    [[ "$status" == "0" ]]
    [[ "$output" == "toolforge-plugin executed" ]]
}

@test "test that params are sent through" {
    export PATH=$BATS_TEST_DIRNAME/fixtures/passes_params_through:$PATH

    run toolforge --help

    [[ "$status" == "0" ]]
    [[ "$output" =~ .*^\ *params ]]

    run toolforge params

    [[ "$status" == "0" ]]
    [[ "$output" == "toolforge-params: " ]]

    run toolforge params -h one two --other=one

    [[ "$status" == "0" ]]
    [[ "$output" == "toolforge-params: -h one two --other=one" ]]
}
