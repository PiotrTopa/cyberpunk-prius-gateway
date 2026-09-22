#include "hardware/pio.h"
#include "commands.h"
#include "config.h"
#include "out.h"
#include "json_util.h"
#include "avclan.h"
#include "can_sol.h"
#include "rs485.h"
#include "usb_cdc.h"
#include "led.h"

#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "hardware/watchdog.h"
#include <string.h>
#include <stdio.h>

bool g_log_rx = false;

static uint32_t s_boot_ms;
static uint8_t  s_hb_counter;

#define MAX_TOKENS 200

/* ------------------------------------------------------------------------ */
/* helpers                                                                   */
/* ------------------------------------------------------------------------ */

static bool parse_query(const json_t *j, int d, can_query_t *q)
{
    memset(q, 0, sizeof(*q));
    int ti = json_obj_get(j, d, "i");
    if (!json_get_hexint(j, ti, &q->req_id)) { out_sys_err("BAD_CAN_ID"); return false; }

    int arr = json_obj_get(j, d, "d");
    int n = json_count(j, arr);
    if (arr < 0 || n < 0 || n > 8) { out_sys_err("BAD_CAN_DATA"); return false; }
    for (int i = 0; i < n; i++) {
        uint32_t v;
        if (!json_get_int_base(j, json_array_item(j, arr, i), 10, &v) || v > 255) { out_sys_err("BAD_CAN_DATA"); return false; }
        q->req[i] = (uint8_t)v;
    }
    q->req_len = (uint8_t)n;

    bool e = false;
    json_get_bool(j, json_obj_get(j, d, "e"), &e);
    q->ext = e;

    long t = 100;
    json_get_long(j, json_obj_get(j, d, "t"), &t);
    if (t < 10) t = 10;
    if (t > 10000) t = 10000;
    q->timeout_ms = (uint32_t)t;

    bool isotp = false;
    json_get_bool(j, json_obj_get(j, d, "isotp"), &isotp);
    if (t >= 300) isotp = true;          /* v2.x: long timeout implies multi-frame */
    q->isotp = isotp;

    int r = json_obj_get(j, d, "r");
    if (r >= 0 && json_count(j, r) > 0) {
        int nr = json_count(j, r);
        if (nr > CAN_MAX_RESP_IDS) nr = CAN_MAX_RESP_IDS;
        for (int i = 0; i < nr; i++) {
            uint32_t v;
            if (!json_get_hexint(j, json_array_item(j, r, i), &v)) { out_sys_err("BAD_RESP_ID"); return false; }
            q->resp[i] = v;
        }
        q->nresp = (uint8_t)nr;
    } else {
        for (int i = 0; i < 8; i++) q->resp[i] = 0x7E8u + (uint32_t)i;
        q->nresp = 8;
    }
    return true;
}

/* ------------------------------------------------------------------------ */
/* id 0: system                                                              */
/* ------------------------------------------------------------------------ */

static void handle_sys(const json_t *j, int d)
{
    int t;
    bool b;

    if ((t = json_obj_get(j, d, "seq")) >= 0 && json_get_bool(j, t, &b)) {
        g_out.seq_enabled = b;
        out_json("{\"id\":0,\"d\":{\"msg\":\"CFG_UPDATED\",\"seq\":%s}}", b ? "true" : "false");
    }
    if ((t = json_obj_get(j, d, "isotp_debug")) >= 0 && json_get_bool(j, t, &b)) {
        g_can.isotp_debug = b;
        out_json("{\"id\":0,\"d\":{\"msg\":\"CFG_UPDATED\",\"isotp_debug\":%s}}", b ? "true" : "false");
    }
    if ((t = json_obj_get(j, d, "test")) >= 0) {
        if (json_str_eq(j, t, "rs485")) {
            if (!g_rs485.ready) out_json("{\"id\":0,\"d\":{\"test\":\"rs485\",\"err\":\"NOT_INIT\"}}");
            else out_json("{\"id\":0,\"d\":{\"test\":\"rs485\",\"w\":%d,\"ok\":true}}", rs485_test_pattern());
        } else if (json_str_eq(j, t, "avc")) {
            bool rx_idle, rx_drive, rx_after;
            avclan_test_loopback(&rx_idle, &rx_drive, &rx_after);
            out_json("{\"id\":0,\"d\":{\"test\":\"avc\",\"rx_idle\":%d,\"rx_drive\":%d,\"rx_after\":%d}}",
                     rx_idle ? 1 : 0, rx_drive ? 1 : 0, rx_after ? 1 : 0);
        } else if (json_str_eq(j, t, "tx_pio")) {
            out_json("{\"id\":0,\"d\":{\"msg\":\"TX_PIO_PULSE\"}}");
        } else if (json_str_eq(j, t, "tx_c")) {
            pio_sm_set_enabled(pio1, 1, false);
            pio_sm_clear_fifos(pio1, 1);
            pio_sm_restart(pio1, 1);
            pio_sm_clkdiv_restart(pio1, 1);
            pio_sm_exec(pio1, 1, pio_encode_jmp(0));
            
            pio_sm_put(pio1, 1, 16);          /* nbits-1 */
            pio_sm_put(pio1, 1, 0xAAAAAAAA);  /* data */
            
            pio_sm_set_enabled(pio1, 1, true);
            out_json("{\"id\":0,\"d\":{\"test\":\"tx_c\",\"ok\":true}}");
        } else if (json_str_eq(j, t, "tx_high")) {
            avclan_test_tx(1);
            out_json("{\"id\":0,\"d\":{\"test\":\"tx_high\",\"gp1\":1,\"gp0\":%d}}", avclan_rx_level() ? 1 : 0);
        } else if (json_str_eq(j, t, "tx_low")) {
            avclan_test_tx(0);
            out_json("{\"id\":0,\"d\":{\"test\":\"tx_low\",\"gp1\":0,\"gp0\":%d}}", avclan_rx_level() ? 1 : 0);
        } else if (json_str_eq(j, t, "tx_sq")) {
            out_json("{\"id\":0,\"d\":{\"test\":\"tx_sq\",\"status\":\"running_10s\"}}");
            avclan_test_tx(2);
            out_json("{\"id\":0,\"d\":{\"test\":\"tx_sq\",\"status\":\"done\"}}");
        }
    }

    int a = json_obj_get(j, d, "a");
    if (a < 0) return;

    if (json_str_eq(j, a, "whoami") || json_str_eq(j, a, "identify") || json_str_eq(j, a, "id")) {
        sys_emit_ident();
    } else if (json_str_eq(j, a, "stats")) {
        sys_emit_stats();
    } else if (json_str_eq(j, a, "avc_raw")) {
        bool on = true;
        json_get_bool(j, json_obj_get(j, d, "on"), &on);
        avclan_set_raw(on);
        out_json("{\"id\":0,\"d\":{\"msg\":\"CFG_UPDATED\",\"avc_raw\":%s}}", on ? "true" : "false");
    } else if (json_str_eq(j, a, "avc_err")) {
        bool on = true;
        json_get_bool(j, json_obj_get(j, d, "on"), &on);
        g_avc.debug_errors = on;
        out_json("{\"id\":0,\"d\":{\"msg\":\"CFG_UPDATED\",\"avc_err\":%s}}", on ? "true" : "false");
    } else if (json_str_eq(j, a, "avc_cfg")) {
        long v;
        int pol = json_obj_get(j, d, "pol");
        if ((t = json_obj_get(j, d, "glitch")) >= 0 && json_get_long(j, t, &v) && v > 0 && v < 100) g_avc_thr.glitch_us = (uint16_t)v;
        if ((t = json_obj_get(j, d, "t1")) >= 0 && json_get_long(j, t, &v) && v > 0 && v < 200)     g_avc_thr.one_max_us = (uint16_t)v;
        if ((t = json_obj_get(j, d, "t0")) >= 0 && json_get_long(j, t, &v) && v > 0 && v < 1000)    g_avc_thr.zero_max_us = (uint16_t)v;
        if ((t = json_obj_get(j, d, "tstart")) >= 0 && json_get_long(j, t, &v) && v > 0 && v < 5000) g_avc_thr.start_max_us = (uint16_t)v;
        if (pol >= 0) {
            if (json_str_eq(j, pol, "auto"))     avclan_set_polarity(AVC_POL_AUTO);
            else if (json_str_eq(j, pol, "hi"))  avclan_set_polarity(AVC_POL_DOMINANT_HIGH);
            else if (json_str_eq(j, pol, "lo"))  avclan_set_polarity(AVC_POL_DOMINANT_LOW);
        }
        out_json("{\"id\":0,\"d\":{\"msg\":\"CFG_UPDATED\",\"avc_cfg\":{\"pol\":\"%s\",\"glitch\":%u,\"t1\":%u,\"t0\":%u,\"tstart\":%u}}}",
                 g_avc.dominant_low ? "lo" : "hi", g_avc_thr.glitch_us, g_avc_thr.one_max_us,
                 g_avc_thr.zero_max_us, g_avc_thr.start_max_us);
    } else if (json_str_eq(j, a, "can_cfg")) {
        long v;
        if ((t = json_obj_get(j, d, "stmin")) >= 0 && json_get_long(j, t, &v) && v >= 0 && v <= 127)   g_can.isotp_stmin_ms = (uint8_t)v;
        if ((t = json_obj_get(j, d, "gap")) >= 0 && json_get_long(j, t, &v) && v >= 0 && v <= 5000)    g_can.inter_request_gap_ms = (uint16_t)v;
        if ((t = json_obj_get(j, d, "retries")) >= 0 && json_get_long(j, t, &v) && v >= 0 && v <= 5)   g_can.isotp_retries = (uint8_t)v;
        out_json("{\"id\":0,\"d\":{\"msg\":\"CFG_UPDATED\",\"can_cfg\":{\"stmin\":%u,\"gap\":%u,\"retries\":%u}}}",
                 g_can.isotp_stmin_ms, g_can.inter_request_gap_ms, g_can.isotp_retries);
    } else if (json_str_eq(j, a, "log_rx")) {
        bool on = true;
        json_get_bool(j, json_obj_get(j, d, "on"), &on);
        g_log_rx = on;
        out_json("{\"id\":0,\"d\":{\"msg\":\"CFG_UPDATED\",\"log_rx\":%s}}", on ? "true" : "false");
    } else if (json_str_eq(j, a, "reset")) {
        out_json("{\"id\":0,\"d\":{\"msg\":\"RESET\"}}");
        sleep_ms(20);
        watchdog_reboot(0, 0, 10);
        for (;;) tight_loop_contents();
    } else if (json_str_eq(j, a, "bootsel")) {
        out_json("{\"id\":0,\"d\":{\"msg\":\"BOOTSEL\"}}");
        sleep_ms(50);
        reset_usb_boot(0, 0);
    }
}

/* ------------------------------------------------------------------------ */
/* id 1: CAN                                                                 */
/* ------------------------------------------------------------------------ */

static void handle_can(const json_t *j, int d)
{
    int a = json_obj_get(j, d, "a");
    can_query_t q;

    if (a < 0 || json_str_eq(j, a, "tx")) {
        if (!parse_query(j, d, &q)) return;
        can_frame_t f = { .id = q.req_id, .ext = q.ext, .dlc = q.req_len };
        memset(f.data, 0, 8);
        memcpy(f.data, q.req, q.req_len);
        can_sol_action_tx(&f);
    } else if (json_str_eq(j, a, "req")) {
        if (!parse_query(j, d, &q)) return;
        can_sol_action_req(&q);
    } else if (json_str_eq(j, a, "sub")) {
        long slot = -1, interval = 1000;
        json_get_long(j, json_obj_get(j, d, "slot"), &slot);
        json_get_long(j, json_obj_get(j, d, "int"), &interval);
        if (slot < 0 || slot >= CAN_MAX_SUBS) { out_sys_err("INVALID_SLOT"); return; }
        if (!parse_query(j, d, &q)) return;
        if (interval < 50) interval = 50;
        can_sol_action_sub((int)slot, &q, (uint32_t)interval);
    } else if (json_str_eq(j, a, "unsub")) {
        int s = json_obj_get(j, d, "slot");
        long slot;
        if (json_str_eq(j, s, "all")) can_sol_action_unsub(-1);
        else if (json_get_long(j, s, &slot)) can_sol_action_unsub((int)slot);
        else out_sys_err("SLOT_NOT_FOUND");
    } else if (json_str_eq(j, a, "subs")) {
        can_sol_action_list();
    } else if (json_str_eq(j, a, "mode")) {
        int m = json_obj_get(j, d, "m");
        if (json_str_eq(j, m, "normal") || json_str_eq(j, m, "tx")) can_sol_action_mode(true);
        else if (json_str_eq(j, m, "listen")) can_sol_action_mode(false);
        else out_sys_err("INVALID_MODE");
    } else {
        out_sys_err("UNKNOWN_ACTION");
    }
}

/* ------------------------------------------------------------------------ */
/* id 2: AVC-LAN transmit                                                    */
/* ------------------------------------------------------------------------ */

static void handle_avc(const json_t *j, int d)
{
    avc_frame_t f;
    memset(&f, 0, sizeof(f));
    uint32_t m, s, c;
    if (!json_get_hexint(j, json_obj_get(j, d, "m"), &m) || m > 0xFFF ||
        !json_get_hexint(j, json_obj_get(j, d, "s"), &s) || s > 0xFFF ||
        !json_get_int_base(j, json_obj_get(j, d, "c"), 10, &c) || c > 0xF) {
        out_sys_err("BAD_AVC_HEADER");
        return;
    }
    f.master = (uint16_t)m;
    f.slave = (uint16_t)s;
    f.control = (uint8_t)c;

    int arr = json_obj_get(j, d, "d");
    int n = json_count(j, arr);
    if (arr < 0 || n > AVC_MAX_DATA) { out_sys_err("BAD_AVC_DATA"); return; }
    for (int i = 0; i < n; i++) {
        uint32_t v;
        if (!json_get_hexint(j, json_array_item(j, arr, i), &v) || v > 255) { out_sys_err("BAD_AVC_DATA"); return; }
        f.data[i] = (uint8_t)v;
    }
    f.len = (uint8_t)n;

    bool b = (s == 0xFFF);
    json_get_bool(j, json_obj_get(j, d, "b"), &b);
    f.broadcast = b;

    if (!avclan_send(&f)) out_sys_err("AVC_TX_QUEUE_FULL");
}

/* ------------------------------------------------------------------------ */

void commands_handle_line(char *line, size_t len)
{
    long id;
    if (!json_scan_id(line, len, &id)) { out_json("{\"id\":0,\"d\":{\"err\":\"CMD_ERR\",\"msg\":\"no id\"}}"); return; }

    if (id >= DEV_SAT_MIN) {
        /* Transparent tunnel to the satellites. */
        if (!g_rs485.ready) { out_sys_err("RS485_OFFLINE"); return; }
        if (!rs485_send(line, len)) { out_sys_err("RS485_TX_FULL"); return; }
        if (g_log_rx) out_json("{\"id\":0,\"d\":{\"log\":\"RS485_TX\",\"len\":%u,\"to\":%ld}}", (unsigned)len, id);
        return;
    }

    static jsmntok_t toks[MAX_TOKENS];
    json_t j;
    int n = json_parse(&j, line, len, toks, MAX_TOKENS);
    if (n < 0) { out_json("{\"id\":0,\"d\":{\"err\":\"JSON_PARSE\",\"code\":%d}}", n); return; }
    int d = json_obj_get(&j, 0, "d");
    if (d < 0) return;

    if (g_log_rx) {
        char a[24] = "";
        json_str_copy(&j, json_obj_get(&j, d, "a"), a, sizeof(a));
        out_json("{\"id\":0,\"d\":{\"log\":\"USB_RX\",\"dev\":%ld,\"a\":\"%s\"}}", id, a);
    }

    switch (id) {
    case DEV_SYS: handle_sys(&j, d); break;
    case DEV_CAN: handle_can(&j, d); break;
    case DEV_AVC: handle_avc(&j, d); break;
    default:      out_sys_err("UNKNOWN_DEVICE"); break;
    }
}

/* ------------------------------------------------------------------------ */
/* system messages                                                           */
/* ------------------------------------------------------------------------ */

void sys_emit_ready(void)
{
    s_boot_ms = now_ms();
    out_json("{\"id\":0,\"d\":{\"msg\":\"GATEWAY_READY\",\"ver\":\"" FW_VERSION "\",\"role\":\"" FW_ROLE "\","
             "\"can\":\"%s\",\"rs485\":\"%s\",\"cores\":1,\"fw\":\"c-sdk\",\"board\":\"" PICO_BOARD "\",\"avc_pol\":\"%s\"}}",
             g_can.ready ? "CAN_READY" : "CAN_INIT_FAIL", g_rs485.ready ? "READY" : "FAIL",
             g_avc.dominant_low ? "lo" : "hi");
}

void sys_emit_ident(void)
{
    out_json("{\"id\":0,\"d\":{\"msg\":\"IDENT\",\"role\":\"" FW_ROLE "\",\"ver\":\"" FW_VERSION "\"}}");
}

void sys_emit_heartbeat(void)
{
    s_hb_counter++;
    uint32_t up = (now_ms() - s_boot_ms) / 1000;
    out_json("{\"id\":0,\"d\":{\"msg\":\"GW_HB\",\"role\":\"" FW_ROLE "\",\"ver\":\"" FW_VERSION "\",\"n\":%u,\"up\":%lu,"
             "\"can\":%d,\"rs485\":%d,\"avc\":%lu,\"avc_err\":%lu,\"avc_lvl\":%d,\"drop\":%lu}}",
             s_hb_counter, (unsigned long)up, g_can.ready ? 1 : 0, g_rs485.ready ? 1 : 0,
             (unsigned long)g_avc.frames_out,
             (unsigned long)(g_avc_rx.parity_errors + g_avc_rx.length_errors + g_avc.timeouts),
             avclan_rx_level() ? 1 : 0, (unsigned long)g_out.dropped);
}

void sys_emit_stats(void)
{
    out_json("{\"id\":0,\"d\":{\"stats\":{"
             "\"avc\":{\"frames\":%lu,\"echo\":%lu,\"parity\":%lu,\"length\":%lu,\"aborted\":%lu,\"timeouts\":%lu,"
             "\"stray\":%lu,\"glitch\":%lu,\"ring_ovf\":%lu,\"words\":%lu,\"tx\":%lu,\"tx_deferred\":%lu,\"tx_qfull\":%lu,\"pol\":\"%s\"},"
             "\"can\":{\"ready\":%d,\"tx_en\":%d,\"req\":%lu,\"resp\":%lu,\"to\":%lu,\"txerr\":%lu,\"isotp_err\":%lu,\"other\":%lu,\"raw_tx\":%lu},"
             "\"rs485\":{\"tx_lines\":%lu,\"tx_bytes\":%lu,\"tx_full\":%lu,\"rx_lines\":%lu,\"rx_bad\":%lu,\"rx_ovr\":%lu},"
             "\"usb\":{\"lines\":%lu,\"dropped\":%lu,\"rx_lines\":%lu,\"rx_overlong\":%lu,\"connected\":%d}}}}",
             (unsigned long)g_avc.frames_out, (unsigned long)g_avc.frames_echo,
             (unsigned long)g_avc_rx.parity_errors, (unsigned long)g_avc_rx.length_errors,
             (unsigned long)g_avc_rx.aborted, (unsigned long)g_avc.timeouts,
             (unsigned long)g_avc_rx.stray_bits, (unsigned long)g_avc_rx.glitches,
             (unsigned long)g_avc.ring_overflow, (unsigned long)g_avc.fifo_words,
             (unsigned long)g_avc.tx_frames, (unsigned long)g_avc.tx_deferred, (unsigned long)g_avc.tx_queue_full,
             g_avc.dominant_low ? "lo" : "hi",
             g_can.ready, g_can.tx_enabled, (unsigned long)g_can.requests, (unsigned long)g_can.responses,
             (unsigned long)g_can.timeouts, (unsigned long)g_can.tx_errors, (unsigned long)g_can.isotp_errors,
             (unsigned long)g_can.rx_other, (unsigned long)g_can.raw_tx,
             (unsigned long)g_rs485.tx_lines, (unsigned long)g_rs485.tx_bytes, (unsigned long)g_rs485.tx_ring_full,
             (unsigned long)g_rs485.rx_lines, (unsigned long)g_rs485.rx_bad, (unsigned long)g_rs485.rx_overrun,
             (unsigned long)g_out.lines, (unsigned long)g_out.dropped, (unsigned long)g_usb.rx_lines,
             (unsigned long)g_usb.rx_overlong, usb_cdc_host_connected() ? 1 : 0);
}
