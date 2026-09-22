/* On-board WS2812 status LED. */
#pragma once
#include <stdbool.h>

typedef enum {
    LED_EV_AVC = 0,   /* AVC-LAN frame delivered */
    LED_EV_CAN,       /* CAN request/response activity */
    LED_EV_RS485,     /* RS485 traffic */
    LED_EV_ERROR,     /* something dropped or failed */
} led_event_t;

void led_init(void);
void led_event(led_event_t ev);
void led_set_can_ok(bool ok);
void led_set_host(bool connected);
void led_task(void);
