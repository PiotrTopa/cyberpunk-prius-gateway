/* Host-side unit tests for the AVC-LAN codec and the JSON helpers.
 * Build & run:  ./test/run.sh
 */
#include "avclan_codec.h"
#include "json_util.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { printf("  FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); failures++; } } while (0)

/* Turn the encoder's packed bits into decoder symbols, optionally with
 * the ACK slots "acknowledged" by a slave (turned into ZERO). */
static int feed_bits(avc_rx_t *rx, const uint32_t *words, uint32_t nbits, bool slave_acks,
                     avc_frame_t *out)
{
    int frames = 0;
    /* ACK slot positions: after slave (1+13+13 -> index 27), control (27+1+5=33),
       length (33+1+9=43), data k: 43+1+ (k+1)*9 + k */
    for (uint32_t i = 0; i < nbits; i++) {
        uint32_t bit = (words[i >> 5] >> (31 - (i & 31))) & 1u;
        avc_symbol_t sym = bit ? AVC_SYM_ONE : AVC_SYM_ZERO;
        if (slave_acks) {
            bool is_ack = (i == 27) || (i == 33) || (i == 43);
            if (i > 43 && ((i - 43) % 10) == 0) is_ack = true;
            if (is_ack) sym = AVC_SYM_ZERO;
        }
        avc_rx_result_t r = avc_rx_feed(rx, sym);
        if (r == AVC_RX_FRAME) { frames++; if (out) *out = rx->f; }
    }
    return frames;
}

static void test_roundtrip(const avc_frame_t *f, bool acks)
{
    uint32_t words[AVC_TX_MAX_WORDS];
    uint32_t nbits = avc_encode(f, words);
    CHECK(nbits == 1u + 13u + 14u + 6u + 10u + 10u * f->len);

    avc_rx_t rx;
    avc_rx_init(&rx);
    avc_frame_t got;
    memset(&got, 0xAA, sizeof(got));
    CHECK(avc_rx_feed(&rx, AVC_SYM_START) == AVC_RX_NONE);
    int n = feed_bits(&rx, words, nbits, acks, &got);
    CHECK(n == 1);
    CHECK(avc_frame_equal(f, &got));
    CHECK(got.broadcast == f->broadcast);
    /* individual frame without slave ACK -> nak flagged; with acks -> clean */
    if (!f->broadcast) CHECK(got.nak == !acks);
    else CHECK(got.nak == false);
    CHECK(!avc_rx_busy(&rx));
    CHECK(rx.frames == 1 && rx.parity_errors == 0);
}

static void test_codec(void)
{
    printf("codec: round trips\n");
    avc_frame_t f = { .master = 0x110, .slave = 0x440, .control = 0xF, .len = 5,
                      .data = { 0x00, 0x5E, 0x29, 0x60, 0x01 }, .broadcast = false };
    test_roundtrip(&f, true);
    test_roundtrip(&f, false);

    avc_frame_t b = { .master = 0x190, .slave = 0xFFF, .control = 0xF, .len = 0, .broadcast = true };
    test_roundtrip(&b, false);

    avc_frame_t big = { .master = 0x002, .slave = 0x660, .control = 0x4, .len = 32, .broadcast = false };
    for (int i = 0; i < 32; i++) big.data[i] = (uint8_t)(i * 37 + 11);
    test_roundtrip(&big, true);

    avc_frame_t touch = { .master = 0x110, .slave = 0x178, .control = 0xF, .len = 8,
                          .data = { 0, 0x21, 0x24, 0x78, 0x80, 0x40, 0x80, 0x40 } };
    test_roundtrip(&touch, true);

    printf("codec: parity error is rejected and resync works\n");
    {
        uint32_t words[AVC_TX_MAX_WORDS];
        uint32_t nbits = avc_encode(&f, words);
        words[0] ^= 0x80000000u >> 5;   /* flip a master address bit */
        avc_rx_t rx; avc_rx_init(&rx);
        avc_rx_feed(&rx, AVC_SYM_START);
        int n = feed_bits(&rx, words, nbits, true, NULL);
        CHECK(n == 0);
        CHECK(rx.parity_errors == 1);
        CHECK(rx.err_field == AVC_F_MASTER);
        CHECK(!avc_rx_busy(&rx));
        /* next frame decodes fine */
        nbits = avc_encode(&f, words);
        avc_rx_feed(&rx, AVC_SYM_START);
        avc_frame_t got;
        n = feed_bits(&rx, words, nbits, true, &got);
        CHECK(n == 1 && avc_frame_equal(&f, &got));
    }

    printf("codec: glitches are ignored, start bit mid-frame resyncs\n");
    {
        uint32_t words[AVC_TX_MAX_WORDS];
        uint32_t nbits = avc_encode(&f, words);
        avc_rx_t rx; avc_rx_init(&rx);
        avc_rx_feed(&rx, AVC_SYM_START);
        /* feed half the frame, glitch, then a new start + full frame */
        for (uint32_t i = 0; i < nbits / 2; i++) {
            uint32_t bit = (words[i >> 5] >> (31 - (i & 31))) & 1u;
            avc_rx_feed(&rx, bit ? AVC_SYM_ONE : AVC_SYM_ZERO);
            if (i == 7) CHECK(avc_rx_feed(&rx, AVC_SYM_GLITCH) == AVC_RX_NONE);
        }
        CHECK(avc_rx_busy(&rx));
        avc_rx_feed(&rx, AVC_SYM_START);
        CHECK(rx.aborted == 1);
        avc_frame_t got;
        int n = feed_bits(&rx, words, nbits, true, &got);
        CHECK(n == 1 && avc_frame_equal(&f, &got));
        CHECK(rx.glitches == 1);
    }

    printf("codec: length > 32 rejected, len 0 completes on its ACK slot\n");
    {
        avc_rx_t rx; avc_rx_init(&rx);
        avc_frame_t z = { .master = 0x1, .slave = 0x2, .control = 0, .len = 0 };
        uint32_t words[AVC_TX_MAX_WORDS];
        uint32_t nbits = avc_encode(&z, words);
        CHECK(nbits == 44);
        avc_rx_feed(&rx, AVC_SYM_START);
        int got_at = -1;
        for (uint32_t i = 0; i < nbits; i++) {
            uint32_t bit = (words[i >> 5] >> (31 - (i & 31))) & 1u;
            if (avc_rx_feed(&rx, bit ? AVC_SYM_ONE : AVC_SYM_ZERO) == AVC_RX_FRAME) got_at = (int)i;
        }
        CHECK(got_at == (int)nbits - 1);   /* completes on the very last slot */

        /* hand-build a frame with length 33 */
        avc_frame_t bad = z; bad.len = 33;
        CHECK(avc_encode(&bad, words) == 0);
        /* encode len=32 then patch the length field bits (index 34..41) to 33 */
        bad.len = 32; nbits = avc_encode(&bad, words);
        /* length field starts at bit 1+13+14+6 = 34; 33 = 0b00100001, 32 = 0b00100000 -> set bit 41, parity flips (bit 42) */
        words[41 >> 5] ^= 0x80000000u >> (41 & 31);
        words[42 >> 5] ^= 0x80000000u >> (42 & 31);
        avc_rx_init(&rx);
        avc_rx_feed(&rx, AVC_SYM_START);
        int n = feed_bits(&rx, words, nbits, false, NULL);
        CHECK(n == 0 && rx.length_errors == 1);
    }

    printf("codec: classifier thresholds\n");
    {
        avc_thresholds_t t = AVC_THRESHOLDS_DEFAULT;
        CHECK(avc_classify(&t, 2) == AVC_SYM_GLITCH);
        CHECK(avc_classify(&t, 20) == AVC_SYM_ONE);
        CHECK(avc_classify(&t, 25) == AVC_SYM_ONE);
        CHECK(avc_classify(&t, 26) == AVC_SYM_ZERO);
        CHECK(avc_classify(&t, 32) == AVC_SYM_ZERO);
        CHECK(avc_classify(&t, 166) == AVC_SYM_START);
        CHECK(avc_classify(&t, 5000) == AVC_SYM_STUCK);
        CHECK(avc_frame_duration_us(44) == 166 + 19 + 44 * 39);
    }
}

static void test_json(void)
{
    printf("json: command parsing\n");
    const char *line = "{\"id\":1,\"d\":{\"a\":\"req\",\"i\":\"0x7E2\",\"d\":[2,33,195,0,0,0,0,0],"
                       "\"r\":[\"0x7EA\"],\"t\":500,\"isotp\":true}}";
    long id;
    CHECK(json_scan_id(line, strlen(line), &id) && id == 1);

    jsmntok_t toks[64];
    json_t j;
    int n = json_parse(&j, line, strlen(line), toks, 64);
    CHECK(n > 0);
    int d = json_obj_get(&j, 0, "d");
    CHECK(d > 0);
    int a = json_obj_get(&j, d, "a");
    CHECK(json_str_eq(&j, a, "req"));
    uint32_t v;
    CHECK(json_get_hexint(&j, json_obj_get(&j, d, "i"), &v) && v == 0x7E2);
    int arr = json_obj_get(&j, d, "d");
    CHECK(json_count(&j, arr) == 8);
    CHECK(json_get_hexint(&j, json_array_item(&j, arr, 2), &v) && v == 195);
    int r = json_obj_get(&j, d, "r");
    CHECK(json_get_hexint(&j, json_array_item(&j, r, 0), &v) && v == 0x7EA);
    long t;
    CHECK(json_get_long(&j, json_obj_get(&j, d, "t"), &t) && t == 500);
    bool b;
    CHECK(json_get_bool(&j, json_obj_get(&j, d, "isotp"), &b) && b);
    CHECK(json_obj_get(&j, d, "nope") == -1);

    const char *avc = "{\"id\": 2, \"d\": {\"m\":\"190\",\"s\":\"440\",\"c\":15,\"d\":[\"00\",\"25\",\"74\",\"9C\",\"01\"]}}";
    CHECK(json_scan_id(avc, strlen(avc), &id) && id == 2);
    n = json_parse(&j, avc, strlen(avc), toks, 64);
    CHECK(n > 0);
    d = json_obj_get(&j, 0, "d");
    CHECK(json_get_hexint(&j, json_obj_get(&j, d, "m"), &v) && v == 0x190);
    arr = json_obj_get(&j, d, "d");
    CHECK(json_get_hexint(&j, json_array_item(&j, arr, 3), &v) && v == 0x9C);
    long c;
    CHECK(json_get_long(&j, json_obj_get(&j, d, "c"), &c) && c == 15);

    /* nested object skipping: key after a nested object */
    const char *nest = "{\"id\":0,\"d\":{\"x\":{\"y\":[1,2,{\"z\":3}]},\"a\":\"whoami\"}}";
    n = json_parse(&j, nest, strlen(nest), toks, 64);
    CHECK(n > 0);
    d = json_obj_get(&j, 0, "d");
    CHECK(json_str_eq(&j, json_obj_get(&j, d, "a"), "whoami"));

    /* satellite line: id scan only */
    const char *sat = "{\"id\":110,\"d\":{\"cmd\":\"STATUS\"}}";
    CHECK(json_scan_id(sat, strlen(sat), &id) && id == 110);
    const char *noid = "{\"d\":{\"id\":5}}";   /* nested id must still be found? no: it is, and that's acceptable for routing */
    CHECK(json_scan_id(noid, strlen(noid), &id));
}

int main(void)
{
    test_codec();
    test_json();
    if (failures) { printf("%d FAILURE(S)\n", failures); return 1; }
    printf("all tests passed\n");
    return 0;
}
