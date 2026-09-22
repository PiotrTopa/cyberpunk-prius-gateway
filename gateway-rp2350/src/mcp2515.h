/* MCP2515 register-level driver (SPI0). */
#pragma once
#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint32_t id;
    bool     ext;
    uint8_t  dlc;
    uint8_t  data[8];
} can_frame_t;

#define MCP_MODE_NORMAL   0x00
#define MCP_MODE_SLEEP    0x20
#define MCP_MODE_LOOPBACK 0x40
#define MCP_MODE_LISTEN   0x60
#define MCP_MODE_CONFIG   0x80

bool     mcp_init(void);                 /* reset, verify, bit timing, filters, listen-only */
bool     mcp_present(void);

uint8_t  mcp_read_reg(uint8_t reg);
void     mcp_write_reg(uint8_t reg, uint8_t val);
void     mcp_bit_modify(uint8_t reg, uint8_t mask, uint8_t val);
uint8_t  mcp_read_status(void);          /* READ STATUS  (0xA0) */
uint8_t  mcp_rx_status(void);            /* RX STATUS    (0xB0) */

bool     mcp_set_mode(uint8_t mode);     /* waits up to ~5 ms for the switch */
uint8_t  mcp_get_mode(void);
const char *mcp_mode_name(uint8_t mode);

/* Enter NORMAL from LISTEN, clearing error counters/flags first. */
bool     mcp_enable_tx(void);

/* Read & release RX buffer 0 or 1. false if empty. */
bool     mcp_read_rx(int buf, can_frame_t *f);
/* true if the INT line is asserted (a receive buffer is full or an error is flagged) */
bool     mcp_int_asserted(void);
/* Discard anything pending in both receive buffers. */
void     mcp_flush_rx(void);

bool     mcp_tx(int txb, const can_frame_t *f);   /* false if that buffer is busy */
bool     mcp_tx_busy(int txb);
void     mcp_tx_abort(int txb);

/*
 * Program acceptance filters so that only `ids` pass (n <= 6: exact match;
 * more: a mask/filter cover). ext=true accepts everything (extended traffic
 * is not filtered). Temporarily enters CONFIG mode; restores the mode.
 */
void     mcp_set_filters(const uint32_t *ids, int n, bool accept_all);

void     mcp_get_errors(uint8_t *tec, uint8_t *rec, uint8_t *eflg);
