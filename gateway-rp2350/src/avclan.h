/* AVC-LAN front end: PIO capture, IRQ-time decoding, immediate emission, TX. */
#pragma once
#include "avclan_codec.h"
#include <stdint.h>
#include <stdbool.h>

typedef enum { AVC_POL_AUTO = 0, AVC_POL_DOMINANT_HIGH, AVC_POL_DOMINANT_LOW } avc_polarity_t;

typedef struct {
    uint32_t frames_out;      /* frames emitted to the host */
    uint32_t frames_echo;     /* of which: echoes of our own transmissions */
    uint32_t ring_overflow;   /* decoded frames lost because the main loop lagged */
    uint32_t fifo_words;      /* raw PIO words processed */
    uint32_t timeouts;        /* frames abandoned (no pulse for AVC_FRAME_TIMEOUT_US) */
    uint32_t tx_frames;
    uint32_t tx_queue_full;
    uint32_t tx_deferred;     /* transmissions delayed because the bus was busy */
    uint32_t last_frame_ms;
    bool     dominant_low;    /* true: comparator idles high, dominant pulls GP0 low */
    bool     raw_enabled;
    bool     debug_errors;    /* emit decode errors on the system channel */
} avclan_stats_t;

extern avclan_stats_t g_avc;
extern avc_thresholds_t g_avc_thr;

/* Live decoder (owned by the PIO IRQ; read counters only). */
extern avc_rx_t g_avc_rx;

void avclan_init(void);
void avclan_task(void);

/* Queue a frame for transmission. false if the queue is full or the frame is invalid. */
bool avclan_send(const avc_frame_t *f);

/* Re-detect or force the RX polarity. Restarts the receiver. */
void avclan_set_polarity(avc_polarity_t pol);

/* Raw pulse streaming for bring-up: emits {"id":0,"d":{"avc_raw":[+dominant_us,-gap_us,...]}} */
void avclan_set_raw(bool on);

/* Raw level of the RX GPIO as wired (1 = high). */
bool avclan_rx_level(void);

/* True while a frame is being received or transmitted. */
bool avclan_bus_busy(void);

/* Hardware loopback diagnostic: pulse TX pin and measure RX pin */
void avclan_test_loopback(bool *rx_idle, bool *rx_drive, bool *rx_after);
void avclan_test_tx(int mode);
