#include "avclan.h"
#include "config.h"
#include "out.h"
#include "led.h"
#include "avclan.pio.h"

#include "pico/stdlib.h"
#include "pico/sync.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/gpio.h"
#include "hardware/clocks.h"
#include <string.h>
#include <stdio.h>

#define AVC_RX_PIO      pio0
#define AVC_RX_SM       0
#define AVC_TX_PIO      pio1
#define AVC_TX_SM       1
#define AVC_RX_CLK_HZ   4000000u   /* 2 cycles per count -> 0.5 us */
#define AVC_TX_CLK_HZ   1000000u
/* Counter -> microseconds, including the program's fixed dead time around each
 * edge (calibrated with test/pio_sim.py: 20 us -> 35 counts, 32 us -> 59,
 * 19 us gap -> 34, 7 us gap -> 10). */
#define RX_DOM_TO_US(c) (((c) + 5u) / 2u)
#define RX_GAP_TO_US(c) (((c) + 4u) / 2u)

avclan_stats_t   g_avc;
avc_thresholds_t g_avc_thr = AVC_THRESHOLDS_DEFAULT;
avc_rx_t         g_avc_rx;

/* ---- decoded-frame ring (IRQ producer, main-loop consumer) -------------- */
#define FRAME_RING 32
typedef struct { avc_frame_t f; uint32_t ts_ms; } frame_slot_t;
static frame_slot_t     s_ring[FRAME_RING];
static volatile uint8_t s_ring_head, s_ring_tail;

/* ---- decode error ring (debug) ----------------------------------------- */
#define ERR_RING 8
typedef struct { uint8_t err, field; uint16_t master, slave; } err_slot_t;
static err_slot_t       s_err[ERR_RING];
static volatile uint8_t s_err_head, s_err_tail;

/* ---- raw pulse ring (debug) -------------------------------------------- */
#define RAW_RING 1024
static int32_t           s_raw[RAW_RING];
static volatile uint16_t s_raw_head, s_raw_tail;
static uint32_t          s_raw_dropped;

static volatile uint32_t s_last_pulse_us;
static uint32_t s_rx_offset;
static bool     s_rx_inverted;

/* ---- TX ---------------------------------------------------------------- */
#define TX_QUEUE 8
static avc_frame_t s_txq[TX_QUEUE];
static uint8_t     s_txq_head, s_txq_tail;
static uint32_t    s_tx_words[1 + AVC_TX_MAX_WORDS];
static int         s_tx_dma = -1;
static uint32_t    s_tx_offset;
static bool        s_tx_active;
static uint32_t    s_tx_end_us;
static avc_frame_t s_tx_last;
static bool        s_tx_last_valid;

/* ------------------------------------------------------------------------ */
/* IRQ: PIO RX FIFO not empty                                                */
/* ------------------------------------------------------------------------ */

static inline void raw_push(int32_t v)
{
    uint16_t next = (uint16_t)((s_raw_head + 1) % RAW_RING);
    if (next == s_raw_tail) { s_raw_dropped++; return; }
    s_raw[s_raw_head] = v;
    s_raw_head = next;
}

static void __isr __time_critical_func(avc_rx_irq)(void)
{
    while (!pio_sm_is_rx_fifo_empty(AVC_RX_PIO, AVC_RX_SM)) {
        uint32_t w = pio_sm_get(AVC_RX_PIO, AVC_RX_SM);
        g_avc.fifo_words++;

        if (w & 0x80000000u) {                      /* gap word */
            if (g_avc.raw_enabled) {
                uint32_t gap = ~w;
                raw_push(-(int32_t)RX_GAP_TO_US(gap));
            }
            continue;
        }

        uint32_t now = time_us_32();
        s_last_pulse_us = now;
        uint32_t us = RX_DOM_TO_US(w);
        if (g_avc.raw_enabled) raw_push((int32_t)us);

        avc_rx_result_t r = avc_rx_feed(&g_avc_rx, avc_classify(&g_avc_thr, us));
        if (r == AVC_RX_FRAME) {
            uint8_t next = (uint8_t)((s_ring_head + 1) % FRAME_RING);
            if (next == s_ring_tail) {
                g_avc.ring_overflow++;
            } else {
                s_ring[s_ring_head].f = g_avc_rx.f;
                s_ring[s_ring_head].ts_ms = now / 1000u;
                s_ring_head = next;
            }
        } else if (r == AVC_RX_ERROR && g_avc.debug_errors) {
            uint8_t next = (uint8_t)((s_err_head + 1) % ERR_RING);
            if (next != s_err_tail) {
                s_err[s_err_head].err    = (uint8_t)g_avc_rx.last_error;
                s_err[s_err_head].field  = g_avc_rx.err_field;
                s_err[s_err_head].master = g_avc_rx.f.master;
                s_err[s_err_head].slave  = g_avc_rx.f.slave;
                s_err_head = next;
            }
        }
    }
}

/* ------------------------------------------------------------------------ */
/* Setup                                                                     */
/* ------------------------------------------------------------------------ */

bool avclan_rx_level(void)
{
    return gpio_get(PIN_AVC_RX);
}

static bool detect_dominant_low(void)
{
    /* The bus is idle far more than it is active: the majority level over
     * ~60 ms is the idle level. Dominant is the opposite level. */
    gpio_set_inover(PIN_AVC_RX, GPIO_OVERRIDE_NORMAL);
    int high = 0;
    const int samples = 3000;
    for (int i = 0; i < samples; i++) {
        high += gpio_get(PIN_AVC_RX) ? 1 : 0;
        sleep_us(20);
    }
    return high * 2 > samples;   /* idles high -> dominant is low */
}

static void rx_start(void)
{
    pio_sm_set_enabled(AVC_RX_PIO, AVC_RX_SM, false);
    pio_sm_clear_fifos(AVC_RX_PIO, AVC_RX_SM);
    pio_sm_restart(AVC_RX_PIO, AVC_RX_SM);
    pio_sm_clkdiv_restart(AVC_RX_PIO, AVC_RX_SM);

    pio_sm_config c = avclan_rx_program_get_default_config(s_rx_offset);
    sm_config_set_in_pins(&c, PIN_AVC_RX);
    sm_config_set_jmp_pin(&c, PIN_AVC_RX);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv(&c, (float)clock_get_hz(clk_sys) / (float)AVC_RX_CLK_HZ);
    pio_sm_init(AVC_RX_PIO, AVC_RX_SM, s_rx_offset, &c);

    /* OSR = 0xFFFFFFFF: the down-counter start value used by the program. */
    pio_sm_exec(AVC_RX_PIO, AVC_RX_SM, pio_encode_mov_not(pio_osr, pio_null));

    uint32_t save = save_and_disable_interrupts();
    avc_rx_init(&g_avc_rx);
    s_ring_head = s_ring_tail = 0;
    restore_interrupts(save);

    pio_sm_set_enabled(AVC_RX_PIO, AVC_RX_SM, true);
}

static void tx_setup(void)
{
    pio_gpio_init(AVC_TX_PIO, PIN_AVC_TX);

    s_tx_offset = pio_add_program(AVC_TX_PIO, &avclan_tx_program);
    pio_sm_config c = avclan_tx_program_get_default_config(s_tx_offset);
    sm_config_set_sideset_pins(&c, PIN_AVC_TX);
    sm_config_set_out_shift(&c, false, true, 32);          /* MSB first, autopull */
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_clkdiv(&c, (float)clock_get_hz(clk_sys) / (float)AVC_TX_CLK_HZ);
    pio_sm_init(AVC_TX_PIO, AVC_TX_SM, s_tx_offset, &c);
    pio_sm_set_consecutive_pindirs(AVC_TX_PIO, AVC_TX_SM, PIN_AVC_TX, 1, true);
    pio_sm_set_pins_with_mask(AVC_TX_PIO, AVC_TX_SM, 0, 1u << PIN_AVC_TX);       /* recessive */
    pio_sm_set_enabled(AVC_TX_PIO, AVC_TX_SM, true);

    s_tx_dma = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config((uint)s_tx_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, true);
    channel_config_set_write_increment(&dc, false);
    channel_config_set_dreq(&dc, pio_get_dreq(AVC_TX_PIO, AVC_TX_SM, true));
    dma_channel_configure((uint)s_tx_dma, &dc, &AVC_TX_PIO->txf[AVC_TX_SM], s_tx_words, 0, false);
}

void avclan_test_loopback(bool *rx_idle, bool *rx_drive, bool *rx_after)
{
    *rx_idle = gpio_get(PIN_AVC_RX);
    gpio_init(PIN_AVC_TX);
    gpio_set_dir(PIN_AVC_TX, GPIO_OUT);
    gpio_put(PIN_AVC_TX, 1);
    busy_wait_us(100);
    *rx_drive = gpio_get(PIN_AVC_RX);
    gpio_put(PIN_AVC_TX, 0);
    busy_wait_us(100);
    *rx_after = gpio_get(PIN_AVC_RX);
    pio_gpio_init(AVC_TX_PIO, PIN_AVC_TX);
}

void avclan_test_tx(int mode)
{
    if (mode == 0 || mode == 1) {
        gpio_init(PIN_AVC_TX);
        gpio_set_dir(PIN_AVC_TX, GPIO_OUT);
        gpio_put(PIN_AVC_TX, mode);
    } else if (mode == 2) {
        gpio_init(PIN_AVC_TX);
        gpio_set_dir(PIN_AVC_TX, GPIO_OUT);
        for (int i = 0; i < 10000; i++) {
            gpio_put(PIN_AVC_TX, 1);
            busy_wait_us(500);
            gpio_put(PIN_AVC_TX, 0);
            busy_wait_us(500);
        }
        pio_gpio_init(AVC_TX_PIO, PIN_AVC_TX);
    }
}

void avclan_init(void)
{
    gpio_init(PIN_AVC_RX);
    gpio_set_dir(PIN_AVC_RX, GPIO_IN);
    gpio_disable_pulls(PIN_AVC_RX);           /* external 4k7 pull-up to 3V3 */
    gpio_set_input_hysteresis_enabled(PIN_AVC_RX, true);

    gpio_init(PIN_AVC_TX);
    gpio_set_dir(PIN_AVC_TX, GPIO_OUT);
    gpio_put(PIN_AVC_TX, 0);

    s_rx_offset = pio_add_program(AVC_RX_PIO, &avclan_rx_program);

    irq_set_exclusive_handler(PIO0_IRQ_0, avc_rx_irq);
    irq_set_priority(PIO0_IRQ_0, 0x00);       /* highest */
    pio_set_irq0_source_enabled(AVC_RX_PIO, (enum pio_interrupt_source)(pis_sm0_rx_fifo_not_empty + AVC_RX_SM), true);
    irq_set_enabled(PIO0_IRQ_0, true);

    avclan_set_polarity(AVC_POL_AUTO);
    tx_setup();
}

void avclan_set_polarity(avc_polarity_t pol)
{
    pio_sm_set_enabled(AVC_RX_PIO, AVC_RX_SM, false);
    bool dominant_low;
    switch (pol) {
    case AVC_POL_DOMINANT_HIGH: dominant_low = false; break;
    case AVC_POL_DOMINANT_LOW:  dominant_low = true;  break;
    default:                    dominant_low = detect_dominant_low(); break;
    }
    g_avc.dominant_low = dominant_low;
    s_rx_inverted = dominant_low;
    gpio_set_inover(PIN_AVC_RX, dominant_low ? GPIO_OVERRIDE_INVERT : GPIO_OVERRIDE_NORMAL);
    rx_start();
}

void avclan_set_raw(bool on)
{
    uint32_t save = save_and_disable_interrupts();
    g_avc.raw_enabled = on;
    s_raw_head = s_raw_tail = 0;
    restore_interrupts(save);
}

/* ------------------------------------------------------------------------ */
/* TX                                                                        */
/* ------------------------------------------------------------------------ */

bool avclan_send(const avc_frame_t *f)
{
    uint32_t tmp[AVC_TX_MAX_WORDS];
    if (avc_encode(f, tmp) == 0) return false;
    uint8_t next = (uint8_t)((s_txq_head + 1) % TX_QUEUE);
    if (next == s_txq_tail) { g_avc.tx_queue_full++; return false; }
    s_txq[s_txq_head] = *f;
    s_txq_head = next;
    return true;
}

static bool tx_busy(void)
{
    if (!s_tx_active) return false;
    uint32_t now = time_us_32();
    if ((int32_t)(now - s_tx_end_us) >= 0) {
        if (dma_channel_is_busy((uint)s_tx_dma)) {
            dma_channel_abort((uint)s_tx_dma);
        }
        s_tx_active = false;
        return false;
    }
    return true;
}

bool avclan_bus_busy(void)
{
    return avc_rx_busy(&g_avc_rx) || tx_busy() ||
           (uint32_t)(time_us_32() - s_last_pulse_us) < AVC_TX_IDLE_US;
}

static void tx_tick(void)
{
    bool busy = tx_busy();
    if (s_txq_head == s_txq_tail || busy) return;
    if (avc_rx_busy(&g_avc_rx) || (uint32_t)(time_us_32() - s_last_pulse_us) < AVC_TX_IDLE_US) {
        g_avc.tx_deferred++;
        return;
    }
    const avc_frame_t *f = &s_txq[s_txq_tail];
    uint32_t nbits = avc_encode(f, &s_tx_words[1]);
    s_tx_words[0] = nbits - 1;
    uint32_t nwords = 1 + (nbits + 31) / 32;

    s_tx_last = *f;
    s_tx_last_valid = true;
    s_txq_tail = (uint8_t)((s_txq_tail + 1) % TX_QUEUE);

    /* Ensure GP1 is PIO-controlled (may have been stolen by test commands). */
    pio_gpio_init(AVC_TX_PIO, PIN_AVC_TX);
    pio_sm_set_consecutive_pindirs(AVC_TX_PIO, AVC_TX_SM, PIN_AVC_TX, 1, true);

    /* Reset the TX state machine to program start. The PIO program begins
     * with "out null, 32 side 0" which stalls until the FIFO has data,
     * providing a clean initial barrier for each frame. */
    pio_sm_set_enabled(AVC_TX_PIO, AVC_TX_SM, false);
    pio_sm_clear_fifos(AVC_TX_PIO, AVC_TX_SM);
    pio_sm_restart(AVC_TX_PIO, AVC_TX_SM);
    pio_sm_clkdiv_restart(AVC_TX_PIO, AVC_TX_SM);
    pio_sm_exec(AVC_TX_PIO, AVC_TX_SM, pio_encode_jmp(s_tx_offset));
    pio_sm_set_enabled(AVC_TX_PIO, AVC_TX_SM, true);

    s_tx_active = true;
    s_tx_end_us = time_us_32() + avc_frame_duration_us(nbits) + 200;
    g_avc.tx_frames++;
    dma_channel_set_read_addr((uint)s_tx_dma, s_tx_words, false);
    dma_channel_set_trans_count((uint)s_tx_dma, nwords, true);
}

/* ------------------------------------------------------------------------ */
/* Main-loop side                                                            */
/* ------------------------------------------------------------------------ */

static const char HEX[] = "0123456789ABCDEF";

static void emit_frame(const frame_slot_t *s)
{
    char buf[420];
    char *p = buf;
    const avc_frame_t *f = &s->f;

    bool echo = false;
    if (s_tx_last_valid && avc_frame_equal(f, &s_tx_last) &&
        (int32_t)(s_tx_end_us + 5000 - time_us_32()) > 0) {
        echo = true;
        s_tx_last_valid = false;
    }

    p += sprintf(p, "{\"id\":2,\"ts\":%lu", (unsigned long)s->ts_ms);
    p += out_seq_field(p, 24);
    p += sprintf(p, ",\"d\":{\"m\":\"%03X\",\"s\":\"%03X\",\"c\":%u,\"d\":[",
                 f->master, f->slave, f->control);
    for (int i = 0; i < f->len; i++) {
        if (i) *p++ = ',';
        *p++ = '"'; *p++ = HEX[f->data[i] >> 4]; *p++ = HEX[f->data[i] & 15]; *p++ = '"';
    }
    *p++ = ']';
    if (f->broadcast) { memcpy(p, ",\"b\":1", 6); p += 6; }
    if (f->nak)       { memcpy(p, ",\"nak\":1", 8); p += 8; }
    if (echo)         { memcpy(p, ",\"echo\":1", 9); p += 9; g_avc.frames_echo++; }
    *p++ = '}'; *p++ = '}';

    out_line(buf, (size_t)(p - buf));
    g_avc.frames_out++;
    g_avc.last_frame_ms = s->ts_ms;
    led_event(LED_EV_AVC);
}

static void emit_raw(void)
{
    if (s_raw_head == s_raw_tail) return;
    static char buf[1200];
    char *p = buf;
    p += sprintf(p, "{\"id\":0,\"d\":{\"avc_raw\":[");
    int n = 0;
    while (s_raw_tail != s_raw_head && n < 96) {
        int32_t v = s_raw[s_raw_tail];
        s_raw_tail = (uint16_t)((s_raw_tail + 1) % RAW_RING);
        if (n) *p++ = ',';
        p += sprintf(p, "%ld", (long)v);
        n++;
    }
    p += sprintf(p, "]");
    if (s_raw_dropped) { p += sprintf(p, ",\"dropped\":%lu", (unsigned long)s_raw_dropped); s_raw_dropped = 0; }
    p += sprintf(p, "}}");
    out_line(buf, (size_t)(p - buf));
}

static void emit_errors(void)
{
    static const char *const names[] = { "none", "parity", "length" };
    static const char *const fields[] = { "idle", "bcast", "master", "slave", "control", "length", "data" };
    while (s_err_tail != s_err_head) {
        err_slot_t e = s_err[s_err_tail];
        s_err_tail = (uint8_t)((s_err_tail + 1) % ERR_RING);
        out_json("{\"id\":0,\"d\":{\"avc_err\":\"%s\",\"field\":\"%s\",\"m\":\"%03X\",\"s\":\"%03X\"}}",
                 names[e.err < 3 ? e.err : 0], fields[e.field < 7 ? e.field : 0], e.master, e.slave);
    }
}

void avclan_task(void)
{
    /* Frames first: this is the latency-critical path. */
    while (s_ring_tail != s_ring_head) {
        frame_slot_t s = s_ring[s_ring_tail];
        s_ring_tail = (uint8_t)((s_ring_tail + 1) % FRAME_RING);
        emit_frame(&s);
    }

    /* Abandon a frame whose bits stopped arriving. */
    if (avc_rx_busy(&g_avc_rx)) {
        uint32_t save = save_and_disable_interrupts();
        if (avc_rx_busy(&g_avc_rx) && (uint32_t)(time_us_32() - s_last_pulse_us) > AVC_FRAME_TIMEOUT_US) {
            avc_rx_abort(&g_avc_rx);
            g_avc.timeouts++;
        }
        restore_interrupts(save);
    }

    if (g_avc.debug_errors) emit_errors();
    if (g_avc.raw_enabled) emit_raw();
    tx_tick();
}
