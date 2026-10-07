/* Build-time configuration: pins, bus parameters, protocol constants. */
#pragma once

#define FW_VERSION      "3.1.0"
#define FW_ROLE         "gateway"

#ifndef PICO_BOARD
#define PICO_BOARD      "unknown"
#endif

/* ---- Pin map (identical to the RP2040-Zero gateway v2.x) ---------------- */
#define PIN_AVC_RX      0    /* LM339 comparator output, open collector + 4k7 to 3V3 */
#define PIN_AVC_TX      1    /* -> 2k2 -> BC547 base; HIGH = drive dominant */

#define PIN_CAN_SCK     26   /* SPI1 */
#define PIN_CAN_MOSI    27
#define PIN_CAN_MISO    28
#define PIN_CAN_CS      29
#define PIN_CAN_INT     15   /* MCP2515 INT, active low */

#define PIN_RS485_DE    7    /* MAX485 DE/RE, HIGH = transmit */
#define PIN_RS485_TX    8    /* UART1 */
#define PIN_RS485_RX    9

#ifdef PICO_DEFAULT_WS2812_PIN
#define PIN_WS2812      PICO_DEFAULT_WS2812_PIN
#else
#define PIN_WS2812      16
#endif

/* ---- Buses -------------------------------------------------------------- */
#define CAN_BITRATE     500000
#define CAN_CRYSTAL_HZ  8000000     /* module marked 8.000 - CNF values below are for this */
#define CAN_SPI_HZ      4000000     /* prototype wiring; MCP2515 tolerates 10 MHz on a PCB */

#define RS485_BAUD      115200
#define RS485_MAX_LINE  4096
#define RS485_TX_RING   8192
#define RS485_RX_RING   4096
#define RS485_IDLE_BEFORE_TX_US  2000  /* only key the driver after this much bus silence */
#define RS485_DE_LEAD_US         100   /* DE asserted -> first byte */

#define USB_MAX_LINE    4096

/* ---- NDJSON device ids -------------------------------------------------- */
#define DEV_SYS         0
#define DEV_CAN         1
#define DEV_AVC         2
#define DEV_SAT_MIN     6    /* anything above 5 is tunnelled to RS485 */

/* ---- Timing ------------------------------------------------------------- */
#define GW_HEARTBEAT_MS     1000
#define CAN_DIAG_MS         5000
#define WATCHDOG_MS         8000

/* AVC-LAN: a frame with no dominant pulse for this long is abandoned. */
#define AVC_FRAME_TIMEOUT_US  600
/* AVC-LAN: bus must be free of pulses for this long before we transmit. */
#define AVC_TX_IDLE_US        250
