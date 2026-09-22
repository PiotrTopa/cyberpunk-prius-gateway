/*
 * AVC-LAN (Toyota IEBus) bit-level codec — platform independent.
 *
 * Wire format (IEBus, after the start bit):
 *
 *   broadcast(1) | master(12) P | slave(12) P A | control(4) P A |
 *   length(8) P A | { data(8) P A } x length
 *
 *   P = even parity bit (XOR of the field bits), A = ACK slot
 *   (0 = slave acknowledged by stretching the pulse, 1 = no ACK).
 *   broadcast bit: 0 = broadcast frame, 1 = individual frame.
 *
 * Bits are pulse-width coded: every bit starts with a DOMINANT pulse
 * (~20 us for '1', ~32 us for '0') inside a ~39 us slot; the start bit
 * is a ~166 us dominant pulse. The decoder therefore consumes
 * *symbols* classified from dominant pulse widths (see avc_classify)
 * and completes a frame on the very last ACK slot, without waiting for
 * bus silence.
 */
#pragma once
#include <stdint.h>
#include <stdbool.h>

#define AVC_MAX_DATA 32

typedef struct {
    uint16_t master;
    uint16_t slave;
    uint8_t  control;
    uint8_t  len;
    uint8_t  data[AVC_MAX_DATA];
    bool     broadcast;   /* broadcast bit == 0 */
    bool     nak;         /* individual frame with at least one ACK slot read as NAK */
} avc_frame_t;

typedef enum {
    AVC_SYM_GLITCH = 0,   /* dominant pulse too short to be a bit: ignored */
    AVC_SYM_ONE,
    AVC_SYM_ZERO,
    AVC_SYM_START,
    AVC_SYM_STUCK,        /* far longer than a start bit: bus fault, ignored */
} avc_symbol_t;

typedef struct {
    uint16_t glitch_us;     /* width <  glitch_us    -> GLITCH  (default 6)   */
    uint16_t one_max_us;    /* width <  one_max_us   -> ONE     (default 26)  */
    uint16_t zero_max_us;   /* width <  zero_max_us  -> ZERO    (default 100) */
    uint16_t start_max_us;  /* width <  start_max_us -> START   (default 400) else STUCK */
} avc_thresholds_t;

#define AVC_THRESHOLDS_DEFAULT { 6, 26, 100, 400 }

avc_symbol_t avc_classify(const avc_thresholds_t *t, uint32_t dominant_us);

typedef enum { AVC_RX_NONE = 0, AVC_RX_FRAME, AVC_RX_ERROR } avc_rx_result_t;

typedef enum {
    AVC_ERR_NONE = 0,
    AVC_ERR_PARITY,
    AVC_ERR_LENGTH,
} avc_rx_error_t;

/* Field identifiers (also used for error reporting). */
enum {
    AVC_F_IDLE = 0,
    AVC_F_BCAST,
    AVC_F_MASTER,
    AVC_F_SLAVE,
    AVC_F_CONTROL,
    AVC_F_LENGTH,
    AVC_F_DATA,
};

typedef struct {
    uint8_t  state;        /* AVC_F_* */
    uint8_t  sub;          /* 0 = value bits, 1 = parity slot, 2 = ack slot */
    uint8_t  bit_i;
    uint8_t  width;
    uint16_t acc;
    uint8_t  parity;
    uint8_t  data_i;
    avc_frame_t f;

    avc_rx_error_t last_error;
    uint8_t  err_field;

    /* counters */
    uint32_t frames;
    uint32_t parity_errors;
    uint32_t length_errors;
    uint32_t aborted;      /* frame interrupted by a new start bit or a timeout */
    uint32_t stray_bits;   /* data bits seen while idle (no start bit) */
    uint32_t glitches;
} avc_rx_t;

void            avc_rx_init(avc_rx_t *rx);
avc_rx_result_t avc_rx_feed(avc_rx_t *rx, avc_symbol_t sym);
bool            avc_rx_busy(const avc_rx_t *rx);
void            avc_rx_abort(avc_rx_t *rx);

/*
 * Encoder: bit stream that follows the start bit, MSB-first, packed into
 * 32-bit words (unused tail bits are zero). ACK slots are emitted as '1'
 * (the addressed slave stretches them on the wire). Returns the number of
 * bits, or 0 if the frame is not encodable.
 */
#define AVC_TX_MAX_BITS  (1 + 13 + 14 + 6 + 10 + AVC_MAX_DATA * 10)   /* 364 */
#define AVC_TX_MAX_WORDS ((AVC_TX_MAX_BITS + 31) / 32)               /* 12  */

uint32_t avc_encode(const avc_frame_t *f, uint32_t words[AVC_TX_MAX_WORDS]);

/* Frame duration on the wire in microseconds (start bit included). */
uint32_t avc_frame_duration_us(uint32_t nbits);

bool avc_frame_equal(const avc_frame_t *a, const avc_frame_t *b);
