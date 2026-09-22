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
    uint32_t last_rx_ms;
} rs485_stats_t;

extern rs485_stats_t g_rs485;

void rs485_init(void);
void rs485_task(void);

/* Queue a line for the bus (a trailing '\n' is added). false = ring full. */
bool rs485_send(const char *line, size_t len);

/* Bench test: 50 x 0x55 on the wire. Returns bytes queued. */
int  rs485_test_pattern(void);
