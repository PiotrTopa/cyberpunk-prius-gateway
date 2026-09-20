#include "mcp2515.h"
#include "config.h"
#include "pico/stdlib.h"
#include "hardware/spi.h"
#include "hardware/gpio.h"
#include <string.h>

#define SPI_PORT spi1

/* registers */
#define R_RXF0SIDH  0x00
#define R_RXF3SIDH  0x10
#define R_RXM0SIDH  0x20
#define R_RXM1SIDH  0x24
#define R_CNF3      0x28
#define R_CNF2      0x29
#define R_CNF1      0x2A
#define R_CANINTE   0x2B
#define R_CANINTF   0x2C
#define R_EFLG      0x2D
#define R_TXB0CTRL  0x30
#define R_RXB0CTRL  0x60
#define R_RXB1CTRL  0x70
#define R_CANCTRL   0x0F
#define R_CANSTAT   0x0E
#define R_TEC       0x1C
#define R_REC       0x1D

/* instructions */
#define I_RESET      0xC0
#define I_READ       0x03
#define I_WRITE      0x02
#define I_BITMOD     0x05
#define I_READ_STAT  0xA0
#define I_RX_STAT    0xB0
#define I_READ_RXB0  0x90
#define I_READ_RXB1  0x94
#define I_LOAD_TXB0  0x40
#define I_RTS        0x80

#define TXREQ 0x08

static bool s_present;

static inline void cs_low(void)  { gpio_put(PIN_CAN_CS, 0); }
static inline void cs_high(void) { gpio_put(PIN_CAN_CS, 1); }

uint8_t mcp_read_reg(uint8_t reg)
{
    uint8_t tx[3] = { I_READ, reg, 0 }, rx[3];
    cs_low();
    spi_write_read_blocking(SPI_PORT, tx, rx, 3);
    cs_high();
    return rx[2];
}

void mcp_write_reg(uint8_t reg, uint8_t val)
{
    uint8_t tx[3] = { I_WRITE, reg, val };
    cs_low();
    spi_write_blocking(SPI_PORT, tx, 3);
    cs_high();
}

static void write_regs(uint8_t reg, const uint8_t *vals, int n)
{
    uint8_t tx[2 + 16] = { I_WRITE, reg };
    if (n > 16) n = 16;
    memcpy(tx + 2, vals, (size_t)n);
    cs_low();
    spi_write_blocking(SPI_PORT, tx, (size_t)(2 + n));
    cs_high();
}

void mcp_bit_modify(uint8_t reg, uint8_t mask, uint8_t val)
{
    uint8_t tx[4] = { I_BITMOD, reg, mask, val };
    cs_low();
    spi_write_blocking(SPI_PORT, tx, 4);
    cs_high();
}

uint8_t mcp_read_status(void)
{
    uint8_t tx[2] = { I_READ_STAT, 0 }, rx[2];
    cs_low();
    spi_write_read_blocking(SPI_PORT, tx, rx, 2);
    cs_high();
    return rx[1];
}

uint8_t mcp_rx_status(void)
{
    uint8_t tx[2] = { I_RX_STAT, 0 }, rx[2];
    cs_low();
    spi_write_read_blocking(SPI_PORT, tx, rx, 2);
    cs_high();
    return rx[1];
}

uint8_t mcp_get_mode(void)
{
    return mcp_read_reg(R_CANSTAT) & 0xE0;
}

const char *mcp_mode_name(uint8_t mode)
{
    switch (mode & 0xE0) {
    case MCP_MODE_NORMAL:   return "NORMAL";
    case MCP_MODE_SLEEP:    return "SLEEP";
    case MCP_MODE_LOOPBACK: return "LOOPBACK";
    case MCP_MODE_LISTEN:   return "LISTEN";
    case MCP_MODE_CONFIG:   return "CONFIG";
    default:                return "UNKNOWN";
    }
}

bool mcp_set_mode(uint8_t mode)
{
    mcp_bit_modify(R_CANCTRL, 0xE0, mode);
    uint32_t t0 = time_us_32();
    while ((uint32_t)(time_us_32() - t0) < 5000) {
        if (mcp_get_mode() == mode) return true;
        sleep_us(50);
    }
    return mcp_get_mode() == mode;
}

bool mcp_enable_tx(void)
{
    if (!mcp_set_mode(MCP_MODE_CONFIG)) return false;
    mcp_write_reg(R_EFLG, 0x00);
    mcp_write_reg(R_TEC, 0x00);
    mcp_write_reg(R_REC, 0x00);
    mcp_write_reg(R_CANINTF, 0x00);
    return mcp_set_mode(MCP_MODE_NORMAL);
}

static void set_bit_timing(void)
{
    /* 8 MHz crystal, 500 kbps. Confirmed on this module 2026-02-17 — DO NOT CHANGE.
     *   CNF1 0xC0: SJW=4TQ, BRP=0 -> TQ = 250 ns
     *   CNF2 0xD8: BTLMODE=1, SAM=1, PHSEG1=4TQ, PRSEG=1TQ
     *   CNF3 0x01: PHSEG2=2TQ      => 8 TQ = 2 us per bit, sample point 75 %. */
    mcp_write_reg(R_CNF1, 0xC0);
    mcp_write_reg(R_CNF2, 0xD8);
    mcp_write_reg(R_CNF3, 0x01);
}

static void id_to_regs(uint32_t id, bool ext, uint8_t r[4])
{
    if (ext) {
        r[0] = (uint8_t)(id >> 21);
        r[1] = (uint8_t)(((id >> 13) & 0xE0) | 0x08 | ((id >> 16) & 0x03));
        r[2] = (uint8_t)(id >> 8);
        r[3] = (uint8_t)id;
    } else {
        r[0] = (uint8_t)(id >> 3);
        r[1] = (uint8_t)((id & 0x07) << 5);
        r[2] = 0;
        r[3] = 0;
    }
}

void mcp_set_filters(const uint32_t *ids, int n, bool accept_all)
{
    uint8_t prev = mcp_get_mode();
    if (prev != MCP_MODE_CONFIG && !mcp_set_mode(MCP_MODE_CONFIG)) return;

    uint8_t regs[4];
    if (accept_all || n <= 0) {
        /* RXM=11: receive any message, filters off */
        mcp_write_reg(R_RXB0CTRL, 0x64);
        mcp_write_reg(R_RXB1CTRL, 0x60);
    } else {
        uint32_t mask, filt[6];
        if (n <= 6) {
            mask = 0x7FF;
            for (int i = 0; i < 6; i++) filt[i] = ids[i < n ? i : n - 1];
        } else {
            uint32_t diff = 0;
            for (int i = 1; i < n; i++) diff |= ids[0] ^ ids[i];
            mask = 0x7FF & ~diff;
            for (int i = 0; i < 6; i++) filt[i] = ids[0];
        }
        id_to_regs(mask, false, regs); write_regs(R_RXM0SIDH, regs, 4);
        id_to_regs(mask, false, regs); write_regs(R_RXM1SIDH, regs, 4);
        for (int i = 0; i < 6; i++) {
            uint8_t reg = (i < 3) ? (uint8_t)(R_RXF0SIDH + 4 * i) : (uint8_t)(R_RXF3SIDH + 4 * (i - 3));
            id_to_regs(filt[i], false, regs);
            write_regs(reg, regs, 4);
        }
        /* RXM=00 filters on; RXB0 rolls over into RXB1 when full */
        mcp_write_reg(R_RXB0CTRL, 0x04);
        mcp_write_reg(R_RXB1CTRL, 0x00);
    }
    mcp_write_reg(R_CANINTF, 0x00);
    if (prev != MCP_MODE_CONFIG) mcp_set_mode(prev);
}

bool mcp_present(void) { return s_present; }

bool mcp_init(void)
{
    spi_init(SPI_PORT, CAN_SPI_HZ);
    spi_set_format(SPI_PORT, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(PIN_CAN_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_CAN_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(PIN_CAN_MISO, GPIO_FUNC_SPI);
    gpio_init(PIN_CAN_CS);
    gpio_set_dir(PIN_CAN_CS, GPIO_OUT);
    cs_high();
    gpio_init(PIN_CAN_INT);
    gpio_set_dir(PIN_CAN_INT, GPIO_IN);
    gpio_pull_up(PIN_CAN_INT);

    s_present = false;
    for (int attempt = 0; attempt < 5 && !s_present; attempt++) {
        uint8_t rst = I_RESET;
        cs_low(); spi_write_blocking(SPI_PORT, &rst, 1); cs_high();
        sleep_ms(10);
        mcp_write_reg(R_CNF1, 0x55);
        if (mcp_read_reg(R_CNF1) == 0x55 && mcp_get_mode() == MCP_MODE_CONFIG) s_present = true;
        else sleep_ms(50);
    }
    if (!s_present) return false;

    set_bit_timing();
    mcp_write_reg(R_CANINTF, 0x00);
    mcp_write_reg(R_CANINTE, 0x03);          /* RX0IE | RX1IE drive the INT pin */

    /* Default acceptance: OBD-II ECU responses 0x7E8..0x7EF only. */
    uint32_t obd[8];
    for (int i = 0; i < 8; i++) obd[i] = 0x7E8u + (uint32_t)i;
    mcp_set_filters(obd, 8, false);

    return mcp_set_mode(MCP_MODE_LISTEN);
}

bool mcp_int_asserted(void)
{
    return !gpio_get(PIN_CAN_INT);
}

bool mcp_read_rx(int buf, can_frame_t *f)
{
    uint8_t st = mcp_rx_status();
    if (!((st >> 6) & (buf == 0 ? 1 : 2))) return false;

    uint8_t tx[14] = { buf == 0 ? I_READ_RXB0 : I_READ_RXB1 };
    uint8_t rx[14];
    cs_low();
    spi_write_read_blocking(SPI_PORT, tx, rx, 14);   /* auto-clears RXnIF */
    cs_high();

    const uint8_t *r = rx + 1;
    f->ext = (r[1] & 0x08) != 0;
    if (f->ext) {
        f->id = ((uint32_t)r[0] << 21) | (((uint32_t)r[1] & 0xE0) << 13) |
                (((uint32_t)r[1] & 0x03) << 16) | ((uint32_t)r[2] << 8) | r[3];
    } else {
        f->id = ((uint32_t)r[0] << 3) | (r[1] >> 5);
    }
    f->dlc = r[4] & 0x0F;
    if (f->dlc > 8) f->dlc = 8;
    memcpy(f->data, r + 5, 8);
    return true;
}

void mcp_flush_rx(void)
{
    can_frame_t f;
    while (mcp_read_rx(0, &f) || mcp_read_rx(1, &f)) { }
}

bool mcp_tx_busy(int txb)
{
    return (mcp_read_reg((uint8_t)(R_TXB0CTRL + 0x10 * txb)) & TXREQ) != 0;
}

void mcp_tx_abort(int txb)
{
    mcp_bit_modify((uint8_t)(R_TXB0CTRL + 0x10 * txb), TXREQ, 0);
}

bool mcp_tx(int txb, const can_frame_t *f)
{
    if (mcp_tx_busy(txb)) return false;
    uint8_t tx[1 + 5 + 8];
    tx[0] = (uint8_t)(I_LOAD_TXB0 | (txb << 1));
    id_to_regs(f->id, f->ext, tx + 1);
    tx[5] = f->dlc > 8 ? 8 : f->dlc;
    memcpy(tx + 6, f->data, 8);
    cs_low();
    spi_write_blocking(SPI_PORT, tx, 6 + tx[5]);
    cs_high();
    uint8_t rts = (uint8_t)(I_RTS | (1 << txb));
    cs_low();
    spi_write_blocking(SPI_PORT, &rts, 1);
    cs_high();
    return true;
}

void mcp_get_errors(uint8_t *tec, uint8_t *rec, uint8_t *eflg)
{
    *tec  = mcp_read_reg(R_TEC);
    *rec  = mcp_read_reg(R_REC);
    *eflg = mcp_read_reg(R_EFLG);
}
