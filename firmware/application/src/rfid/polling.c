#include "polling.h"

#include "app_timer.h"
#include "rfid_main.h"
#include "settings.h"
#include "tag_emulation.h"
#include "lf_tag_em.h"

APP_TIMER_DEF(m_polling_timer);

#define POLLING_HF_ACTIVITY_WINDOW_MS 500

static volatile bool m_polling_pending;
static bool m_polling_running;
static uint32_t m_last_reader_activity;
static bool m_polling_active;      // cycling session in progress
static uint8_t m_original_slot;    // slot to restore when the reader leaves

static void polling_timer_handler(void *p_context) {
    m_polling_pending = true;   // only set a flag: slot switch touches flash
}

void polling_init(void) {
    ret_code_t err_code = app_timer_create(&m_polling_timer, APP_TIMER_MODE_REPEATED, polling_timer_handler);
    APP_ERROR_CHECK(err_code);
}

void polling_start(void) {
    if (!settings_get_polling_enable()) return;
    m_polling_pending = false;
    ret_code_t err_code = app_timer_start(m_polling_timer,
                                          APP_TIMER_TICKS(settings_get_polling_interval_ms()), NULL);
    APP_ERROR_CHECK(err_code);
    m_polling_running = true;
}

void polling_stop(void) {
    ret_code_t err_code = app_timer_stop(m_polling_timer);
    APP_ERROR_CHECK(err_code);
    m_polling_pending = false;
    m_polling_running = false;
    m_polling_active = false;
}

bool polling_is_running(void) {
    return m_polling_running;
}

void polling_note_reader_activity(void) {
    m_last_reader_activity = app_timer_cnt_get();
}

static bool polling_reader_present(void) {
    if (is_lf_field_exists()) return true;
    uint32_t diff = app_timer_cnt_diff_compute(app_timer_cnt_get(), m_last_reader_activity);
    return diff < APP_TIMER_TICKS(POLLING_HF_ACTIVITY_WINDOW_MS);
}

void polling_process(void) {
    if (!m_polling_running) return;
    if (get_device_mode() == DEVICE_MODE_READER) return;  // emulation mode only

    if (polling_reader_present()) {
        if (!m_polling_active) {
            // Reader arrived: start a cycling session from the current slot.
            m_original_slot = tag_emulation_get_slot();
            m_polling_active = true;
        }
        if (!m_polling_pending) return;
        m_polling_pending = false;
        uint8_t slot_now = tag_emulation_get_slot();
        uint8_t slot_new = tag_emulation_slot_find_next(slot_now);
        if (slot_new == slot_now) return;   // only one enabled slot
        tag_emulation_change_slot(slot_new, true);
        // Polling switches must not run the blocking marquee animation (it
        // would eat the whole poll interval); update the slot LED instantly.
        light_up_by_slot();
    } else {
        m_polling_pending = false;
        if (m_polling_active) {
            // Reader left: stop cycling and restore the original slot.
            tag_emulation_change_slot(m_original_slot, true);
            light_up_by_slot();
            m_polling_active = false;
        }
    }
}
