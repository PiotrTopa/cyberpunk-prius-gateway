/* Half-duplex RS485 satellite bus (UART1 + DE), NDJSON lines, non-blocking. */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

typedef struct {
    bool     ready;
    uint32_t tx_lines;
    uint32_t tx_bytes;
    uint32_t tx_ring_full;
    uint32_t rx_lines;
    uint32_t rx_bad;         /* non-JSON or overlong */
    uint32_t rx_overrun;     /* software ring overflow */
    uint32_t rx_bytes;       /* every byte the UART delivered */
    uint32_t rx_framing;     /* UART framing errors (bad stop bit: noise, wrong baud, swapped A/B) */
    uint32_t rx_break;       /* UART break conditions (line held low) */
    uint32_t rx_fifo_ovr;    /* hardware FIFO overruns */
    uint32_t last_rx_ms;
} rs485_stats_t;

extern rs485_stats_t g_rs485;

void rs485_init(void);
void rs485_task(void);

/* Queue a line for the bus (a trailing '\n' is added). false = ring full. */
bool rs485_send(const char *line, size_t len);

/* Bench self-test of the transceiver wiring: RX pin level under each pull,
 * with the driver off (receiver on) and on (receiver off, RO released).
 * Fills lv[0..5] = DE off: none/up/down, DE on: none/up/down. ~1 ms, main loop only. */
void rs485_diag(uint8_t lv[6]);

/* Bench: key the driver and hold the TX pin at a fixed level for `ms`
 * (static A/B and wiring check with a meter). Bus traffic waits meanwhile. */
void rs485_hold(bool tx_level, uint32_t ms);
/* Bench wiring finder. drive=true: key the driver and hold `pin` (TX or RX
 * pin) at `level`. drive=false: driver off, TX pin released as an input, so
 * every pad can be watched with gpio_get_all() while the far end drives. */
void rs485_probe(bool drive, unsigned pin, bool level, uint32_t ms);
bool rs485_holding(void);

/* Bench test: 50 x 0x55 on the wire. Returns bytes queued. */
int  rs485_test_pattern(void);
