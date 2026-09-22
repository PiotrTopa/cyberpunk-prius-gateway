/* NDJSON output to the USB host. Single producer: the main loop. */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

typedef struct {
    uint32_t lines;
    uint32_t dropped;        /* host not reading / buffer full */
    uint32_t seq;            /* next sequence number */
    bool     seq_enabled;
} out_stats_t;

extern out_stats_t g_out;

uint32_t now_ms(void);

/* Write one complete line (adds '\n'). Returns false if dropped. */
bool out_line(const char *s, size_t n);

/* printf-style; a '\n' is appended. */
bool out_json(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

/* Appends ',"seq":N' when enabled; returns chars written. */
int  out_seq_field(char *dst, size_t cap);
/* Consume and return the next sequence number. */
uint32_t out_next_seq(void);

/* Common system messages. */
void out_sys_err(const char *code);
void out_sys_log(const char *msg);
