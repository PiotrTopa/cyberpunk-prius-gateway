/* Host command dispatch (NDJSON lines from USB) and system messages. */
#pragma once
#include <stddef.h>
#include <stdbool.h>

void commands_handle_line(char *line, size_t len);

void sys_emit_ready(void);
void sys_emit_heartbeat(void);
void sys_emit_ident(void);
void sys_emit_stats(void);

extern bool g_log_rx;   /* echo every received command as {"log":"USB_RX",...} (v2.x behaviour) */
