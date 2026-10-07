#include "can_sol.h"
#include "config.h"
#include "out.h"
#include "led.h"
#include "pico/stdlib.h"
#include <string.h>
#include <stdio.h>
#include <stdarg.h>

can_sol_stats_t g_can = { .isotp_stmin_ms = 5, .isotp_retries = 1, .inter_request_gap_ms = 5 };
can_sub_t       g_can_subs[CAN_MAX_SUBS];

#define TXB_ENGINE 0
#define TXB_RAW    1

/* ---- one-shot request queue -------------------------------------------- */
static can_query_t s_reqq[CAN_REQ_QUEUE];
static uint8_t     s_reqq_head, s_reqq_tail;

/* ---- engine ------------------------------------------------------------ */
typedef enum { ENG_IDLE = 0, ENG_SENDING, ENG_WAIT_RESP, ENG_WAIT_CF, ENG_GAP } eng_state_t;

static struct {
    eng_state_t state;
    can_query_t q;
    int         slot;            /* subscription slot or -1 for a one-shot request */
    uint8_t     attempt;
    uint32_t    start_ms;
    uint32_t    deadline_ms;
    uint32_t    gap_until_ms;
    /* ISO-TP */
    uint32_t    rx_id;
    uint32_t    fc_target;
    uint16_t    total;
    uint16_t    received;
    uint8_t     expected_seq;
    uint8_t     buf[CAN_ISOTP_MAX];
} s_eng;

static uint8_t  s_rr;                    /* round-robin start slot */
static uint32_t s_filter_ids[CAN_MAX_SUBS * CAN_MAX_RESP_IDS + CAN_MAX_RESP_IDS];
static int      s_filter_n = -1;
static bool     s_filter_all;

/* ---- sniff (opt-in pass-through) ---------------------------------------- */
static uint32_t s_sn_ids[CAN_SNIFF_MAX_IDS];
static int      s_sn_n;                      /* 0 = every id */
static uint8_t  s_sn_last[2048][9];          /* [std id] = dlc+1 (0 = unseen), data */
static uint32_t s_sn_eflg_ms;

/* ------------------------------------------------------------------------ */

static void ilog(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void ilog(const char *fmt, ...)
{
    if (!g_can.isotp_debug) return;
    char msg[160];
    va_list ap; va_start(ap, fmt); vsnprintf(msg, sizeof(msg), fmt, ap); va_end(ap);
    out_json("{\"id\":0,\"d\":{\"isotp\":\"%s\"}}", msg);
}

static bool ensure_tx_enabled(void)
{
    if (!g_can.ready) { out_sys_err("CAN_OFFLINE"); return false; }
    if (g_can.tx_enabled) return true;
    if (!mcp_enable_tx()) { out_sys_err("CAN_MODE_SWITCH_FAIL"); return false; }
    g_can.tx_enabled = true;
    return true;
}

/* Recompute the hardware acceptance filters from every live query.
 * `extra` is a query about to start (not yet visible through the engine state). */
static void refresh_filters(bool force, const can_query_t *extra)
{
    if (!g_can.ready) return;
    if (g_can.sniff) {             /* pass-through: hardware accepts everything */
        if (force || !s_filter_all || s_filter_n != 0) {
            s_filter_n = 0;
            s_filter_all = true;
            mcp_set_filters(NULL, 0, true);
        }
        return;
    }
    uint32_t ids[sizeof(s_filter_ids) / sizeof(s_filter_ids[0])];
    int n = 0;
    bool all = false;

    #define ADD_QUERY(qp) do { \
        if ((qp)->ext) all = true; \
        for (int _i = 0; _i < (qp)->nresp && n < (int)(sizeof(ids)/sizeof(ids[0])); _i++) { \
            uint32_t _v = (qp)->resp[_i]; bool _dup = false; \
            for (int _k = 0; _k < n; _k++) if (ids[_k] == _v) { _dup = true; break; } \
            if (!_dup) ids[n++] = _v; \
        } } while (0)

    for (int i = 0; i < CAN_MAX_SUBS; i++) if (g_can_subs[i].used) ADD_QUERY(&g_can_subs[i].q);
    for (uint8_t i = s_reqq_tail; i != s_reqq_head; i = (uint8_t)((i + 1) % CAN_REQ_QUEUE)) ADD_QUERY(&s_reqq[i]);
    if (s_eng.state != ENG_IDLE && s_eng.state != ENG_GAP) ADD_QUERY(&s_eng.q);
    if (extra) ADD_QUERY(extra);
    #undef ADD_QUERY

    if (n == 0) {   /* nothing pending: fall back to the OBD range */
        for (int i = 0; i < 8; i++) ids[n++] = 0x7E8u + (uint32_t)i;
    }

    bool same = !force && (all == s_filter_all) && (n == s_filter_n) &&
                memcmp(ids, s_filter_ids, sizeof(uint32_t) * (size_t)n) == 0;
    if (same) return;

    memcpy(s_filter_ids, ids, sizeof(uint32_t) * (size_t)n);
    s_filter_n = n;
    s_filter_all = all;
    mcp_set_filters(ids, n, all);
}

void can_sol_init(void)
{
    memset(g_can_subs, 0, sizeof(g_can_subs));
    memset(&s_eng, 0, sizeof(s_eng));
    g_can.ready = mcp_init();
    g_can.tx_enabled = false;
    led_set_can_ok(g_can.ready);
    if (g_can.ready) refresh_filters(true, NULL);
}

/* ------------------------------------------------------------------------ */
/* Emission                                                                  */
/* ------------------------------------------------------------------------ */

static void emit_response(uint32_t rx_id, const uint8_t *data, int len)
{
    static char buf[1400];
    char *p = buf;
    p += sprintf(p, "{\"id\":1,\"ts\":%lu", (unsigned long)now_ms());
    p += out_seq_field(p, 24);
    if (s_eng.slot >= 0) p += sprintf(p, ",\"d\":{\"a\":\"sub\",\"slot\":%d", s_eng.slot);
    else                 p += sprintf(p, ",\"d\":{\"a\":\"resp\"");
    p += sprintf(p, ",\"i\":\"0x%lX\",\"d\":[", (unsigned long)rx_id);
    for (int i = 0; i < len; i++) p += sprintf(p, i ? ",%u" : "%u", data[i]);
    p += sprintf(p, "]}}");
    out_line(buf, (size_t)(p - buf));
    g_can.responses++;
    g_can.last_activity_ms = now_ms();
    led_event(LED_EV_CAN);
}

static void emit_req_error(const char *err)
{
    /* "i" carries the first expected response id so the host can attribute the failure. */
    out_json("{\"id\":1,\"d\":{\"a\":\"resp\",\"err\":\"%s\",\"i\":\"0x%lX\",\"req\":\"0x%lX\"}}",
             err, (unsigned long)(s_eng.q.nresp ? s_eng.q.resp[0] : 0), (unsigned long)s_eng.q.req_id);
}

/* ------------------------------------------------------------------------ */
/* Engine                                                                    */
/* ------------------------------------------------------------------------ */

static void job_finish(bool ok, const char *err)
{
    if (s_eng.slot >= 0 && g_can_subs[s_eng.slot].used) {
        if (ok) g_can_subs[s_eng.slot].ok++;
        else    g_can_subs[s_eng.slot].timeouts++;
    } else if (s_eng.slot < 0 && !ok) {
        emit_req_error(err);
    }
    if (!ok) {
        if (strcmp(err, "TIMEOUT") == 0) g_can.timeouts++;
    }
    s_eng.state = ENG_GAP;
    s_eng.gap_until_ms = now_ms() + g_can.inter_request_gap_ms;
}

static bool job_send_request(void)
{
    can_frame_t f = { .id = s_eng.q.req_id, .ext = s_eng.q.ext, .dlc = 8 };
    memset(f.data, 0, 8);
    memcpy(f.data, s_eng.q.req, s_eng.q.req_len);
    /* OBD/UDS requests are conventionally padded to 8 bytes; the host already
     * sends 8 bytes, shorter arrays are padded with zeros here. */
    if (mcp_tx_busy(TXB_ENGINE)) mcp_tx_abort(TXB_ENGINE);
    mcp_flush_rx();
    ilog("TX REQ 0x%lX len=%u attempt=%u", (unsigned long)f.id, s_eng.q.req_len, s_eng.attempt + 1);
    if (!mcp_tx(TXB_ENGINE, &f)) { g_can.tx_errors++; return false; }
    s_eng.state = ENG_SENDING;
    s_eng.start_ms = now_ms();
    s_eng.deadline_ms = s_eng.start_ms + s_eng.q.timeout_ms;
    g_can.requests++;
    led_event(LED_EV_CAN);
    return true;
}

static void job_start(const can_query_t *q, int slot)
{
    s_eng.q = *q;
    s_eng.slot = slot;
    s_eng.attempt = 0;
    s_eng.received = s_eng.total = 0;
    refresh_filters(false, &s_eng.q);
    if (!job_send_request()) job_finish(false, "CAN_TX_FULL");
}

static bool pick_job(void)
{
    if (!g_can.tx_enabled) return false;
    uint32_t now = now_ms();

    if (s_reqq_tail != s_reqq_head) {
        can_query_t q = s_reqq[s_reqq_tail];
        s_reqq_tail = (uint8_t)((s_reqq_tail + 1) % CAN_REQ_QUEUE);
        job_start(&q, -1);
        return true;
    }
    for (int i = 0; i < CAN_MAX_SUBS; i++) {
        int slot = (s_rr + i) % CAN_MAX_SUBS;
        can_sub_t *s = &g_can_subs[slot];
        if (!s->used) continue;
        if ((uint32_t)(now - s->last_poll_ms) >= s->interval_ms || s->last_poll_ms == 0) {
            s->last_poll_ms = now;
            s_rr = (uint8_t)((slot + 1) % CAN_MAX_SUBS);
            job_start(&s->q, slot);
            return true;
        }
    }
    return false;
}

static bool id_expected(uint32_t id)
{
    for (int i = 0; i < s_eng.q.nresp; i++) if (s_eng.q.resp[i] == id) return true;
    return false;
}

static uint32_t fc_target_for(uint32_t rx_id)
{
    uint32_t tx = s_eng.q.req_id;
    if (tx == 0x7DF) return rx_id - 8;
    if (tx >= 0x7E0 && tx <= 0x7E7) return tx;
    if (rx_id >= 0x7E8 && rx_id <= 0x7EF) return rx_id - 8;
    return tx;
}

static void retry_or_fail(const char *err)
{
    g_can.isotp_errors++;
    if (s_eng.attempt < g_can.isotp_retries) {
        s_eng.attempt++;
        s_eng.received = s_eng.total = 0;
        ilog("retry after %s", err);
        if (job_send_request()) return;
    }
    job_finish(false, err);
}

static void handle_frame(const can_frame_t *f)
{
    if (!id_expected(f->id) || f->dlc == 0) { g_can.rx_other++; return; }

    if (!s_eng.q.isotp) {
        emit_response(f->id, f->data, f->dlc);
        job_finish(true, NULL);
        return;
    }

    uint8_t pci = f->data[0] >> 4;
    if (s_eng.state == ENG_WAIT_RESP) {
        if (pci == 0) {                                  /* single frame */
            uint8_t len = f->data[0] & 0x0F;
            if (len == 0 || len > 7 || len > f->dlc - 1) { g_can.rx_other++; return; }
            ilog("RX SF 0x%lX len=%u", (unsigned long)f->id, len);
            emit_response(f->id, f->data + 1, len);
            job_finish(true, NULL);
        } else if (pci == 1) {                           /* first frame */
            uint16_t total = (uint16_t)(((f->data[0] & 0x0F) << 8) | f->data[1]);
            if (total == 0 || total > CAN_ISOTP_MAX) { retry_or_fail("ISOTP_LEN"); return; }
            s_eng.rx_id = f->id;
            s_eng.total = total;
            s_eng.received = 0;
            int n = f->dlc - 2; if (n > 6) n = 6;
            memcpy(s_eng.buf, f->data + 2, (size_t)n);
            s_eng.received = (uint16_t)n;
            s_eng.expected_seq = 1;
            s_eng.fc_target = fc_target_for(f->id);
            can_frame_t fc = { .id = s_eng.fc_target, .ext = s_eng.q.ext, .dlc = 8,
                               .data = { 0x30, 0x00, g_can.isotp_stmin_ms, 0, 0, 0, 0, 0 } };
            ilog("RX FF 0x%lX total=%u -> FC 0x%lX", (unsigned long)f->id, total, (unsigned long)fc.id);
            if (mcp_tx_busy(TXB_ENGINE)) mcp_tx_abort(TXB_ENGINE);
            if (!mcp_tx(TXB_ENGINE, &fc)) { g_can.tx_errors++; retry_or_fail("FC_TX_FAIL"); return; }
            s_eng.state = ENG_WAIT_CF;
        } else {
            g_can.rx_other++;
        }
        return;
    }

    /* ENG_WAIT_CF */
    if (f->id != s_eng.rx_id || pci != 2) { g_can.rx_other++; return; }
    uint8_t seq = f->data[0] & 0x0F;
    if (seq != s_eng.expected_seq) {
        if (seq == ((s_eng.expected_seq - 1) & 0x0F)) return;   /* duplicate */
        ilog("CF seq %u expected %u", seq, s_eng.expected_seq);
        retry_or_fail("ISOTP_SEQ");
        return;
    }
    int n = f->dlc - 1; if (n > 7) n = 7;
    if (s_eng.received + n > s_eng.total) n = s_eng.total - s_eng.received;
    memcpy(s_eng.buf + s_eng.received, f->data + 1, (size_t)n);
    s_eng.received = (uint16_t)(s_eng.received + n);
    s_eng.expected_seq = (uint8_t)((s_eng.expected_seq + 1) & 0x0F);
    if (s_eng.received >= s_eng.total) {
        ilog("complete %u bytes", s_eng.total);
        emit_response(s_eng.rx_id, s_eng.buf, s_eng.total);
        job_finish(true, NULL);
    }
}

static bool sniff_wanted(const can_frame_t *f)
{
    if (s_sn_n > 0) {
        bool hit = false;
        for (int i = 0; i < s_sn_n; i++) if (s_sn_ids[i] == f->id) { hit = true; break; }
        if (!hit) return false;
    }
    if (g_can.sniff_chg && !f->ext && f->id < 2048) {
        uint8_t *last = s_sn_last[f->id];
        if (last[0] == f->dlc + 1 && memcmp(last + 1, f->data, f->dlc) == 0) return false;
        last[0] = (uint8_t)(f->dlc + 1);
        memcpy(last + 1, f->data, f->dlc);
    }
    return true;
}

static void sniff_emit(const can_frame_t *f)
{
    char buf[128];
    int n = snprintf(buf, sizeof(buf), "{\"id\":1,\"ts\":%lu", (unsigned long)now_ms());
    n += out_seq_field(buf + n, sizeof(buf) - (size_t)n);
    n += snprintf(buf + n, sizeof(buf) - (size_t)n, ",\"d\":{\"a\":\"sniff\",\"t\":%lu,\"i\":\"0x%lX\"%s,\"x\":\"",
                  (unsigned long)time_us_32(), (unsigned long)f->id, f->ext ? ",\"e\":true" : "");
    for (int i = 0; i < f->dlc; i++) n += snprintf(buf + n, sizeof(buf) - (size_t)n, "%02X", f->data[i]);
    n += snprintf(buf + n, sizeof(buf) - (size_t)n, "\"}}");
    if (out_line(buf, (size_t)n)) g_can.sniff_out++;
}

static void sniff_task(void)
{
    can_frame_t f;
    for (int i = 0; i < 8; i++) {
        if (!mcp_read_rx(0, &f) && !mcp_read_rx(1, &f)) break;
        g_can.sniff_rx++;
        if (sniff_wanted(&f)) sniff_emit(&f);
    }
    uint32_t now = now_ms();
    if (now - s_sn_eflg_ms >= 100) {            /* overflow / error flags, 10 Hz */
        s_sn_eflg_ms = now;
        uint8_t eflg = mcp_read_reg(0x2D /*EFLG*/);
        if (eflg & 0xC0) { g_can.sniff_ovr++; mcp_bit_modify(0x2D, 0xC0, 0x00); }
        if (mcp_int_asserted() && !mcp_read_rx(0, &f) && !mcp_read_rx(1, &f))
            mcp_bit_modify(0x2C /*CANINTF*/, 0xFC, 0x00);
    }
}

void can_sol_task(void)
{
    if (!g_can.ready) return;
    if (g_can.sniff) { sniff_task(); return; }
    uint32_t now = now_ms();

    switch (s_eng.state) {
    case ENG_IDLE:
        pick_job();
        break;

    case ENG_GAP:
        if ((int32_t)(now - s_eng.gap_until_ms) >= 0) { s_eng.state = ENG_IDLE; pick_job(); }
        break;

    case ENG_SENDING:
        if (!mcp_tx_busy(TXB_ENGINE)) {
            s_eng.state = ENG_WAIT_RESP;
        } else if ((int32_t)(now - s_eng.deadline_ms) >= 0) {
            mcp_tx_abort(TXB_ENGINE);
            g_can.tx_errors++;
            ilog("TX timeout");
            job_finish(false, "TX_TIMEOUT");
        }
        break;

    case ENG_WAIT_RESP:
    case ENG_WAIT_CF:
        if (mcp_int_asserted()) {
            can_frame_t f;
            for (int i = 0; i < 4 && s_eng.state != ENG_GAP; i++) {
                if (mcp_read_rx(0, &f)) handle_frame(&f);
                else if (mcp_read_rx(1, &f)) handle_frame(&f);
                else break;
            }
            /* INT may also be an error flag: clear it so it does not stick. */
            if (mcp_int_asserted() && !mcp_read_rx(0, &f) && !mcp_read_rx(1, &f))
                mcp_bit_modify(0x2C /*CANINTF*/, 0xFC, 0x00);
        }
        if (s_eng.state != ENG_GAP && (int32_t)(now - s_eng.deadline_ms) >= 0) {
            if (s_eng.q.isotp && s_eng.state == ENG_WAIT_CF) {
                ilog("CF timeout %u/%u", s_eng.received, s_eng.total);
                retry_or_fail("TIMEOUT");
            } else {
                ilog("response timeout");
                job_finish(false, "TIMEOUT");
            }
        }
        break;
    }

    /* Keep the receive buffers from sitting full while idle (stray traffic
     * that slipped through the filters would otherwise pin INT low). */
    if ((s_eng.state == ENG_IDLE || s_eng.state == ENG_GAP) && mcp_int_asserted()) {
        can_frame_t f;
        if (!mcp_read_rx(0, &f) && !mcp_read_rx(1, &f)) mcp_bit_modify(0x2C, 0xFC, 0x00);
        else g_can.rx_other++;
    }
}

/* ------------------------------------------------------------------------ */
/* Host actions                                                              */
/* ------------------------------------------------------------------------ */

void can_sol_action_tx(const can_frame_t *f)
{
    if (g_can.sniff) { out_sys_err("CAN_SNIFF_ACTIVE"); return; }
    if (!ensure_tx_enabled()) return;
    if (!mcp_tx(TXB_RAW, f)) { out_sys_err("CAN_TX_FULL"); return; }
    g_can.raw_tx++;
    led_event(LED_EV_CAN);
}

void can_sol_action_req(const can_query_t *q)
{
    if (g_can.sniff) { out_sys_err("CAN_SNIFF_ACTIVE"); return; }
    if (!ensure_tx_enabled()) return;
    uint8_t next = (uint8_t)((s_reqq_head + 1) % CAN_REQ_QUEUE);
    if (next == s_reqq_tail) { out_sys_err("CAN_REQ_QUEUE_FULL"); return; }
    s_reqq[s_reqq_head] = *q;
    s_reqq_head = next;
}

void can_sol_action_sub(int slot, const can_query_t *q, uint32_t interval_ms)
{
    if (slot < 0 || slot >= CAN_MAX_SUBS) { out_sys_err("INVALID_SLOT"); return; }
    if (g_can.sniff) { out_sys_err("CAN_SNIFF_ACTIVE"); return; }
    if (!ensure_tx_enabled()) return;
    can_sub_t *s = &g_can_subs[slot];
    s->q = *q;
    s->interval_ms = interval_ms ? interval_ms : 1000;
    s->last_poll_ms = 0;
    s->ok = s->timeouts = 0;
    s->used = true;
    refresh_filters(false, NULL);
    out_json("{\"id\":0,\"d\":{\"msg\":\"SUB_OK\",\"slot\":%d}}", slot);
}

void can_sol_action_unsub(int slot)
{
    if (slot < 0) {
        for (int i = 0; i < CAN_MAX_SUBS; i++) g_can_subs[i].used = false;
        refresh_filters(false, NULL);
        out_json("{\"id\":0,\"d\":{\"msg\":\"UNSUB_ALL\"}}");
        return;
    }
    if (slot >= CAN_MAX_SUBS || !g_can_subs[slot].used) { out_sys_err("SLOT_NOT_FOUND"); return; }
    g_can_subs[slot].used = false;
    refresh_filters(false, NULL);
    out_json("{\"id\":0,\"d\":{\"msg\":\"UNSUB_OK\",\"slot\":%d}}", slot);
}

void can_sol_action_list(void)
{
    static char buf[2048];
    size_t cap = sizeof(buf);
    int n = snprintf(buf, cap, "{\"id\":0,\"d\":{\"subs\":[");
    bool first = true;
    for (int i = 0; i < CAN_MAX_SUBS && (size_t)n < cap - 8; i++) {
        can_sub_t *s = &g_can_subs[i];
        if (!s->used) continue;
        n += snprintf(buf + n, cap - (size_t)n,
                      "%s{\"slot\":%d,\"i\":\"0x%lX\",\"int\":%lu,\"ok\":%lu,\"to\":%lu%s}",
                      first ? "" : ",", i, (unsigned long)s->q.req_id, (unsigned long)s->interval_ms,
                      (unsigned long)s->ok, (unsigned long)s->timeouts, s->q.isotp ? ",\"isotp\":true" : "");
        first = false;
    }
    if ((size_t)n > cap - 8) n = (int)cap - 8;
    n += snprintf(buf + n, cap - (size_t)n, "]}}");
    out_line(buf, (size_t)n);
}

void can_sol_action_mode(bool normal)
{
    if (!g_can.ready) { out_sys_err("CAN_OFFLINE"); return; }
    if (normal) {
        if (mcp_enable_tx()) { g_can.tx_enabled = true; out_json("{\"id\":0,\"d\":{\"msg\":\"CAN_MODE\",\"m\":\"NORMAL\"}}"); }
        else out_sys_err("MODE_SWITCH_FAIL");
    } else {
        /* abandon any job, drop subscriptions (v2.x behaviour) */
        s_eng.state = ENG_IDLE;
        s_reqq_head = s_reqq_tail = 0;
        for (int i = 0; i < CAN_MAX_SUBS; i++) g_can_subs[i].used = false;
        if (mcp_set_mode(MCP_MODE_LISTEN)) { g_can.tx_enabled = false; out_json("{\"id\":0,\"d\":{\"msg\":\"CAN_MODE\",\"m\":\"LISTEN\"}}"); }
        else out_sys_err("MODE_SWITCH_FAIL");
        refresh_filters(false, NULL);
    }
}

void can_sol_action_sniff(bool on, bool chg, const uint32_t *ids, int n)
{
    if (!g_can.ready) { out_sys_err("CAN_OFFLINE"); return; }
    if (on) {
        /* same teardown as "mode listen": abandon jobs, drop subscriptions */
        s_eng.state = ENG_IDLE;
        s_reqq_head = s_reqq_tail = 0;
        for (int i = 0; i < CAN_MAX_SUBS; i++) g_can_subs[i].used = false;
        if (!mcp_set_mode(MCP_MODE_LISTEN)) { out_sys_err("MODE_SWITCH_FAIL"); return; }
        g_can.tx_enabled = false;
        if (n > CAN_SNIFF_MAX_IDS) n = CAN_SNIFF_MAX_IDS;
        s_sn_n = n > 0 ? n : 0;
        for (int i = 0; i < s_sn_n; i++) s_sn_ids[i] = ids[i];
        memset(s_sn_last, 0, sizeof(s_sn_last));
        g_can.sniff_chg = chg;
        g_can.sniff_rx = g_can.sniff_out = g_can.sniff_ovr = 0;
        g_can.sniff = true;
        refresh_filters(true, NULL);
        mcp_flush_rx();
    } else {
        g_can.sniff = false;
        s_filter_n = -1;
        refresh_filters(true, NULL);
        mcp_flush_rx();
    }
    out_json("{\"id\":0,\"d\":{\"msg\":\"CAN_SNIFF\",\"on\":%s,\"chg\":%s,\"ids\":%d}}",
             g_can.sniff ? "true" : "false", g_can.sniff_chg ? "true" : "false", s_sn_n);
}

void can_sol_emit_diag(void)
{
    if (!g_can.ready) return;
    uint8_t tec, rec, eflg;
    mcp_get_errors(&tec, &rec, &eflg);
    int nsubs = 0;
    for (int i = 0; i < CAN_MAX_SUBS; i++) if (g_can_subs[i].used) nsubs++;
    out_json("{\"id\":0,\"d\":{\"can_diag\":{\"mode\":\"%s\",\"tec\":%u,\"rec\":%u,\"eflg\":\"%02X\","
             "\"req\":%lu,\"resp\":%lu,\"to\":%lu,\"txerr\":%lu,\"isotp_err\":%lu,\"other\":%lu,\"subs\":%d,\"eng\":%d}}}",
             mcp_mode_name(mcp_get_mode()), tec, rec, eflg,
             (unsigned long)g_can.requests, (unsigned long)g_can.responses, (unsigned long)g_can.timeouts,
             (unsigned long)g_can.tx_errors, (unsigned long)g_can.isotp_errors, (unsigned long)g_can.rx_other,
             nsubs, (int)s_eng.state);
    if (g_can.sniff)
        out_json("{\"id\":0,\"d\":{\"can_sniff\":{\"rx\":%lu,\"out\":%lu,\"ovr\":%lu}}}",
                 (unsigned long)g_can.sniff_rx, (unsigned long)g_can.sniff_out, (unsigned long)g_can.sniff_ovr);
}
