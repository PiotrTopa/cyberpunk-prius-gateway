#include "pico/stdlib.h"
#include "hardware/clocks.h"

void ws2812_put_pixel(uint pin, uint32_t pixel_grb) {
    uint32_t mask = 1ul << pin;
    uint32_t f_sys = clock_get_hz(clk_sys);
    
    uint32_t t0h = f_sys / 2500000; // 400ns
    uint32_t t0l = f_sys / 1176470; // 850ns
    uint32_t t1h = f_sys / 1250000; // 800ns
    uint32_t t1l = f_sys / 2222222; // 450ns

    uint32_t save = save_and_disable_interrupts();
    for (int i = 23; i >= 0; i--) {
        if (pixel_grb & (1u << i)) {
            gpio_put(pin, 1);
            busy_wait_at_least_cycles(t1h);
            gpio_put(pin, 0);
            busy_wait_at_least_cycles(t1l);
        } else {
            gpio_put(pin, 1);
            busy_wait_at_least_cycles(t0h);
            gpio_put(pin, 0);
            busy_wait_at_least_cycles(t0l);
        }
    }
    restore_interrupts(save);
}
