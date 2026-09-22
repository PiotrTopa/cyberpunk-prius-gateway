/* Thin helpers over jsmn for the gateway's tiny command grammar. */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define JSMN_HEADER
#define JSMN_PARENT_LINKS
#define JSMN_STRICT
#include "jsmn.h"

typedef struct {
    const char *js;
    jsmntok_t  *tok;
    int         n;
} json_t;

/* Parse; returns token count (>0) or a negative jsmn error. */
int  json_parse(json_t *j, const char *s, size_t len, jsmntok_t *toks, int max);

/* Index of the value token for `key` inside object token `obj`, or -1. */
int  json_obj_get(const json_t *j, int obj, const char *key);

/* Number of elements in an array/object token. */
int  json_count(const json_t *j, int tok);

/* Token index of element `idx` of array `arr`, or -1. */
int  json_array_item(const json_t *j, int arr, int idx);

/* Index of the first token after `tok`'s whole subtree. */
int  json_skip(const json_t *j, int tok);

bool json_is_string(const json_t *j, int tok);
bool json_is_number(const json_t *j, int tok);
bool json_str_eq(const json_t *j, int tok, const char *s);
size_t json_str_copy(const json_t *j, int tok, char *dst, size_t cap);

/* Decimal number, or true/false (1/0). */
bool json_get_long(const json_t *j, int tok, long *out);
bool json_get_bool(const json_t *j, int tok, bool *out);

/* Integer given as number, or as a hex string ("0x7DF" / "7DF"). */
bool json_get_hexint(const json_t *j, int tok, uint32_t *out);

/* Integer given as number, or as a string parsed with `base`. */
bool json_get_int_base(const json_t *j, int tok, int base, uint32_t *out);

/*
 * Cheap scan for the top-level "id" of an NDJSON line without tokenizing.
 * Returns true and sets *id when found.
 */
bool json_scan_id(const char *s, size_t len, long *id);
