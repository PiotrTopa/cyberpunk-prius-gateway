#define JSMN_PARENT_LINKS
#define JSMN_STRICT
#include "jsmn.h"
#include "json_util.h"
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

int json_parse(json_t *j, const char *s, size_t len, jsmntok_t *toks, int max)
{
    jsmn_parser p;
    jsmn_init(&p);
    int n = jsmn_parse(&p, s, len, toks, (unsigned)max);
    j->js  = s;
    j->tok = toks;
    j->n   = n > 0 ? n : 0;
    return n;
}

static int tok_len(const json_t *j, int tok)
{
    return j->tok[tok].end - j->tok[tok].start;
}

int json_skip(const json_t *j, int tok)
{
    /* Children of `tok` are exactly the tokens whose (transitive) parent is tok
     * and they are laid out contiguously after it. */
    int i = tok + 1;
    while (i < j->n) {
        int p = j->tok[i].parent;
        bool inside = false;
        while (p >= 0) {
            if (p == tok) { inside = true; break; }
            p = j->tok[p].parent;
        }
        if (!inside) break;
        i++;
    }
    return i;
}

int json_obj_get(const json_t *j, int obj, const char *key)
{
    if (obj < 0 || obj >= j->n || j->tok[obj].type != JSMN_OBJECT) return -1;
    size_t klen = strlen(key);
    int i = obj + 1;
    int end = json_skip(j, obj);
    while (i < end) {
        const jsmntok_t *k = &j->tok[i];
        if (k->parent == obj && k->type == JSMN_STRING && k->size == 1) {
            if ((size_t)(k->end - k->start) == klen &&
                memcmp(j->js + k->start, key, klen) == 0) {
                return i + 1;
            }
        }
        i++;
    }
    return -1;
}

int json_count(const json_t *j, int tok)
{
    if (tok < 0 || tok >= j->n) return 0;
    return j->tok[tok].size;
}

int json_array_item(const json_t *j, int arr, int idx)
{
    if (arr < 0 || arr >= j->n || j->tok[arr].type != JSMN_ARRAY) return -1;
    if (idx < 0 || idx >= j->tok[arr].size) return -1;
    int i = arr + 1;
    for (int k = 0; k < idx; k++) i = json_skip(j, i);
    return i < j->n ? i : -1;
}

bool json_is_string(const json_t *j, int tok)
{
    return tok >= 0 && tok < j->n && j->tok[tok].type == JSMN_STRING;
}

bool json_is_number(const json_t *j, int tok)
{
    if (tok < 0 || tok >= j->n || j->tok[tok].type != JSMN_PRIMITIVE) return false;
    char c = j->js[j->tok[tok].start];
    return c == '-' || (c >= '0' && c <= '9');
}

bool json_str_eq(const json_t *j, int tok, const char *s)
{
    if (!json_is_string(j, tok)) return false;
    size_t l = strlen(s);
    return (size_t)tok_len(j, tok) == l && memcmp(j->js + j->tok[tok].start, s, l) == 0;
}

size_t json_str_copy(const json_t *j, int tok, char *dst, size_t cap)
{
    if (!json_is_string(j, tok) || cap == 0) { if (cap) dst[0] = 0; return 0; }
    size_t l = (size_t)tok_len(j, tok);
    if (l >= cap) l = cap - 1;
    memcpy(dst, j->js + j->tok[tok].start, l);
    dst[l] = 0;
    return l;
}

bool json_get_long(const json_t *j, int tok, long *out)
{
    if (tok < 0 || tok >= j->n || j->tok[tok].type != JSMN_PRIMITIVE) return false;
    const char *p = j->js + j->tok[tok].start;
    if (*p == 't') { *out = 1; return true; }
    if (*p == 'f') { *out = 0; return true; }
    if (*p == 'n') return false;
    char buf[24];
    int l = tok_len(j, tok);
    if (l <= 0 || l >= (int)sizeof(buf)) return false;
    memcpy(buf, p, (size_t)l);
    buf[l] = 0;
    char *endp;
    long v = strtol(buf, &endp, 10);
    if (*endp == '.') { /* tolerate 100.0 */
        double d = strtod(buf, &endp);
        v = (long)d;
    }
    if (*endp != 0) return false;
    *out = v;
    return true;
}

bool json_get_bool(const json_t *j, int tok, bool *out)
{
    long v;
    if (!json_get_long(j, tok, &v)) return false;
    *out = v != 0;
    return true;
}

bool json_get_int_base(const json_t *j, int tok, int base, uint32_t *out)
{
    if (tok < 0 || tok >= j->n) return false;
    if (j->tok[tok].type == JSMN_PRIMITIVE) {
        long v;
        if (!json_get_long(j, tok, &v) || v < 0) return false;
        *out = (uint32_t)v;
        return true;
    }
    if (j->tok[tok].type != JSMN_STRING) return false;
    char buf[24];
    if (!json_str_copy(j, tok, buf, sizeof(buf)) || buf[0] == 0) return false;
    char *endp;
    unsigned long v = strtoul(buf, &endp, base);
    if (*endp != 0) return false;
    *out = (uint32_t)v;
    return true;
}

bool json_get_hexint(const json_t *j, int tok, uint32_t *out)
{
    return json_get_int_base(j, tok, 16, out);
}

bool json_scan_id(const char *s, size_t len, long *id)
{
    /* Looks for  "id"  followed by ':' and an integer. Good enough for the
     * envelope {"id":N,...} that every command uses. */
    const char *end = s + len;
    const char *p = s;
    while (p + 4 < end) {
        p = memchr(p, '"', (size_t)(end - p));
        if (!p) return false;
        if (end - p >= 4 && p[1] == 'i' && p[2] == 'd' && p[3] == '"') {
            const char *q = p + 4;
            while (q < end && isspace((unsigned char)*q)) q++;
            if (q >= end || *q != ':') { p += 4; continue; }
            q++;
            while (q < end && isspace((unsigned char)*q)) q++;
            if (q >= end) return false;
            bool neg = false;
            if (*q == '-') { neg = true; q++; }
            if (q >= end || !isdigit((unsigned char)*q)) return false;
            long v = 0;
            while (q < end && isdigit((unsigned char)*q)) { v = v * 10 + (*q - '0'); q++; }
            *id = neg ? -v : v;
            return true;
        }
        p++;
    }
    return false;
}
