#!/usr/bin/env bash
# Build and run the host-side unit tests (no Pico toolchain needed).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build-test
cc -std=c11 -Wall -Wextra -O1 -g -Isrc \
    src/avclan_codec.c src/json_util.c test/test_codec.c \
    -o build-test/test_codec
./build-test/test_codec
