/*
 * Solicited-only CAN: request/response queries and periodic subscriptions,
 * with ISO 15765-2 (ISO-TP) reassembly. Nothing is streamed passively.
 * Fully non-blocking; call can_sol_task() from the main loop.
 */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "mcp2515.h"

#define CAN_MAX_SUBS      16
#define CAN_MAX_RESP_IDS  8
#define CAN_REQ_QUEUE     8
#define CAN_ISOTP_MAX     256

typedef struct {
    uint32_t req_id;
    bool     ext;
    uint8_t  req_len;
    uint8_t  req[8];
    uint8_t  nresp;
    uint32_t resp[CAN_MAX_RESP_IDS];
    uint32_t timeout_ms;
    bool     isotp;
} can_query_t;

typedef struct {
    bool        used;
    can_query_t q;
    uint32_t    interval_ms;
    uint32_t    last_poll_ms;
    uint32_t    ok;
    uint32_t    timeouts;
} can_sub_t;

typedef struct {
    bool     ready;             /* controller initialised */
    bool     tx_enabled;        /* NORMAL mode */
    uint32_t requests;          /* jobs started */
    uint32_t responses;
    uint32_t timeouts;
    uint32_t tx_errors;
    uint32_t isotp_errors;
    uint32_t rx_other;          /* frames not matching the active job */
    uint32_t raw_tx;
    uint32_t last_activity_ms;
    uint8_t  isotp_stmin_ms;    /* STmin we ask ECUs for (default 5) */
    uint8_t  isotp_retries;     /* default 1 */
    uint16_t inter_request_gap_ms; /* default 5 */
    bool     isotp_debug;
} can_sol_stats_t;

extern can_sol_stats_t g_can;
extern can_sub_t       g_can_subs[CAN_MAX_SUBS];

void can_sol_init(void);
void can_sol_task(void);

/* Host actions (see PROTOCOL / README). Each emits its own NDJSON reply. */
void can_sol_action_tx(const can_frame_t *f);
void can_sol_action_req(const can_query_t *q);
void can_sol_action_sub(int slot, const can_query_t *q, uint32_t interval_ms);
void can_sol_action_unsub(int slot);          /* slot < 0: all */
void can_sol_action_list(void);
void can_sol_action_mode(bool normal);

/* Periodic diagnostics line ({"can_diag":...}). */
void can_sol_emit_diag(void);
