#ifndef SLOT_LED_H
#define SLOT_LED_H

#include <stdbool.h>
#include <stdint.h>

// Start/stop the high-half-slot blink (slots 9-16 blink on LED slot % 8).
void slot_led_blink_init(void);
void slot_led_blink_start(uint8_t slot);
void slot_led_blink_stop(void);

#endif
