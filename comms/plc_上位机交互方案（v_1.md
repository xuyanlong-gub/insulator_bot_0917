# PLC–上位机交互方案（V1.0）

> 适用范围：绝缘子清洗机器人“上升采样—终止协商—下降执行”三阶段流程。上位机为视觉主控程序（Python），下位机为 PLC。本文为双方联调与固化协议的依据。

---

## 1. 通讯与编码约定
- 物理/传输：Modbus TCP。默认 `UnitID=1`，端口建议 `15020`（可改 502）。
- 地址空间：保持寄存器（Holding Registers）。
- 数据类型：**float32**（IEEE754，**大端**，word-order **高字在前**）。
  - 1 个 `float` 占 2 个 16 位寄存器。
  - 实际地址 = `REG_BASE + (FLOAT_OFFSET * 2)`。
- 连接与超时：TCP 超时 2 s；应用层轮询间隔 50 ms（可调）。

---

## 2. 寄存器布局（以 float 偏移计）
| 偏移(浮点) | 名称        | 方向 | 说明                                                     |
|---:|---|:--:|--------------------------------------------------------|
| 0 | VERSION   | PLC→Host | 固件/协议版本，示例 100.2                                       |
| 1 | CMD       | Host→PLC | 命令码：`0 IDLE, 1 TICK, 2 STOP_ASC, 3 START_SEG, 4 ABORT` |
| 2 | ARG0      | Host→PLC | 命令参数 0；语义随命令而定                                         |
| 3 | ARG1      | Host→PLC | 命令参数 1                                                 |
| 4 | ARG2      | Host→PLC | 命令参数 2                                                 |
| 5 | ARG3      | Host→PLC | 命令参数 3                                                 |
| 6 | ARG4      | Host→PLC | 命令参数 4                                                 |
| 7 | STATUS    | PLC→Host | **整数位图**载于 float：见下表                                   |
| 8 | Z         | PLC→Host | 升降高度（mm）                                               |
| 9 | DIS       | Host→PLC | 距离（mm）                                                 |
| 10| HEARTBEAT | Host→PLC | 心跳；Host 定期写入递增值或0/1                                    |

> 注：若 PLC 端不便处理 float，可在 PLC 内部以 2 寄存器合并/拆分为 float 计算。

### 2.1 STATUS 位定义（以 int 解释）
| 位值 | 名称       | 责任方 | 说明 |
|---:|---|:--:|---|
| 1   | ST_READY   | PLC | 可接收命令（初始化完成）|
| 2   | ST_BUSY    | PLC | 正在执行段动作 |
| 4   | ST_Z_VALID | PLC | Z 有效（最近一次 TICK 已更新）|
| 8   | ST_AT_MAX  | PLC | 升降达到顶端位（限位/到顶）|
| 16  | ST_ACK     | PLC | 已接收并处理当前命令（握手应答）|
| 32  | ST_SEG_DONE| PLC | 单段执行完成 |
| 64  | ST_ERROR   | PLC | 异常/急停 |

---

## 3. 命令语义
- `CMD=0 IDLE`：空闲，无动作。
- `CMD=1 TICK`：上位机采样心跳。PLC 应：
  - 刷新 `Z`（或保留最新值），置位 `ST_Z_VALID=1`；
  - 根据上位机是否需要 ACK，**可不置 ACK**。
- `CMD=2 STOP_ASC`：请求停止上升。`ARG0=reason`，**停止原因码**见 §4。
  - PLC：置位 `ST_ACK=1`，并进入安全态/停止上升；可清 `ST_Z_VALID`。
- `CMD=3 START_SEG`：执行下降清洁一个“段”。参数：
  - `ARG0=z_start` 起始高度 mm
  - `ARG1=step` 每步高度增量 mm
  - `ARG2=n_steps` 步数（int）
  - `ARG3=dis` 到绝缘子距离/mm
  - `ARG4=is_last` 是否最后一段（1/0）
  - PLC：收到后**立即**置 `ST_ACK=1` 与 `ST_BUSY=1`，执行完成后置 `ST_SEG_DONE=1`，清 `ST_BUSY` 与 `ST_ACK`。
- `CMD=4 ABORT`：紧急中止；PLC 可置 `ST_ERROR=1` 并转安全状态。

---

## 4. 停止条件与原因码
**停止触发为“或”逻辑，任一条件满足即停：**
1) `ST_AT_MAX==1`（升降机构到顶端位）；
2) 视觉中心带识别为 `top`。

原因码建议（写入 `ARG0`）：
- `0`: 未定义/其它
- `1`: AT_MAX 触发停止
- `2`: 中心带识别 top 触发停止
- `3`: 人工/上位机手动停止
- `4`: 异常/急停

上位机在 Phase-1 结束时调用 `STOP_ASC(ARG0=reason)`。

---

## 5. 三阶段时序

### 5.1 Phase-0 上电与握手
1. Host 连接 TCP，读 `VERSION`、`STATUS`。
2. 要求：`ST_READY=1` 且 `ST_BUSY=0`。
3. Host 开始周期写 `HEARTBEAT`（建议 1 s）。

### 5.2 Phase-1 上升采样循环
- 周期（默认 1.0 s，可 0.5–2.0 s）：
  1) Host 写 `CMD=TICK`，`ARG0=0/1`；`ARG0` 为一个递增的数字。
  2) PLC 刷新 `Z`，置 `ST_Z_VALID=1`；
  3) Host 读 `STATUS,Z`，同时完成图像帧判定（中心带 `flag` 与 `part`）。
- 退出条件：
  - 若 `STATUS&ST_AT_MAX==1` → 记录 `reason=1`；
  - 否则若 `part=='top'` → 记录 `reason=2`；
  - 满足任一条件立刻进入 Phase-2。

### 5.3 Phase-2 终止协商
1. Host 写 `CMD=STOP_ASC`，`ARG0=reason`。
2. PLC 置 `ST_ACK=1`，停止上升，进入可下发段状态。
3. Host 等 `ACK`，超时（默认 3 s）则重试 1 次，仍失败进入异常处理。

### 5.4 Phase-1.5 采样后处理（仅主机侧）
- 将 `[flag,z,dis]` 序列经开闭运算、最小段过滤、边界缩退、偏置与段合并，生成清洁段列表 `[(flag,s,dis), ...]`，并转换成段参数 `(z_start, step, n_steps, dis, is_last)`。

### 5.5 Phase-3 下降执行（逐段）
对每一段：
1) Host 写 `CMD=START_SEG` 及 5 个参数；
2) PLC 置 `ST_ACK=1`、`ST_BUSY=1`；
3) Host 等 `ACK`（≤3 s），再等 `SEG_DONE`（建议超时 `max(3 s, 0.1×n_steps)`）；
4) 完成后进入下一段。`is_last=1` 的段完成时，PLC 可将 `CMD` 归零为 `IDLE`（可选）。

> 建议：`SEG_DONE` 置位后由 PLC 在下一次 `START_SEG` 前自动清零；`ACK` 在段执行开始后清零，避免陈旧 ACK 干扰。

---

## 6. 超时、重试与幂等
- `ACK` 等待：3 s；超时**重发同一命令一次**。仍失败 → 触发 `ABORT` 或人工介入。
- `SEG_DONE` 等待：`max(3 s, 0.1×n_steps)`；可按工艺调整。
- 幂等与去重：
  - PLC 端对重复的 `START_SEG` 应安全处理（若参数一致且当前空闲，可重入；若忙则忽略或返回错误位）。
  - Host 在进入下一段前必须已观察到上段 `SEG_DONE`。

---

## 7. 心跳与失联检测
- Host 每 1 s 写 `HEARTBEAT`（自增计数或0/1）。
- PLC 可监视心跳跳变，若 `> 3 s` 未跳变判定上位机失联并转安全态。

---

## 8. 字节序与数据校验
- 字节序固定：float32 大端，word 高字在前。
- 建议在每次联调前进行：
  1) Host 写入 `DIS=123.456`；PLC 读回验证；
  2) PLC 写 `Z=789.0`；Host 读回验证。

---

## 9. 错误与异常约定
| 场景 | PLC行为 | Host行为 |
|---|---|---|
| 参数非法（步数≤0 等） | 置 `ST_ERROR`，保持安全 | 读到 `ST_ERROR` 立即 `ABORT`，弹窗/日志 |
| 忙时收到新命令 | 忽略或置 `ST_ERROR` | 观察不到 `ACK`，按超时重试或终止 |
| 机械急停 | 置 `ST_ERROR` | 立即 `ABORT` 并提示人工处理 |
| 网络断开 | — | 捕获异常→重连→恢复到 Phase-0 |

---

## 10. 联调检查清单
- [ ] TCP 互通：`ping` 与端口放行（Windows 防火墙入站 15020）。
- [ ] 字节序回环测试：`DIS`/`Z` 互写互读正确。
- [ ] 状态位时序：`TICK` 后 `ST_Z_VALID=1`；`START_SEG` → 先 `ACK=1` 再 `BUSY=1`，结束 `SEG_DONE=1`。
- [ ] 停止条件：`ST_AT_MAX=1` 或 `part=top` 任一触发即可，`STOP_ASC(ARG0=1/2)`。
- [ ] 超时策略：`ACK` 与 `SEG_DONE` 超时路径可重现并受控。

---

## 11. 变更提案接口（如 PLC 需调整）
请按如下格式提出：
- 变更项：如“STATUS 按位定义/新增位/清零时机/ACK 语义”等。
- 变更原因：安全/可实现性/PLC 资源限制等。
- 影响评估：对现有三阶段流程与 Host 代码的影响点。
- 迁移计划：灰度方案与回滚策略。

---

## 12. 附：典型时序（文本示意）
```
Phase-1 (采样循环，每 1.0 s)
Host:  CMD=TICK, ARG0=1/0 →
PLC :  Z 刷新, ST_Z_VALID=1
Host:  读 STATUS,Z, 视觉判定 part
条件1: STATUS&AT_MAX==1  → reason=1 → Phase-2
条件2: part=='top'        → reason=2 → Phase-2

Phase-2 (终止协商)
Host:  CMD=STOP_ASC, ARG0=reason →
PLC :  ST_ACK=1, 停止上升
Host:  等 ACK

Phase-3 (逐段执行)
循环各段：
Host:  CMD=START_SEG, (z_start, step, n_steps, dis, is_last) →
PLC :  ST_ACK=1, ST_BUSY=1
Host:  等 ACK → 等 SEG_DONE
PLC :  段完成 ST_SEG_DONE=1, 清 ST_BUSY, 清 ST_ACK
Host:  下一段或结束
```