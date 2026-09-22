#include "usb_cdc.h"
#include "config.h"
#include "tusb.h"
#include <string.h>

usb_cdc_stats_t g_usb;

static usb_line_cb_t s_on_line;
static char   s_line[USB_MAX_LINE + 1];
static size_t s_line_len;
static bool   s_discarding;   /* skipping the rest of an overlong line */

void usb_cdc_init(usb_line_cb_t on_line)
{
    s_on_line = on_line;
    tusb_init();
}

bool usb_cdc_host_connected(void)
{
    return tud_cdc_connected();
}

static void pump_rx(void)
{
    uint8_t buf[256];
    while (tud_cdc_available()) {
        uint32_t n = tud_cdc_read(buf, sizeof(buf));
        for (uint32_t i = 0; i < n; i++) {
            char c = (char)buf[i];
            if (c == '\n' || c == '\r') {
                if (s_discarding) {
                    s_discarding = false;
                } else if (s_line_len) {
                    s_line[s_line_len] = 0;
                    g_usb.rx_lines++;
                    if (s_on_line) s_on_line(s_line, s_line_len);
                }
                s_line_len = 0;
                continue;
            }
            if (s_discarding) continue;
            if (s_line_len >= USB_MAX_LINE) {
                s_discarding = true;
                s_line_len = 0;
                g_usb.rx_overlong++;
                continue;
            }
            s_line[s_line_len++] = c;
        }
    }
}

void usb_cdc_task(void)
{
    tud_task();
    if (tud_cdc_available()) pump_rx();
}

bool usb_cdc_write_line(const char *s, size_t n)
{
    if (!tud_cdc_connected()) {
        /* Nobody listening: never let stale data pile up for the next open. */
        tud_cdc_write_clear();
        return false;
    }
    if (tud_cdc_write_available() < n + 1) return false;   /* whole line or nothing */
    tud_cdc_write(s, (uint32_t)n);
    tud_cdc_write_char('\n');
    tud_cdc_write_flush();
    return true;
}

/* --- TinyUSB callbacks -------------------------------------------------- */

void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts)
{
    (void)itf; (void)rts;
    if (!dtr) {
        /* host closed the port: drop any half line */
        s_line_len = 0;
        s_discarding = false;
    }
}
