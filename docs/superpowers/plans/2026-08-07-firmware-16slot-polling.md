# Chameleon Ultra 16 槽位 + 固定延迟轮询固件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在官方最新 main 固件（v2.2.0+，本仓库已克隆于 `~/Projects/chameleonultra-poll`）上实现：16 卡槽（8 LED 显示高低半区）+ 固定延迟轮询（可配置、持久化、协议命令控制），GPL-3.0 开源发布。

**Architecture:** 改动集中在 7 个区域：槽位扩容（tag_emulation）+ FDS 存储上限（tag_persistence）+ 槽配置迁移（v8→v9）+ LED 映射（%8 + 高半区闪烁）+ settings v7（轮询配置持久化）+ 轮询模块（app_timer 标志位 + 主循环处理，复用官方 syssleep 模式）+ 协议命令（data_cmd 1041-1044 + app_cmd 表驱动）。轮询切槽用"定时器置标志 + 主循环执行"模式（切槽含 Flash 写，不能在定时器上下文执行）。

**Tech Stack:** C（nRF52840, nRF5 SDK 17.1, -O3 -Wall -Werror）、GNU ARM 12.2.rel1 工具链（Docker 官方镜像）、nrfutil/mergehex（打包 DFU）、app_timer + FDS（Nordic 库）

**构建事实（已核实）：** 本机无 arm-none-eabi-gcc；官方 CI 用 Docker 镜像 `ghcr.io/rfidresearchgroup/chameleonultra-fw-builder`（ubuntu:22.04 + ARM 12.2.rel1 + nrfutil）；`build.sh` 产出 `objects/ultra-dfu-app.zip`（仅 application 的 DFU 包，交付物）。`APP_FW_VER` 来自 `git describe --tags --match "v*.*"`，仓库无 v 标签，需先补本地标签。

**协议/数据事实（已核实）：** FDS dump 记录 id = `0x1100+slot`，nick = `0x1200+slot`（8→16 只需扩上限）；槽配置结构 `tag_slot_config_t` 8 槽=68B，16 槽=132B；settings 结构 v6 有 `reserved0:5` 可挪用 1 位；命令分发是表驱动（`m_data_cmd_map`，app_cmd.c:3058-3227），新命令自动进 GET_DEVICE_CAPABILITIES。

---

### Task 1: 构建环境 + 官方基线验证

**Files:** 无源码改动

- [ ] **Step 1: 检查 Docker/工具链可用性**

```bash
docker --version 2>&1 | head -1
which nrfutil mergehex 2>&1
```

若 docker 可用 → 用官方镜像（推荐）；若不可用 → 手动装 ARM 12.2.rel1：
```bash
curl -sL https://armkeil.blob.core.windows.net/developer/Files/downloads/gnu/12.2.rel1/binrel/arm-gnu-toolchain-12.2.rel1-x86_64-arm-none-eabi.tar.xz | tar xJ -C ~/arm-toolchain
export GNU_INSTALL_ROOT=$HOME/arm-toolchain/arm-gnu-toolchain-12.2.rel1-x86_64-arm-none-eabi/bin/
export GNU_VERSION=12.2.rel1
# nrfutil: pip install nrfutil
# mergehex: 需要 nRF Command Line Tools .deb（Docker 路径则免）
```

- [ ] **Step 2: 补本地 git 标签**

```bash
cd ~/Projects/chameleonultra-poll
git tag v2.2.0
git describe --tags --abbrev=7
```

Expected: 输出 `v2.2.0`（或 `v2.2.0-...`）

- [ ] **Step 3: 编译官方基线**

Docker 方式：
```bash
cd ~/Projects/chameleonultra-poll/firmware
docker run --rm -v "$(pwd)/..:/workdir:rw" -e CURRENT_DEVICE_TYPE=ultra \
  ghcr.io/rfidresearchgroup/chameleonultra-fw-builder:main bash ./firmware/build.sh
```
手动方式（无 docker）：
```bash
export GNU_INSTALL_ROOT=... GNU_VERSION=...
cd ~/Projects/chameleonultra-poll/firmware && ./build.sh
```

Expected: 编译无错（-Wall -Werror），`objects/ultra-dfu-app.zip` 生成

- [ ] **Step 4: 验证产物**

```bash
ls -la ~/Projects/chameleonultra-poll/firmware/objects/ultra-dfu-app.zip
unzip -l ~/Projects/chameleonultra-poll/firmware/objects/ultra-dfu-app.zip
```

Expected: application.bin（约 253KB）+ application.dat + manifest.json

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add -A
git commit -m "chore: build baseline verified (official v2.2.0)"
```

（若 objects/ 被 gitignore 只提交必要内容；若无改动可跳过 commit 并在报告里说明）

---

### Task 2: 槽位扩容 8 → 16

**Files:**
- Modify: `firmware/application/src/rfid/nfctag/tag_emulation.h:13,48,50,75`
- Modify: `firmware/application/src/rfid/nfctag/tag_emulation.c:442-499,65-81`
- Modify: `firmware/application/src/rfid/nfctag/tag_persistence.c:12`
- Modify: `firmware/application/src/utils/fds_ids.h:23-24,30-31`（注释更新）

- [ ] **Step 1: 改 tag_emulation.h**

tag_emulation.h:13:
```c
// Up to sixteen card slots
#define TAG_MAX_SLOT_NUM 16
```

tag_emulation.h:48:
```c
#define TAG_SLOT_CONFIG_CURRENT_VERSION 9
```

tag_emulation.h:50（16 槽 = 4 + 16×8 = 132）:
```c
// Intended struct size, for static assert
#define TAG_SLOT_CONFIG_CURRENT_SIZE 132
```

STATIC_ASSERT（:75）保持原样（宏已更新，编译期自动校验 132）。

- [ ] **Step 2: 改 tag_emulation.c 的 slotConfig 默认值**

tag_emulation.c:65-81 的静态初始化数组：在 8 槽之后**不追加任何项**（C 静态初始化缺省 0 = enabled=false + UNDEFINED，9~16 槽自动为"空槽"）。在结构体后加一行注释：
```c
// Slots 9~16 default to disabled/undefined (zero-initialized).
```

- [ ] **Step 3: 改迁移代码（关键）**

tag_emulation.c:442-472 的 `tag_emulation_migrate_slot_config_v0_to_v8()`：
- 行 451 `for (uint8_t i = 0; i < ARRAYLEN(slotConfig.slots); i++)` → 改为 `for (uint8_t i = 0; i < 8; i++)`（旧数据只有 8 槽，防读 tmpbuf[68..131] 垃圾）
- 行 449 `slotConfig.version = TAG_SLOT_CONFIG_CURRENT_VERSION;` → 改为 `slotConfig.version = 8;`（先升到 v8，让后续 v8→v9 迁移接管）

tag_emulation.c:474-499 的 `tag_emulation_migrate_slot_config()` 的 switch 追加 case 8（在 `default:` 之前）：
```c
        case 8:
            // v8 -> v9: expand 8 slots to 16, clear the new slots
            memset(&slotConfig.slots[8], 0, 8 * sizeof(slotConfig.slots[0]));
            NRF_LOG_INFO("Migrating slotConfig v8 to v9...");
            slotConfig.version = 9;
            tag_emulation_save_config();
            break;
```
（`tag_emulation_save_config()` 是文件内 static 函数，tag_emulation.c:523-539，switch 里可调用；需确认其声明在迁移函数之前——若在之后则改用文件内声明前置或把保存逻辑内联：`fds_write_sync(FDS_EMULATION_CONFIG_FILE_ID, FDS_EMULATION_CONFIG_RECORD_KEY, sizeof(slotConfig), (uint8_t *)&slotConfig);`）

- [ ] **Step 4: 改 tag_persistence.c 上限**

tag_persistence.c:12：
```c
    if ((sense_type == TAG_SENSE_NO) || (slot >= TAG_MAX_SLOT_NUM)) {
```
文件头加 `#include "tag_emulation.h"`（需确认当前 include 集合，避免重复包含）。

- [ ] **Step 5: 更新 fds_ids.h 注释**

fds_ids.h:23-24 与 30-31 的注释 `"starting from 0x1100 to 0x1107"` → `"starting from 0x1100 to 0x110F"`（16 槽），`0x1200..0x120F` 同理。

- [ ] **Step 6: 编译验证**

```bash
cd ~/Projects/chameleonultra-poll/firmware
docker run --rm -v "$(pwd)/..:/workdir:rw" -e CURRENT_DEVICE_TYPE=ultra \
  ghcr.io/rfidresearchgroup/chameleonultra-fw-builder:main bash ./firmware/build.sh
```
（或手动工具链）Expected: 0 error 0 warning（-Wall -Werror）

- [ ] **Step 7: Commit**

```bash
git add firmware/ && git commit -m "feat: expand slots from 8 to 16 with v9 migration"
```

---

### Task 3: LED 槽位映射与越界保护

**Files:**
- Modify: `firmware/application/src/rfid_main.c:78-89`（light_up_by_slot）
- Modify: `firmware/application/src/rgb_marquee.c:263,275,293,306`（rgb_marquee_slot_switch 越界护栏）

- [ ] **Step 1: light_up_by_slot 槽号 → LED 位置映射**

rfid_main.c:78-89：
```c
void light_up_by_slot(void) {
    uint32_t *led_pins = hw_get_led_array();
    uint8_t slot = tag_emulation_get_slot();
    uint8_t led_index = slot % 8;   // 8 LEDs show 16 slots
    for (int i = 0; i < RGB_LIST_NUM; i++) {
        if (i == led_index) {
            nrf_gpio_pin_set(led_pins[i]);
        } else {
            nrf_gpio_pin_clear(led_pins[i]);
        }
    }
}
```

- [ ] **Step 2: rgb_marquee_slot_switch 越界保护**

rgb_marquee.c:260-321：函数入口（260 行后）加映射：
```c
void rgb_marquee_slot_switch(uint8_t led_down, uint8_t color_led_down, uint8_t led_up, uint8_t color_led_up) {
    led_down %= 8;   // 16 slots map onto 8 LEDs
    led_up %= 8;
    int16_t light_level = 99; //ledBrightnessValue
    uint32_t *led_pins = hw_get_led_array();
    if (led_down <= 7) {
        ...原有逻辑不变...
```
（行 263/293 的 `<= 7` 护栏保留即可，因为已 %8）

- [ ] **Step 3: 编译验证**

同 Task 1 Step 3 命令。Expected: 0 error 0 warning

- [ ] **Step 4: Commit**

```bash
git add firmware/ && git commit -m "fix: map 16 slots onto 8 LEDs, guard marquee bounds"
```

---

### Task 4: 高半区槽位 LED 闪烁模块（槽 9~16 区分）

**Files:**
- Create: `firmware/application/src/slot_led.h`
- Create: `firmware/application/src/slot_led.c`
- Modify: `firmware/application/src/rfid_main.c`（light_up_by_slot 挂钩）
- Modify: `firmware/application/src/app_main.c`（sleep 前停止）

设计：槽号 ≥ 8 时，`slot % 8` 位置的 LED 以 300ms 周期闪烁（GPIO 翻转，**不用 PWM**，避免与 rgb_marquee 的 PWM 动画冲突；闪烁仅翻转 GPIO 在定时器回调里安全）。槽 < 8 或进入睡眠时停止。

- [ ] **Step 1: 写头文件**

`firmware/application/src/slot_led.h`：
```c
#ifndef SLOT_LED_H
#define SLOT_LED_H

#include <stdbool.h>
#include <stdint.h>

// Start/stop the high-half-slot blink (slots 9-16 blink on LED slot % 8).
void slot_led_blink_init(void);
void slot_led_blink_start(uint8_t slot);
void slot_led_blink_stop(void);

#endif
```

- [ ] **Step 2: 写实现**

`firmware/application/src/slot_led.c`：
```c
#include "slot_led.h"

#include "app_timer.h"
#include "hw_connect.h"

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
```

- [ ] **Step 3: light_up_by_slot 挂钩**

rfid_main.c:78-89 的 light_up_by_slot 末尾加：
```c
    if (slot >= 8) {
        slot_led_blink_start(slot);
    } else {
        slot_led_blink_stop();
    }
```
rfid_main.c 文件头加 `#include "slot_led.h"`。

- [ ] **Step 4: 初始化 + 睡眠停止**

app_main.c：`tag_emulation_init()` 调用点（约 1021 行）后加 `slot_led_blink_init();`
app_main.c `system_off_enter()` 内 `tag_emulation_save()`（约 292 行）后加 `slot_led_blink_stop();`
两处均需文件头确认已含 `slot_led.h`（没有则加）。

- [ ] **Step 5: 编译验证**

同 Task 1 Step 3。Expected: 0 error 0 warning

- [ ] **Step 6: Commit**

```bash
git add firmware/ && git commit -m "feat: blink LED for high-half slots 9-16"
```

---

### Task 5: settings v7（轮询配置持久化）

**Files:**
- Modify: `firmware/application/src/settings.h:8,44`（+末尾字段）
- Modify: `firmware/application/src/settings.c:34-104`（init + migrate + accessors）

- [ ] **Step 1: 结构扩展**

settings.h:8：`#define SETTINGS_CURRENT_VERSION 6` → `7`

settings.h:44：
```c
    uint8_t animation_config : 2;
    uint8_t ble_pairing_enable : 1;
    uint8_t polling_enable : 1;   // NEW in v7: auto slot polling switch
    uint8_t reserved0 : 4;
```

settings.h 结构体末尾（sleep_timeout 后）追加：
```c
    // 2 byte (add on version7)
    uint16_t polling_interval_ms; // polling switch interval in ms
```

- [ ] **Step 2: 默认值初始化**

settings.c 增加（参照 settings_init_sleep_timeout_config，settings.c:34-59 区域）：
```c
#define POLLING_INTERVAL_DEFAULT_MS 500
#define POLLING_INTERVAL_MIN_MS 100
#define POLLING_INTERVAL_MAX_MS 5000

static void settings_init_polling_config(void) {
    config.polling_enable = false;
    config.polling_interval_ms = POLLING_INTERVAL_DEFAULT_MS;
}
```
`settings_init_config()`（settings.c:61-69）末尾追加 `settings_init_polling_config();`

- [ ] **Step 3: 迁移步骤**

settings_migrate()（settings.c:71-104）的注释上方插入：
```c
        case 6:
            settings_init_polling_config();
```
（保持落空到最后一个 case 的 `settings_update_version_for_config(); break;`）

- [ ] **Step 4: Accessors**

settings.h 追加声明：
```c
bool settings_get_polling_enable(void);
void settings_set_polling_enable(bool enable);
uint16_t settings_get_polling_interval_ms(void);
void settings_set_polling_interval_ms(uint16_t ms);
```

settings.c 追加实现（参照 settings_get_sleep_timeout，settings.c:304-310）：
```c
bool settings_get_polling_enable(void) {
    return config.polling_enable;
}

void settings_set_polling_enable(bool enable) {
    config.polling_enable = enable;
}

uint16_t settings_get_polling_interval_ms(void) {
    return config.polling_interval_ms;
}

void settings_set_polling_interval_ms(uint16_t ms) {
    config.polling_interval_ms = ms;
}
```

- [ ] **Step 5: 编译验证**

同 Task 1 Step 3。Expected: 0 error 0 warning

- [ ] **Step 6: Commit**

```bash
git add firmware/ && git commit -m "feat: settings v7 with polling enable/interval"
```

---

### Task 6: 固定延迟轮询模块

**Files:**
- Create: `firmware/application/src/rfid/polling.h`
- Create: `firmware/application/src/rfid/polling.c`
- Modify: `firmware/application/src/app_main.c`（main 初始化 + 主循环 + 唤醒/睡眠挂钩）
- Modify: `firmware/application/src/app_main.c:576-596`（cycle_slot 重启定时器）

设计（官方 syssleep 模式）：app_timer（REPEATED）回调**只置标志位**（切槽含 Flash 写，禁止在定时器上下文执行），主循环 `polling_process()` 检查标志位执行实际切槽。

- [ ] **Step 1: 写头文件**

`firmware/application/src/rfid/polling.h`：
```c
#ifndef POLLING_H
#define POLLING_H

#include <stdbool.h>
#include <stdint.h>

// Fixed-delay slot polling: periodically switch to the next enabled slot.
void polling_init(void);
void polling_start(void);   // (re)start the polling timer per settings
void polling_stop(void);
void polling_process(void); // call from main loop
bool polling_is_running(void);

#endif
```

- [ ] **Step 2: 写实现**

`firmware/application/src/rfid/polling.c`：
```c
#include "polling.h"

#include "app_timer.h"
#include "rfid_main.h"
#include "settings.h"
#include "tag_emulation.h"

APP_TIMER_DEF(m_polling_timer);

static volatile bool m_polling_pending;

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
}

void polling_stop(void) {
    ret_code_t err_code = app_timer_stop(m_polling_timer);
    APP_ERROR_CHECK(err_code);
    m_polling_pending = false;
}

bool polling_is_running(void) {
    return app_timer_is_running(m_polling_timer) && settings_get_polling_enable();
}

void polling_process(void) {
    if (!m_polling_pending) return;
    m_polling_pending = false;
    if (get_device_mode() == DEVICE_MODE_READER) return;  // emulation mode only
    uint8_t slot_now = tag_emulation_get_slot();
    uint8_t slot_new = tag_emulation_slot_find_next(slot_now);
    if (slot_new == slot_now) return;   // only one enabled slot
    tag_emulation_change_slot(slot_new, true);
    apply_slot_change(slot_now, slot_new);
}
```
（`apply_slot_change` 在 rfid_main.h:30 声明；`get_device_mode`/`apply_slot_change` 均来自 rfid_main.h。若 `app_timer_is_running` 不可用则改为自维护 bool。）

- [ ] **Step 3: 主循环与生命周期挂钩（app_main.c）**

1. main() 中 `tag_emulation_init()`（约 1021 行）后：
```c
    slot_led_blink_init();
    polling_init();
```
2. 主循环 `button_press_process();`（约 1042 行）后加：
```c
    polling_process();
```
3. `system_off_enter()`（app_main.c:288-438）内 `tag_emulation_save()`（约 292 行）后加：
```c
    polling_stop();
```
4. 唤醒路径 `check_wakeup_src()`（约 485/518 行 `light_up_by_slot()` 之后）加：
```c
    polling_start();
```
（两处唤醒分支都加，或挑公共位置；以代码实际结构为准，原则：设备清醒并处于模拟模式时轮询在跑）
5. `cycle_slot()`（app_main.c:576-596）末尾加：
```c
    polling_start();   // manual switch restarts the polling period
```

- [ ] **Step 4: 编译验证**

同 Task 1 Step 3。Expected: 0 error 0 warning

- [ ] **Step 5: Commit**

```bash
git add firmware/ && git commit -m "feat: fixed-delay slot polling module"
```

---

### Task 7: 协议命令（1041-1044）

**Files:**
- Modify: `firmware/application/src/data_cmd.h`（:50 后追加 4 个 define）
- Modify: `firmware/application/src/app_cmd.c`（4 个 handler + 4 行表项）

- [ ] **Step 1: data_cmd.h 追加命令 ID**

data_cmd.h 中 `DATA_CMD_SET_SLEEP_TIMEOUT (1040)` 定义后追加：
```c
#define DATA_CMD_GET_POLLING_ENABLE              (1041)
#define DATA_CMD_SET_POLLING_ENABLE              (1042)
#define DATA_CMD_GET_POLLING_INTERVAL            (1043)
#define DATA_CMD_SET_POLLING_INTERVAL            (1044)
```

- [ ] **Step 2: app_cmd.c 写 4 个 handler**

参照 `cmd_processor_get_sleep_timeout`（app_cmd.c:213-224）风格，追加（放在 sleep timeout handlers 之后）：
```c
static data_frame_tx_t *cmd_processor_get_polling_enable(uint16_t cmd, uint16_t status, uint16_t length, uint8_t *data) {
    uint8_t payload = settings_get_polling_enable() ? 1 : 0;
    return data_frame_make(cmd, STATUS_SUCCESS, sizeof(payload), &payload);
}

static data_frame_tx_t *cmd_processor_set_polling_enable(uint16_t cmd, uint16_t status, uint16_t length, uint8_t *data) {
    if (length != 1 || data[0] > 1) {
        return data_frame_make(cmd, STATUS_PAR_ERR, 0, NULL);
    }
    settings_set_polling_enable(data[0] == 1);
    settings_save_config();
    if (data[0] == 1) {
        polling_start();
    } else {
        polling_stop();
    }
    return data_frame_make(cmd, STATUS_SUCCESS, 0, NULL);
}

static data_frame_tx_t *cmd_processor_get_polling_interval(uint16_t cmd, uint16_t status, uint16_t length, uint8_t *data) {
    uint8_t payload[2];
    uint16_t interval = settings_get_polling_interval_ms();
    payload[0] = (uint8_t)(interval >> 8);
    payload[1] = (uint8_t)(interval & 0xFF);
    return data_frame_make(cmd, STATUS_SUCCESS, sizeof(payload), payload);
}

static data_frame_tx_t *cmd_processor_set_polling_interval(uint16_t cmd, uint16_t status, uint16_t length, uint8_t *data) {
    if (length != 2) {
        return data_frame_make(cmd, STATUS_PAR_ERR, 0, NULL);
    }
    uint16_t interval = ((uint16_t)data[0] << 8) | data[1];
    if (interval < 100 || interval > 5000) {
        return data_frame_make(cmd, STATUS_PAR_ERR, 0, NULL);
    }
    settings_set_polling_interval_ms(interval);
    settings_save_config();
    polling_start();   // restart with new interval
    return data_frame_make(cmd, STATUS_SUCCESS, 0, NULL);
}
```
文件头需 `#include "polling.h"`（确认已有或添加）。

- [ ] **Step 3: 注册表项**

`m_data_cmd_map[]`（app_cmd.c:3058-3227）中 `DATA_CMD_SET_SLEEP_TIMEOUT` 表项后追加：
```c
    {DATA_CMD_GET_POLLING_ENABLE, NULL, cmd_processor_get_polling_enable, NULL},
    {DATA_CMD_SET_POLLING_ENABLE, NULL, cmd_processor_set_polling_enable, NULL},
    {DATA_CMD_GET_POLLING_INTERVAL, NULL, cmd_processor_get_polling_interval, NULL},
    {DATA_CMD_SET_POLLING_INTERVAL, NULL, cmd_processor_set_polling_interval, NULL},
```

- [ ] **Step 4: 编译验证**

同 Task 1 Step 3。Expected: 0 error 0 warning

- [ ] **Step 5: Commit**

```bash
git add firmware/ && git commit -m "feat: add polling protocol commands 1041-1044"
```

---

### Task 8: 集成构建 + 产物验证 + 收尾

**Files:** 无源码改动（验证 + 文档）

- [ ] **Step 1: 全量重建**

同 Task 1 Step 3 命令，确认 0 error 0 warning。

- [ ] **Step 2: 产物检查**

```bash
ls -la ~/Projects/chameleonultra-poll/firmware/objects/ultra-dfu-app.zip
unzip -l ~/Projects/chameleonultra-poll/firmware/objects/ultra-dfu-app.zip
strings ~/Projects/chameleonultra-poll/firmware/objects/application.bin | grep -c "Migrating slotConfig v8"
```

Expected: zip 存在；`application.bin` 内含 `Migrating slotConfig v8 to v9` 字符串

- [ ] **Step 3: 代码审查**

审查重点：
1. 迁移路径：v0_to_v8 上限锁 8、v8→v9 清零 9~16 槽、旧 1~8 槽数据保留（FDS 记录 id 不变）
2. 轮询安全：切槽只在主循环执行、睡眠前 stop、唤醒后 start、reader 模式跳过
3. LED：%8 映射无越界、闪烁定时器在睡眠前停止
4. settings：v7 迁移落空正确、interval 范围校验
5. -Wall -Werror 通过

- [ ] **Step 4: 提交收尾**

```bash
git add -A && git commit -m "docs: firmware build verified with 16-slot polling" 2>/dev/null || true
git log --oneline -10
```

---

## 验收清单（对照设计文档 docs/superpowers/specs/2026-08-07-chameleonultra-polling-16slot-design.md）

- [ ] 槽位 8→16，9~16 默认禁用，老数据保留（Task 2）
- [ ] 槽配置迁移 v8→v9（Task 2）
- [ ] 8 LED 显示 16 槽：位置 %8，9~16 闪烁区分（Task 3、4）
- [ ] 轮询配置持久化 settings v7（Task 5）
- [ ] 固定延迟轮询：app_timer + 主循环切槽、跳过空槽、手动切槽重置、睡眠/唤醒挂钩（Task 6）
- [ ] 协议 4 命令 + 表驱动注册（Task 7）
- [ ] 构建通过 -Wall -Werror，产出 ultra-dfu-app.zip（Task 8）
- [ ] GPL-3.0 合规：不改 LICENSE、不引入闭源代码

## 后续（不在本次范围）

- ChameleonUltraGUI 魔改（轮询面板 + 16 槽管理页）——另立计划
- 自适应轮询（M1 扇区认证指纹匹配）——本轮只做固定延迟
- 真机测试清单（用户执行）：刷机、按键 16 槽循环、LED 高低半区、GUI 轮询开关、实测门禁
