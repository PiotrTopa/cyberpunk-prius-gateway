/*
 * Cyberpunk Prius gateway v3 — RP2350 / RP2040, pico-sdk.
 *
 * One core, one non-blocking loop. Every bus is serviced by hardware
 * (PIO, DMA, UART FIFO + IRQ) so nothing here ever waits; the AVC-LAN
 * path in particular goes PIO -> IRQ decoder -> ring -> USB within the
 * same loop iteration in which the frame's last bit ended.
 */
#include "config.h"
#include "out.h"
#include "usb_cdc.h"
#include "avclan.h"
#include "can_sol.h"
#include "rs485.h"
#include "commands.h"
#include "led.h"

#include "pico/stdlib.h"
#include "hardware/watchdog.h"

int main(void)
{
    /* No stdio: the USB CDC port belongs to the NDJSON protocol. */
    led_init();
    usb_cdc_init(commands_handle_line);
    rs485_init();
    can_sol_init();
    avclan_init();

    watchdog_enable(WATCHDOG_MS, true);

    /* Give the host a moment to see the port before the banner. */
    uint32_t t0 = now_ms();
    while (now_ms() - t0 < 300) { usb_cdc_task(); watchdog_update(); }
    sys_emit_ready();

    uint32_t last_hb = now_ms();
    uint32_t last_diag = now_ms();
    bool host_was = false;

    for (;;) {
        watchdog_update();

        avclan_task();          /* 1. decoded AVC-LAN frames out, TX kick */
        usb_cdc_task();         /* 2. USB device task + host commands */
        can_sol_task();         /* 3. solicited CAN engine */
        rs485_task();           /* 4. satellite bus */

        uint32_t now = now_ms();
        if (now - last_hb >= GW_HEARTBEAT_MS) {
            last_hb = now;
            sys_emit_heartbeat();
        }
        if (now - last_diag >= CAN_DIAG_MS) {
            last_diag = now;
            can_sol_emit_diag();
        }

        bool host = usb_cdc_host_connected();
        if (host != host_was) { host_was = host; led_set_host(host); }
        led_task();
    }
}
