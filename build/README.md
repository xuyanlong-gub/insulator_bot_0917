# 任务
请在不改变我方电气团队既定“编号与表结构”的前提下，将当前项目代码改为如下通讯协议与流程。目标：最小改动跑通 demo，后续再优化鲁棒性。

## 仓库结构与入口
- 仓库：`insulator_bot/`（已上传）
- 入口：`python -m insulator_bot.main --config insulator_bot/config.yaml --video path/to/demo.mp4`
- 主要模块：
  - 通讯：`insulator_bot/comms/modbus.py`（FC03/FC16 封装）
  - 采样：`insulator_bot/pipeline/sampler.py`
  - 后处理：`insulator_bot/pipeline/postprocess.py`
  - 段映射与执行：`insulator_bot/pipeline/segments.py`, `insulator_bot/pipeline/state_machine.py`
  - 检测：`insulator_bot/vision/detector.py`
  - 公共：`insulator_bot/core/*.py`

## 必须遵守的协议约束（按双方沟通一致）
1. **职责边界**：CMD 仅由 HOST 写；STATUS 仅由 PLC 写。
2. **Z_SIGNAL 语义**：HOST 每次采样将 `Z_SIGNAL` 递增 1。PLC 在 50–100ms 内更新 `Z` 并设置 `STATUS=2`（采样进行中）。HOST 读取到 `STATUS`∈{2,4} 且 `Z` 变化后记一条采样。
3. **类型与字节序**：float32（2 regs，大端，word-order 高字在前）；INT/DINT 也按大端处理。

## CMD 表（仅 HOST 写）
| CMD | 含义 |
|---|---|
| 0 | 开机/自检完成 |
| 1 | 准备就绪请求 |
| 2 | 上行采样请求（同时递增 Z_SIGNAL） |
| 3 | 停止上升请求 |
| 5 | 开始分段清洗（一次一段，参数见寄存器） |
| 6 | 等待当前段结束（轮询 STATUS） |
| 7 | 结束流程 |

> 删除“CMD=4 由 PLC 设置”的语义；TOP 由 STATUS=4 表示。

## STATUS 表（仅 PLC 写）
| STATUS | 含义 |
|---|---|
| 0 | 初始化/自检 |
| 1 | 准备就绪 |
| 2 | 采样进行中（Z 有效） |
| 3 | 已停止上升 |
| 4 | 到达最大伸长高度 |
| 5 | 等待分段数据 |
| 6 | 清洗中 |
| 7 | 结束清洗 |

> 状态迁移视为隐式 ACK。

## 寄存器表
| 名称 | 类型 | 占 regs | 责任方 | 说明 |
|---|---|---|---|---|
| VERSION | INT | 1 | PLC | 固件版本 |
| CMD | INT | 1 | HOST | 命令 |
| STATUS | INT | 1 | PLC | 状态码 |
| Z | float | 2 | PLC | 高度 mm |
| Z_SIGNAL | DINT | 2 | HOST | **递增计数** |
| H0 | float | 2 | HOST | 段起始高度 mm |
| Delta_H | float | 2 | HOST | 步进偏移 mm |
| N | DINT | 2 | HOST | 步数；若无法增加字段，用 N=0 表示“无后续段/收尾” |
| DIS | float | 2 | HOST | 测距 mm |
| HEART | INT | 1 | HOST | 心跳（500–1000ms） |

## 需要你改动的代码点
1. **编码层**（`modbus.py`）  
   - 增加 INT/DINT 与 regs 的互转工具（保持 float 转换不变）。  
   - 新增 `write_int`, `write_dint`, `read_int`, `read_dint` 的辅助函数。  
   - 保障大端与 word-order 一致。

2. **采样流程**（`sampler.py`）  
   - 每个采样周期：先 `Z_SIGNAL += 1`（写 DINT），再写 `CMD=2`。  
   - 轮询读取：`STATUS` 与 `Z`，当 `STATUS in {2,4}` 且 `Z` 变化时记录 `[flag,z]`。  
   - `STATUS=4`（TOP）后停止采样并转 Phase-2。

3. **终止上升**（`state_machine.py`）  
   - 停止上升：写 `CMD=3`，等待 `STATUS=3`。超时重试一次后告警。

4. **分段执行**（`state_machine.py`）  
   - 对每段：写 `H0, Delta_H, N, DIS`，随后写 `CMD=5`，等待 `STATUS=6` → 等待 `STATUS=5`（段完成回到等待数据）。  
   - 最后一段后写 `CMD=7`，等待 `STATUS=7`。

5. **心跳**（`main.py` 或独立协程）  
   - 每 0.5–1s 写 `HEART` 递增。

6. **配置项**（`config.yaml`）  
   - 加入寄存器基址、轮询周期、各阶段超时（采样、停止上升、段执行）、最大重试次数。

7. **日志与 CSV**  
   - 追加字段：`cmd,status,z,z_signal,heart`，以及每段参数 `h0,delta_h,n,dis`。

## 验收
- 使用 `plc_sim.py` 模拟端验证全流程：采样→停止上升→多段执行→结束。  
- 在 README 中添加“与现协议对齐的调用示例”和常见故障定位指引（超时、字节序、掉包）。

请基于以上要求直接修改代码
