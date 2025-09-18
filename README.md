# 绝缘子清洗机器人（三阶段协议重构版）

本项目根据《GPT5 Agent 重构指南》重构，包含：视觉检测、中心带判定、采样后处理、三阶段 Modbus 通讯状态机、模拟 PLC、可视化与配置。

## 一、环境
```bash
pip install -r requirements.txt
```

## 二、启动模拟 PLC（建议先在本机联调）
```bash
python -m insulator_bot.comms.plc_sim  # 监听 0.0.0.0:15020
```

## 三、运行主流程（视频源或相机）
```bash
# 使用默认配置与示例参数（请先修改 config.yaml 中模型路径）
python -m insulator_bot.main --config config.yaml --video path/to/demo.mp4
```

## 四、仅离线后处理与可视化
```bash
python -m insulator_bot.viz.visualize --csv logs/sample.csv --video path/to/demo.mp4
```

## 五、目录
```text
insulator_bot/
├─ core/                 # 配置、日志、工具
├─ vision/               # 检测、中心带判定、投票
├─ pipeline/             # 采样、后处理、段映射、状态机
├─ comms/                # Modbus 客户端与模拟 PLC
├─ viz/                  # 可视化
├─ main.py               # 程序入口
├─ config.yaml           # 配置
└─ requirements.txt
```

## 六、三阶段交互协议要点
- 浮点寄存器（float32，大端，1 float=2 regs）；固定偏移：VERSION、CMD、ARG0..ARG4、STATUS、Z、DIS、HEARTBEAT；
- CMD：0 idle，1 tick，2 stop_ascend，3 start_seg，4 abort；
- STATUS 位：1 READY，2 BUSY，4 Z_VALID，8 AT_MAX，16 ACK，32 SEG_DONE，64 ERROR；
- 上升：周期写 TICK→读 STATUS|Z 并记录 [flag,Z]；
- 终止：写 STOP_ASC（ARG0=1 顶端/2 顶部位）→等待 ACK；
- 下降：逐段写 START_SEG（ARG0=Z_start, ARG1=offset_step, ARG2=n_steps, ARG3=dis, ARG4=is_last）→等待 ACK→等待 SEG_DONE。

## 七、连接真实 PLC 的注意事项
- Windows 防火墙放行 TCP/502 或实际端口；
- 确认上位机与 PLC 在同一网段，禁用虚拟网卡对优先级的影响；
- 读写保持寄存器时注意字节序：本项目使用 float32 大端，字序高字在前；
- 超时与重试策略：ACK/SEG_DONE 等待超时自动重发，掉线可重连；
- 对端需按本文协议置位/清位 STATUS 位，保证幂等。

## 八、验证路线
1. 启动 `plc_sim`，观察控制台打印；
2. 运行 `python -m insulator_bot.main --config config.yaml --video path/to/demo.mp4`；
3. 结束后检查 `logs/sample.csv` 与日志，确认段下发；
4. 可在 `postproc` 中调整形态学窗口、最小段、边界缩退与合并参数。

## 九、License
本仓库仅用于内部联调与演示。
