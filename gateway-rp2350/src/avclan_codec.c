#include "avclan_codec.h"
#include <string.h>

avc_symbol_t avc_classify(const avc_thresholds_t *t, uint32_t dominant_us)
{
    if (dominant_us < t->glitch_us)    return AVC_SYM_GLITCH;
    if (dominant_us < t->one_max_us)   return AVC_SYM_ONE;
    if (dominant_us < t->zero_max_us)  return AVC_SYM_ZERO;
    if (dominant_us < t->start_max_us) return AVC_SYM_START;
    return AVC_SYM_STUCK;
}

static void begin_field(avc_rx_t *rx, uint8_t state, uint8_t width)
{
    rx->state  = state;
    rx->width  = width;
    rx->sub    = 0;
    rx->bit_i  = 0;
    rx->acc    = 0;
    rx->parity = 0;
}

void avc_rx_init(avc_rx_t *rx)
{
    memset(rx, 0, sizeof(*rx));
    rx->state = AVC_F_IDLE;
}

bool avc_rx_busy(const avc_rx_t *rx)
{
    return rx->state != AVC_F_IDLE;
}

void avc_rx_abort(avc_rx_t *rx)
{
    if (rx->state != AVC_F_IDLE) {
        rx->aborted++;
        rx->state = AVC_F_IDLE;
    }
}

static avc_rx_result_t fail(avc_rx_t *rx, avc_rx_error_t err)
{
    rx->last_error = err;
    rx->err_field  = rx->state;
    if (err == AVC_ERR_PARITY) rx->parity_errors++;
    else                       rx->length_errors++;
    rx->state = AVC_F_IDLE;
    return AVC_RX_ERROR;
}

static avc_rx_result_t complete(avc_rx_t *rx)
{
    rx->state = AVC_F_IDLE;
    rx->frames++;
    return AVC_RX_FRAME;
}

avc_rx_result_t avc_rx_feed(avc_rx_t *rx, avc_symbol_t sym)
{
    switch (sym) {
    case AVC_SYM_START:
        /* A start bit always resynchronises, even mid-frame. */
        if (rx->state != AVC_F_IDLE) rx->aborted++;
        memset(&rx->f, 0, sizeof(rx->f));
        begin_field(rx, AVC_F_BCAST, 1);
        return AVC_RX_NONE;
    case AVC_SYM_GLITCH:
        rx->glitches++;
        return AVC_RX_NONE;
    case AVC_SYM_STUCK:
        avc_rx_abort(rx);
        return AVC_RX_NONE;
    default:
        break;
    }

    if (rx->state == AVC_F_IDLE) {
        rx->stray_bits++;
        return AVC_RX_NONE;
    }

    const uint8_t bit = (sym == AVC_SYM_ONE) ? 1 : 0;

    if (rx->state == AVC_F_BCAST) {
        rx->f.broadcast = (bit == 0);
        begin_field(rx, AVC_F_MASTER, 12);
        return AVC_RX_NONE;
    }

    if (rx->sub == 0) {                       /* value bits */
        rx->acc = (uint16_t)((rx->acc << 1) | bit);
        rx->parity ^= bit;
        if (++rx->bit_i == rx->width) rx->sub = 1;
        return AVC_RX_NONE;
    }

    if (rx->sub == 1) {                       /* parity slot */
        if (bit != rx->parity) return fail(rx, AVC_ERR_PARITY);
        switch (rx->state) {
        case AVC_F_MASTER:
            rx->f.master = rx->acc;
            begin_field(rx, AVC_F_SLAVE, 12);  /* master has no ACK slot */
            return AVC_RX_NONE;
        case AVC_F_SLAVE:   rx->f.slave   = rx->acc; break;
        case AVC_F_CONTROL: rx->f.control = (uint8_t)rx->acc; break;
        case AVC_F_LENGTH:
            if (rx->acc > AVC_MAX_DATA) return fail(rx, AVC_ERR_LENGTH);
            rx->f.len = (uint8_t)rx->acc;
            break;
        case AVC_F_DATA:
            rx->f.data[rx->data_i++] = (uint8_t)rx->acc;
            break;
        default:
            break;
        }
        rx->sub = 2;
        return AVC_RX_NONE;
    }

    /* sub == 2: ACK slot */
    if (bit && !rx->f.broadcast) rx->f.nak = true;
    switch (rx->state) {
    case AVC_F_SLAVE:   begin_field(rx, AVC_F_CONTROL, 4); return AVC_RX_NONE;
    case AVC_F_CONTROL: begin_field(rx, AVC_F_LENGTH, 8);  return AVC_RX_NONE;
    case AVC_F_LENGTH:
        if (rx->f.len == 0) return complete(rx);
        rx->data_i = 0;
        begin_field(rx, AVC_F_DATA, 8);
        return AVC_RX_NONE;
    case AVC_F_DATA:
        if (rx->data_i >= rx->f.len) return complete(rx);
        begin_field(rx, AVC_F_DATA, 8);
        return AVC_RX_NONE;
    default:
        rx->state = AVC_F_IDLE;
        return AVC_RX_NONE;
    }
}

/* ------------------------------------------------------------------ */
/* Encoder                                                             */
/* ------------------------------------------------------------------ */

typedef struct {
    uint32_t *w;
    uint32_t  n;
} bitwriter_t;

static void put_bit(bitwriter_t *bw, uint32_t bit)
{
    if (bit) bw->w[bw->n >> 5] |= 0x80000000u >> (bw->n & 31);
    bw->n++;
}

static void put_field(bitwriter_t *bw, uint32_t value, int width, bool ack)
{
    uint32_t parity = 0;
    for (int i = width - 1; i >= 0; i--) {
        uint32_t b = (value >> i) & 1u;
        parity ^= b;
        put_bit(bw, b);
    }
    put_bit(bw, parity);
    if (ack) put_bit(bw, 1);
}

uint32_t avc_encode(const avc_frame_t *f, uint32_t words[AVC_TX_MAX_WORDS])
{
    if (f->master > 0xFFF || f->slave > 0xFFF || f->control > 0xF || f->len > AVC_MAX_DATA)
        return 0;

    memset(words, 0, sizeof(uint32_t) * AVC_TX_MAX_WORDS);
    bitwriter_t bw = { words, 0 };

    put_bit(&bw, f->broadcast ? 0 : 1);
    put_field(&bw, f->master, 12, false);
    put_field(&bw, f->slave, 12, true);
    put_field(&bw, f->control, 4, true);
    put_field(&bw, f->len, 8, true);
    for (int i = 0; i < f->len; i++) put_field(&bw, f->data[i], 8, true);
    return bw.n;
}

uint32_t avc_frame_duration_us(uint32_t nbits)
{
    return 166 + 19 + nbits * 39;
}

bool avc_frame_equal(const avc_frame_t *a, const avc_frame_t *b)
{
    return a->master == b->master && a->slave == b->slave &&
           a->control == b->control && a->len == b->len &&
           a->broadcast == b->broadcast &&
           memcmp(a->data, b->data, a->len) == 0;
}
