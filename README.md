# 绝缘子清洗机器人（三阶段协议重构版）

本项目重构了绝缘子清洗机器人的三阶段控制流程，覆盖视觉检测、中心带判定、采样后处理、Modbus 通讯状态机、PLC 模拟器与可视化等组件，便于在实验室环境快速验证端到端流程。

## 功能总览
- 视觉检测：基于 YOLOv8/ONNX，可按需切换至 Dummy 检测器。
- 中心带判定：结合滑动投票，稳定判断当前刷头区域是否可清洗。
- 上升采样：按照固定周期向 PLC 请求高度采样并记录 flag/Z/距离数据。
- 后处理：对采样序列做形态学滤波、边界缩退、刷头偏置与距离统计，生成执行段表。
- 下降执行：三阶段 Modbus 状态机逐段下发清洗指令。
- PLC 模拟器：内置最小 Modbus 服务器，便于离线联调。
- 可视化：支持实时叠加检测框与中心带、离线回放日志。

## 目录结构
```text
insulator_bot/
├─ core/               # 配置读取、日志、工具函数
├─ comms/              # Modbus 客户端、协议常量及 PLC 模拟器
├─ pipeline/           # 采样、后处理、段命令与状态机
├─ vision/             # 目标检测、中心带判定、滑动投票
├─ sensors/            # 距离传感器抽象与模拟实现
├─ viz/                # 可视化叠加与视频回放脚本
├─ runtime/            # 多线程运行模板与辅助线程
├─ build/              # 打包或部署所需的离线脚本与依赖
├─ videos/             # 示例视频（通过 Git LFS 管理）
├─ logs/               # 采样与段后处理输出
├─ main.py             # 主流程入口
├─ config.yaml         # 运行配置
├─ requirements.txt    # Python 依赖
└─ README.md
```

## 环境准备
1. **Python** ：建议 3.9 及以上版本。
2. **依赖安装** ：
   ```bash
   pip install -r requirements.txt
   ```
   - 若需直接运行 YOLOv8 推理，请确保 `torch` 与 `ultralytics` 可用。
   - 仅离线回放/后处理可使用 Dummy 模式，无需额外深度学习依赖。
3. **Git LFS** ：仓库中的 `videos/*.mp4` 通过 Git LFS 管理，克隆后请执行：
   ```bash
   git lfs install
   git lfs pull
   ```

## 快速上手
1. **模拟 PLC**（建议先在本机联调）：
   ```bash
   python -m insulator_bot.comms.plc_sim  # 默认监听 0.0.0.0:15020
   ```
2. **运行主流程**（视频源或相机）：
   ```bash
   # 使用默认配置与示例参数，运行前请修改 config.yaml 中的模型路径
   python -m insulator_bot.main --config config.yaml --video path/to/demo.mp4
   ```
3. **离线可视化回放**：
   ```bash
   python -m insulator_bot.viz.visualize --config config.yaml --video path/to/demo.mp4 --save outputs/preview.mp4
   ```
4. **仅做后处理（不走通讯）**：
   ```bash
   python - <<'PY'
   from pipeline.postprocess import postprocess_sequences_ex
   # 读取 logs/sample.csv, 自行调用后处理函数
   PY
   ```

## 三阶段流程说明
1. **Phase 1 — 上升采样**
   - `pipeline.sampler.run_sampling` 定期触发 `CMD_SAMPLE_UP`，读取 PLC 回传高度与状态。
   - 视觉检测 + 中心带判定生成可清洗 flag，配合距离数据缓冲。
   - 采样结果保存至 `logs/sample.csv`。
2. **Phase 2 — 停止协商**
   - `pipeline.state_machine.negotiate_stop` 写入 `CMD_STOP_ASC`，等待 PLC 进入停止状态。
3. **Phase 3 — 段执行**
   - 后处理生成段表后，`pipeline.state_machine.descend_execute` 依次写入 `CMD_START_SEG` 与参数（起点、步距、次数、距离、是否最后一段）。
   - 状态机等待 `ST_CLEANING` → `ST_WAIT_SEG`，最后通过 `CMD_FINISH_ALL` 收尾。

## 配置文件说明（`config.yaml`）
- `vision`：模型路径、置信度阈值、中心带宽度、投票窗口等参数。
- `sampling`：采样周期、触顶策略、Z 上限。
- `postproc`：形态学窗口、最小段长、安全缩退、刷头偏置、合并间隙等。
- `modbus`：PLC 地址、端口、站号及寄存器偏移。
- `distance`：距离数据的回填、插值与限幅策略。
- `cleaning`：刷头宽度、步距限制与重叠率。
- `logging` / `runtime`：日志路径、心跳周期、超时与重试次数等运行时参数。

## 通讯协议要点
- 浮点寄存器采用 **float32 大端**（1 float = 2 个寄存器），常用偏移：
  - `OFF_CMD`、`OFF_STATUS`、`OFF_Z`、`OFF_ZSIG`、`OFF_H0`、`OFF_DH`、`OFF_N`、`OFF_DIS`、`OFF_HEART` 等。
- 主要命令：`CMD_BOOT_OK`、`CMD_READY_REQ`、`CMD_SAMPLE_UP`、`CMD_STOP_ASC`、`CMD_START_SEG`、`CMD_FINISH_ALL`。
- 状态位：`ST_INIT`、`ST_READY`、`ST_SAMPLING`、`ST_STOPPED`、`ST_AT_TOP`、`ST_WAIT_SEG`、`ST_CLEANING`、`ST_DONE`。
- 推荐策略：
  - 采样阶段轮询 `read_status_and_z`，记录 flag/Z。
  - 等待 ACK/SEG_DONE 时设定超时与重试，掉线时支持重连。
  - 真实 PLC 联调需开放端口、防火墙并确保网络通畅。

## 产出数据
- `logs/sample.csv`：采样得到的 `flag, z, dis` 序列。
- `logs/segments.csv`：后处理生成的可清洗段（起始/终止高度 + 距离统计）。
- 控制台日志与可选的文件日志（在 `logging.file` 配置）。

## 可视化与调试
- `viz/overlay.py` 提供检测与中心带叠加函数，可在自定义界面复用。
- `viz/visualize.py` 支持实时播放与录制。
- `runtime/threading_runtime.py` 提供多线程模板，包括抓帧、检测、距离读取、心跳与 CSV 写入线程，适合扩展到真实设备。

## 常见问题
- **YOLO 模型无法加载**：检查 `ultralytics`/`torch` 是否安装，或改用 ONNX / Dummy 模式。
- **视频文件过大导致 push 失败**：仓库已启用 Git LFS，请确保本地也通过 `git lfs track "*.mp4"` 管理。
- **PLC 联调失败**：确认网络配置、端口、防火墙及寄存器字节序与本项目一致。

## License
本仓库仅供团队内部联调与演示使用，禁止未经授权的对外发布。
