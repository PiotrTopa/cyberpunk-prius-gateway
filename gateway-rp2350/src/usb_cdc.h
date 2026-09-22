/* USB CDC transport (TinyUSB device, one CDC interface). */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

typedef void (*usb_line_cb_t)(char *line, size_t len);

void usb_cdc_init(usb_line_cb_t on_line);

/* Runs the TinyUSB device task and feeds complete input lines to the callback. */
void usb_cdc_task(void);

/* Queue one line for the host. Never blocks; false = dropped. */
bool usb_cdc_write_line(const char *s, size_t n);

bool usb_cdc_host_connected(void);

typedef struct {
    uint32_t rx_lines;
    uint32_t rx_overlong;    /* input lines longer than USB_MAX_LINE */
} usb_cdc_stats_t;

extern usb_cdc_stats_t g_usb;
