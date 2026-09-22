#include "led.h"
#include "config.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/sync.h"

static uint32_t s_ev_until[4];
static bool     s_can_ok;
static bool     s_host;
static uint32_t s_last_update;
static uint32_t s_last_color = 0xFFFFFFFF;

void led_init(void)
{
    gpio_init(PIN_WS2812);
    gpio_set_dir(PIN_WS2812, GPIO_OUT);
    gpio_put(PIN_WS2812, 0);
}

static void put_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    uint32_t grb = ((uint32_t)g << 16) | ((uint32_t)r << 8) | b;
    if (grb == s_last_color) return;

    uint32_t f_sys = clock_get_hz(clk_sys);
    uint32_t t0h = f_sys / 2500000; // ~400ns
    uint32_t t0l = f_sys / 1176470; // ~850ns
    uint32_t t1h = f_sys / 1250000; // ~800ns
    uint32_t t1l = f_sys / 2222222; // ~450ns

    uint32_t save = save_and_disable_interrupts();
    for (int i = 23; i >= 0; i--) {
        if (grb & (1u << i)) {
            gpio_put(PIN_WS2812, 1);
            busy_wait_at_least_cycles(t1h);
            gpio_put(PIN_WS2812, 0);
            busy_wait_at_least_cycles(t1l);
        } else {
            gpio_put(PIN_WS2812, 1);
            busy_wait_at_least_cycles(t0h);
            gpio_put(PIN_WS2812, 0);
            busy_wait_at_least_cycles(t0l);
        }
    }
    restore_interrupts(save);
    
    s_last_color = grb;
}

void led_event(led_event_t ev)
{
    s_ev_until[ev] = time_us_32() + 40000;   /* 40 ms flash */
}

void led_set_can_ok(bool ok) { s_can_ok = ok; }
void led_set_host(bool connected) { s_host = connected; }

void led_task(void)
{
    uint32_t now = time_us_32();
    if ((uint32_t)(now - s_last_update) < 20000) return;   /* 50 Hz max */
    s_last_update = now;

    bool avc   = (int32_t)(s_ev_until[LED_EV_AVC]   - now) > 0;
    bool can   = (int32_t)(s_ev_until[LED_EV_CAN]   - now) > 0;
    bool rs    = (int32_t)(s_ev_until[LED_EV_RS485] - now) > 0;
    bool err   = (int32_t)(s_ev_until[LED_EV_ERROR] - now) > 0;

    if (err)       { put_rgb(40, 0, 0);  return; }
    if (avc)       { put_rgb(0, 30, 40); return; }   /* cyan */
    if (can)       { put_rgb(40, 24, 0); return; }   /* amber */
    if (rs)        { put_rgb(20, 0, 40); return; }   /* violet */

    /* idle: slow breathing, green when host connected, blue otherwise;
       red tint if the CAN controller failed to initialise */
    uint32_t phase = (now / 1000) % 2000;
    uint32_t tri = phase < 1000 ? phase : 2000 - phase;    /* 0..1000 */
    uint8_t lvl = (uint8_t)(2 + tri * 10 / 1000);          /* 2..12 */
    if (!s_can_ok)      put_rgb(lvl, 0, 0);
    else if (s_host)    put_rgb(0, lvl, 0);
    else                put_rgb(0, 0, lvl);
}
