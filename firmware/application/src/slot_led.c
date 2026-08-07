#include "slot_led.h"

#include "app_timer.h"
#include "hw_connect.h"
#include "nrf_gpio.h"

#define SLOT_LED_BLINK_INTERVAL_MS 300

APP_TIMER_DEF(m_slot_led_blink_timer);

static bool m_blink_on;
static uint8_t m_blink_led_index;

static void slot_led_blink_timer_handler(void *p_context) {
    m_blink_on = !m_blink_on;
    uint32_t *led_pins = hw_get_led_array();
    if (m_blink_on) {
        nrf_gpio_pin_set(led_pins[m_blink_led_index]);
    } else {
        nrf_gpio_pin_clear(led_pins[m_blink_led_index]);
    }
}

void slot_led_blink_init(void) {
    ret_code_t err_code = app_timer_create(&m_slot_led_blink_timer, APP_TIMER_MODE_REPEATED, slot_led_blink_timer_handler);
    APP_ERROR_CHECK(err_code);
}

void slot_led_blink_start(uint8_t slot) {
    if (slot < 8) return;   // low half: steady LED
    m_blink_led_index = slot % 8;
    m_blink_on = true;
    uint32_t *led_pins = hw_get_led_array();
    nrf_gpio_pin_set(led_pins[m_blink_led_index]);
    ret_code_t err_code = app_timer_start(m_slot_led_blink_timer, APP_TIMER_TICKS(SLOT_LED_BLINK_INTERVAL_MS), NULL);
    APP_ERROR_CHECK(err_code);
}

void slot_led_blink_stop(void) {
    ret_code_t err_code = app_timer_stop(m_slot_led_blink_timer);
    APP_ERROR_CHECK(err_code);
    m_blink_on = false;
}
