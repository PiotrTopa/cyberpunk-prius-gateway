#include "rs485.h"
#include "config.h"
#include "out.h"
#include "led.h"
#include "json_util.h"
#include "pico/stdlib.h"
#include "hardware/uart.h"
#include "hardware/irq.h"
#include "hardware/gpio.h"
#include <string.h>
#include <stdio.h>

#define UART_ID uart1

rs485_stats_t g_rs485;

/* IRQ-fed receive ring */
static uint8_t           s_rx_ring[RS485_RX_RING];
static volatile uint16_t s_rx_head, s_rx_tail;
static volatile uint32_t s_last_rx_us;

/* transmit ring (main loop only) */
static uint8_t  s_tx_ring[RS485_TX_RING];
static uint16_t s_tx_head, s_tx_tail;
static bool     s_de_on;
static uint32_t s_de_on_us;

/* line assembly */
static char   s_line[RS485_MAX_LINE + 1];
static size_t s_line_len;
static bool   s_discarding;

static void __isr uart_rx_irq(void)
{
    while (uart_is_readable(UART_ID)) {
        uint8_t c = (uint8_t)uart_get_hw(UART_ID)->dr;
        uint16_t next = (uint16_t)((s_rx_head + 1) % RS485_RX_RING);
        if (next == s_rx_tail) { g_rs485.rx_overrun++; continue; }
        s_rx_ring[s_rx_head] = c;
        s_rx_head = next;
    }
    s_last_rx_us = time_us_32();
}

void rs485_init(void)
{
    gpio_init(PIN_RS485_DE);
    gpio_set_dir(PIN_RS485_DE, GPIO_OUT);
    gpio_put(PIN_RS485_DE, 0);

    uart_init(UART_ID, RS485_BAUD);
    gpio_set_function(PIN_RS485_TX, GPIO_FUNC_UART);
    gpio_set_function(PIN_RS485_RX, GPIO_FUNC_UART);
    gpio_pull_up(PIN_RS485_RX);
    uart_set_format(UART_ID, 8, 1, UART_PARITY_NONE);
    uart_set_hw_flow(UART_ID, false, false);
    uart_set_fifo_enabled(UART_ID, true);

    irq_set_exclusive_handler(UART1_IRQ, uart_rx_irq);
    irq_set_enabled(UART1_IRQ, true);
    uart_set_irq_enables(UART_ID, true, false);   /* RX + RX timeout */

    g_rs485.ready = true;
}

static size_t tx_ring_free(void)
{
    return (size_t)((s_tx_tail + RS485_TX_RING - s_tx_head - 1) % RS485_TX_RING);
}

static bool tx_ring_put(const uint8_t *p, size_t n)
{
    if (tx_ring_free() < n) return false;
    for (size_t i = 0; i < n; i++) {
        s_tx_ring[s_tx_head] = p[i];
        s_tx_head = (uint16_t)((s_tx_head + 1) % RS485_TX_RING);
    }
    return true;
}

bool rs485_send(const char *line, size_t len)
{
    if (!g_rs485.ready) return false;
    bool nl = len && line[len - 1] == '\n';
    if (tx_ring_free() < len + (nl ? 0 : 1)) { g_rs485.tx_ring_full++; return false; }
    tx_ring_put((const uint8_t *)line, len);
    if (!nl) { uint8_t c = '\n'; tx_ring_put(&c, 1); }
    g_rs485.tx_lines++;
    return true;
}

int rs485_test_pattern(void)
{
    uint8_t pat[50];
    memset(pat, 0x55, sizeof(pat));
    if (!tx_ring_put(pat, sizeof(pat))) return 0;
    return (int)sizeof(pat);
}

/* Forward a satellite line to the host, injecting ts (and seq) like v2.x did. */
static void forward_line(const char *line, size_t len)
{
    if (len < 2 || line[0] != '{' || line[len - 1] != '}') { g_rs485.rx_bad++; return; }
    long id;
    if (!json_scan_id(line, len, &id)) { g_rs485.rx_bad++; return; }

    static char buf[RS485_MAX_LINE + 64];   /* main-loop only */
    char *p = buf;
    *p++ = '{';
    bool has_ts  = strstr(line, "\"ts\"")  != NULL;
    bool has_seq = strstr(line, "\"seq\"") != NULL;
    bool injected = false;
    if (!has_ts) {
        p += sprintf(p, "\"ts\":%lu", (unsigned long)now_ms());
        injected = true;
    }
    if (!has_seq && g_out.seq_enabled) {
        p += sprintf(p, "%s\"seq\":%lu", injected ? "," : "", (unsigned long)out_next_seq());
        injected = true;
    }
    if (injected && len > 2) *p++ = ',';    /* more members follow */
    memcpy(p, line + 1, len - 1);           /* rest of the object incl. '}' */
    p += len - 1;
    out_line(buf, (size_t)(p - buf));
    g_rs485.rx_lines++;
    g_rs485.last_rx_ms = now_ms();
    led_event(LED_EV_RS485);
}

static void pump_rx(void)
{
    while (s_rx_tail != s_rx_head) {
        char c = (char)s_rx_ring[s_rx_tail];
        s_rx_tail = (uint16_t)((s_rx_tail + 1) % RS485_RX_RING);
        if (c == '\n' || c == '\r') {
            if (s_discarding) s_discarding = false;
            else if (s_line_len) { s_line[s_line_len] = 0; forward_line(s_line, s_line_len); }
            s_line_len = 0;
            continue;
        }
        if (s_discarding) continue;
        if (s_line_len >= RS485_MAX_LINE) { s_discarding = true; s_line_len = 0; g_rs485.rx_bad++; continue; }
        s_line[s_line_len++] = c;
    }
}

static void pump_tx(void)
{
    uint32_t now = time_us_32();
    if (!s_de_on) {
        if (s_tx_head == s_tx_tail) return;
        /* light arbitration: don't key up while a satellite is mid-frame */
        if ((uint32_t)(now - s_last_rx_us) < RS485_IDLE_BEFORE_TX_US) return;
        gpio_put(PIN_RS485_DE, 1);
        s_de_on = true;
        s_de_on_us = now;
        return;
    }
    if ((uint32_t)(now - s_de_on_us) < RS485_DE_LEAD_US) return;

    while (s_tx_head != s_tx_tail && uart_is_writable(UART_ID)) {
        uart_get_hw(UART_ID)->dr = s_tx_ring[s_tx_tail];
        s_tx_tail = (uint16_t)((s_tx_tail + 1) % RS485_TX_RING);
        g_rs485.tx_bytes++;
    }
    if (s_tx_head == s_tx_tail && !(uart_get_hw(UART_ID)->fr & UART_UARTFR_BUSY_BITS)) {
        gpio_put(PIN_RS485_DE, 0);     /* last stop bit is on the wire */
        s_de_on = false;
    }
}

void rs485_task(void)
{
    if (!g_rs485.ready) return;
    pump_rx();
    pump_tx();
}
