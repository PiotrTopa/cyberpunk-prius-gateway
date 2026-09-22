#pragma once

#ifndef CFG_TUSB_MCU
#error "CFG_TUSB_MCU must be defined by the pico-sdk tinyusb integration"
#endif

#define CFG_TUSB_RHPORT0_MODE   OPT_MODE_DEVICE
#ifndef CFG_TUSB_OS
#define CFG_TUSB_OS             OPT_OS_PICO
#endif

#define CFG_TUD_ENDPOINT0_SIZE  64

#define CFG_TUD_CDC             1
#define CFG_TUD_MSC             0
#define CFG_TUD_HID             0
#define CFG_TUD_MIDI            0
#define CFG_TUD_VENDOR          0

/* Big TX FIFO: lines are written whole-or-nothing and flushed per line. */
#define CFG_TUD_CDC_RX_BUFSIZE  1024
#define CFG_TUD_CDC_TX_BUFSIZE  8192
#define CFG_TUD_CDC_EP_BUFSIZE  64
