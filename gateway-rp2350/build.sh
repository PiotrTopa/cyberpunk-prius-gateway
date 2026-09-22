#!/usr/bin/env bash
# Build the gateway firmware.
#
#   ./build.sh                                  # RP2350-Zero (default)
#   PICO_BOARD=waveshare_rp2040_zero ./build.sh # RP2040-Zero, same pinout
#
# Toolchain lookup order: $PICO_SDK_PATH / tools on $PATH, then the layout
# ~/.pico-sdk/{sdk/<ver>,toolchain/<ver>/bin,venv/bin} (as installed on 2026-09-16).
set -euo pipefail
cd "$(dirname "$0")"

BOARD="${PICO_BOARD:-waveshare_rp2350_zero}"
PSDK_ROOT="${HOME}/.pico-sdk"

if [ -z "${PICO_SDK_PATH:-}" ]; then
    PICO_SDK_PATH="$(ls -d "${PSDK_ROOT}"/sdk/* 2>/dev/null | sort -V | tail -1 || true)"
    [ -n "$PICO_SDK_PATH" ] || { echo "PICO_SDK_PATH not set and no SDK under ${PSDK_ROOT}/sdk" >&2; exit 1; }
    export PICO_SDK_PATH
fi

if ! command -v arm-none-eabi-gcc >/dev/null 2>&1; then
    TC="$(ls -d "${PSDK_ROOT}"/toolchain/*/bin 2>/dev/null | sort -V | tail -1 || true)"
    [ -n "$TC" ] || { echo "arm-none-eabi-gcc not found" >&2; exit 1; }
    export PATH="${TC}:${PATH}"
fi
if ! command -v cmake >/dev/null 2>&1 || ! command -v ninja >/dev/null 2>&1; then
    [ -x "${PSDK_ROOT}/venv/bin/cmake" ] && export PATH="${PSDK_ROOT}/venv/bin:${PATH}"
fi

BUILD="build-${BOARD}"
cmake -S . -B "$BUILD" -G Ninja -DPICO_BOARD="$BOARD" -DCMAKE_BUILD_TYPE="${BUILD_TYPE:-Release}" "$@"
cmake --build "$BUILD" --parallel
echo
echo "UF2: $(pwd)/${BUILD}/prius_gateway.uf2"
