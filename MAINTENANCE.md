# 维护文档

## 项目结构

```
firmware/
├── application/       # 应用固件（本修改版所有改动所在）
│   └── src/
│       ├── rfid_main.c          # 槽位 LED 显示、混色逻辑
│       ├── app_main.c           # 按键/唤醒/睡眠、轮询反馈
│       ├── app_cmd.c            # 协议命令（1041~1048）
│       ├── settings.c/h         # 设置持久化（v8）
│       └── rfid/
│           ├── polling.c/h      # 自动轮询模块
│           └── nfctag/          # 标签模拟（槽配置、迁移 v8→v9）
├── resource/tools/              # 刷机辅助（enter_dfu.py 等）
├── tools/cu-ble-sim/            # USB 串口调试脚本
└── .github/workflows/           # CI/CD（打 tag 自动构建 + 上传 Release + 同步 jsDelivr）
```

## 构建

```bash
cd firmware
docker run --rm -v "$(pwd)/..:/workdir:rw" -e CURRENT_DEVICE_TYPE=ultra \
  ghcr.io/rfidresearchgroup/chameleonultra-fw-builder:main bash ./firmware/build.sh
# 产物：firmware/objects/ultra-dfu-app.zip
```

版本号由 git 标签生成，打新构建号：`git tag -f v2.2.0-mazha0309-XXX HEAD`

## 发布流程（CI/CD）

- 打 tag（`v*`）推送即触发构建
- 自动上传 `ultra-dfu-app.zip` 到 Release
- 自动把固件包提交到仓库 `releases/`（jsDelivr CDN 渠道）并更新 `version.txt`

## 版本号规则

`v2.2.0-mazha0309-XXX`，XXX 为构建序号（-017 等）。

## 协议命令

| ID | 命令 | 说明 |
|---|---|---|
| 1041/1042 | GET/SET_POLLING_ENABLE | 轮询开关 |
| 1043/1044 | GET/SET_POLLING_INTERVAL | 轮询间隔（100~5000ms） |
| 1045/1046 | GET/SET_AB_REBOOT_ENABLE | A+B 软重启开关 |
| 1047/1048 | GET/SET_SLOT_POLLING_SKIP | 每槽轮询参与开关（16 位掩码） |

## 常见问题

- **刷入后槽位配置**：固件升级保留设置与卡槽数据；槽配置 v8→v9 迁移自动完成。
- **轮询不生效**：确认已开轮询开关（按键有绿/红反馈）、目标槽启用且未设为"跳过轮询"、读头在场。
- **灯色异常**：高半区（9~16）为混色（黄/青/品红），刷卡过程保持显示色。
- **恢复官方**：随时可刷官方 v2.2.0 的 ultra-dfu-app.zip。

## 贡献

- Fork 本仓库，修改后提交 PR。
- 遵守 GPL-3.0：修改版需公开源代码并携带上游 License（见 DISCLAIMER.md）。
