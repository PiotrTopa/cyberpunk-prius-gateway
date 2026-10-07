cmake_minimum_required(VERSION 3.13)

# Target board. RP2350-Zero is the default; the RP2040-Zero (same pinout) builds
# with -DPICO_BOARD=waveshare_rp2040_zero.
set(PICO_BOARD waveshare_rp2350_zero CACHE STRING "Board type")

include(pico_sdk_import.cmake)

project(prius_gateway C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(prius_gateway
    src/main.c
    src/commands.c
    src/out.c
    src/usb_cdc.c
    src/usb_descriptors.c
    src/json_util.c
    src/avclan_codec.c
    src/avclan.c
    src/mcp2515.c
    src/can_sol.c
    src/rs485.c
    src/led.c
)

pico_generate_pio_header(prius_gateway ${CMAKE_CURRENT_LIST_DIR}/src/avclan.pio)
pico_generate_pio_header(prius_gateway ${CMAKE_CURRENT_LIST_DIR}/src/ws2812.pio)

target_include_directories(prius_gateway PRIVATE ${CMAKE_CURRENT_LIST_DIR}/src)

target_compile_options(prius_gateway PRIVATE -Wall -Wextra -Wno-unused-parameter)

# Core-0 stack: 4 KB (fills SCRATCH_Y; the SDK default is 2 KB). All big line
# buffers are static, so this leaves ample headroom for printf/TinyUSB.
target_compile_definitions(prius_gateway PRIVATE PICO_STACK_SIZE=0x1000)

target_link_libraries(prius_gateway
    pico_stdlib
    pico_unique_id
    pico_bootrom
    hardware_pio
    hardware_dma
    hardware_spi
    hardware_uart
    hardware_irq
    hardware_gpio
    hardware_clocks
    hardware_watchdog
    tinyusb_device
)

# The USB port is the protocol channel, not a console.
pico_enable_stdio_usb(prius_gateway 0)
pico_enable_stdio_uart(prius_gateway 0)

pico_set_program_name(prius_gateway "prius_gateway")
pico_set_program_version(prius_gateway "3.1.0")

pico_add_extra_outputs(prius_gateway)
