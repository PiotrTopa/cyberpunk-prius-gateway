#include "out.h"
#include "usb_cdc.h"
#include "pico/time.h"
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

out_stats_t g_out = { .seq_enabled = true };

uint32_t now_ms(void)
{
    return to_ms_since_boot(get_absolute_time());
}

bool out_line(const char *s, size_t n)
{
    bool ok = usb_cdc_write_line(s, n);
    if (ok) g_out.lines++; else g_out.dropped++;
    return ok;
}

uint32_t out_next_seq(void)
{
    uint32_t s = g_out.seq;
    g_out.seq = (g_out.seq + 1) & 0xFFFF;
    return s;
}

bool out_json(const char *fmt, ...)
{
    static char buf[1536];   /* main-loop only */
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n < 0) return false;
    if ((size_t)n >= sizeof(buf)) { g_out.dropped++; return false; }
    return out_line(buf, (size_t)n);
}

int out_seq_field(char *dst, size_t cap)
{
    if (!g_out.seq_enabled) { if (cap) dst[0] = 0; return 0; }
    int n = snprintf(dst, cap, ",\"seq\":%lu", (unsigned long)out_next_seq());
    return n < 0 ? 0 : n;
}

void out_sys_err(const char *code)
{
    out_json("{\"id\":0,\"d\":{\"err\":\"%s\"}}", code);
}

void out_sys_log(const char *msg)
{
    out_json("{\"id\":0,\"d\":{\"log\":\"%s\"}}", msg);
}
