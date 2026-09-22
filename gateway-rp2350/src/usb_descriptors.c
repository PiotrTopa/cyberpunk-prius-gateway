/* USB descriptors: a single CDC-ACM interface. */
#include "tusb.h"
#include "pico/unique_id.h"
#include <string.h>

#define USBD_VID 0x2E8A   /* Raspberry Pi */
#define USBD_PID 0x000A   /* "Pico SDK CDC" - same class/driver as the v2.x MicroPython gateway */

static const tusb_desc_device_t desc_device = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = TUSB_CLASS_MISC,
    .bDeviceSubClass    = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol    = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = USBD_VID,
    .idProduct          = USBD_PID,
    .bcdDevice          = 0x0300,
    .iManufacturer      = 1,
    .iProduct           = 2,
    .iSerialNumber      = 3,
    .bNumConfigurations = 1,
};

const uint8_t *tud_descriptor_device_cb(void)
{
    return (const uint8_t *)&desc_device;
}

enum { ITF_CDC = 0, ITF_CDC_DATA, ITF_COUNT };

#define EPNUM_CDC_NOTIF 0x81
#define EPNUM_CDC_OUT   0x02
#define EPNUM_CDC_IN    0x82

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN)

static const uint8_t desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_COUNT, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_CDC_DESCRIPTOR(ITF_CDC, 4, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
};

const uint8_t *tud_descriptor_configuration_cb(uint8_t index)
{
    (void)index;
    return desc_configuration;
}

static const char *const string_desc[] = {
    (const char[]){ 0x09, 0x04 },   /* 0: English (US) */
    "Cyberpunk Prius",              /* 1: manufacturer */
    "Prius Gateway",                /* 2: product */
    NULL,                           /* 3: serial (unique id) */
    "Gateway NDJSON",               /* 4: CDC interface */
};

const uint16_t *tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
    (void)langid;
    static uint16_t desc[34];
    uint8_t chr_count;

    if (index == 0) {
        memcpy(&desc[1], string_desc[0], 2);
        chr_count = 1;
    } else {
        char serial[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];
        const char *str;
        if (index == 3) {
            pico_get_unique_board_id_string(serial, sizeof(serial));
            str = serial;
        } else {
            if (index >= sizeof(string_desc) / sizeof(string_desc[0])) return NULL;
            str = string_desc[index];
        }
        chr_count = (uint8_t)strlen(str);
        if (chr_count > 32) chr_count = 32;
        for (uint8_t i = 0; i < chr_count; i++) desc[1 + i] = (uint16_t)str[i];
    }
    desc[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * chr_count + 2));
    return desc;
}
