# 专业模拟版图：模板语法 + 知识卡 + Laya 在环优化

日期：2026-09-26。分支 `claude/pro-analog-layout`（基于 `codex/analog-layout-loop` @ 5bc8109）。
本文所有数字均为本分支实测；复现命令见文末。

## 1. 结论先行

- **版图差的根因不在 Laya，而在生成器的"词汇"。** 旧生成器（`layout/compiler.py`，analog-groups-v1）把每个
  finger 画成独立的 nf=1 PCell、间隔 2 µm，所有网络都走"行上方 M3 总线 + 右侧 M4 脊 + M5 跨列"的通道布线。
  Laya 只能在 9 个全局旋钮（pattern、fingers_per_row、columns、split、rail、dummies、shield、decap、location）
  之间排序，任何组合都画不出共享扩散、行结构、对称走线、紧凑电容阵列。**搜索无法越过生成器的表达能力。**
- **新生成器把专业规则编译进模板（"layout grammar"）：** 与 ChipJev 的拓扑语法"每个答案都是合法电路"同构，
  版图语法保证"每个动作都产生一个结构专业的版图"。Laya 与搜索只在专业版图之间做目标驱动的取舍。
- **旧流程在 3 个新 prompt 上全部失败**（8/8 候选后仿不合格），原因是原理图零裕量（PM 60.10° vs 60°、
  电流恰在 10 µA 门限），不是几何问题；固定尺寸的版图搜索无法制造裕量。新流程把"版图可实现性"放回电路搜索
  （layout-aware sizing，`--finger-max`），并用"物理原理图"三段归因区分器件变化与寄生。
- **关于知识注入 vs 预训练/微调：两者结合，但分工明确，且都不是主杠杆**（详见 §6）：
  约 90% 的专业规则应编译成模板和可执行检查；只有条件性的取舍才按"动作 + 实测症状"检索注入给 Laya；
  Laya 要真正有用，必须用 EDA 实测结果做微调。实测：仅注入指南文本的 Laya 在未见拓扑族上与随机相当甚至更差；
  用 18 条自博弈数据微调 2.5 秒后，遗憾值降低 2–4 倍。**不建议用讲义文本预训练 Laya。**

## 2. 诊断：跑电路、看版图、找原因

在 `codex/analog-layout-loop` 上运行了 3 个新 prompt（telescopic、5T OTA、两级 Miller）以及 3 个 demo 电路，
用 KLayout/自绘渲染逐一检查（图见 `docs/figures/`）。观察到的问题与根因：

| 现象 | 根因（代码） | 后果 |
| --- | --- | --- |
| 每个 finger 独立一块扩散，间隔 2 µm | `primitive_specs` 固定 `nf=1`，`guard=0` 后逐个摆放 | 面积 2–6 倍；结电容大；"dummy" 是孤立晶体管，不起边缘环境作用 |
| 细长竖线布满版图 | 每个端子用 M2 直通到行上方 M3 总线，每网一条总线 | 平行长线耦合、敏感节点电容大、差分走线不对称 |
| 右侧大片空白、长 M5 环路 | 所有网络汇到右侧 M4 脊，跨列走 M5 | 线长与面积浪费；看起来"不专业" |
| 20 pF 电容排成 440 µm 一长排 | MIM tile 顺序单行放置 | 纵横比 5:1 以上 |
| 50 µm 高的 finger | 电路搜索的 `FINGER_MAX_UM=50`，版图原样照搬 | 源极金属条分布电阻大（本分支实测 −12.8% 供电电流）、闩锁距离不足 |
| 3 个新 prompt 全部失败 | 原理图零裕量；版图动作只改几何 | 结论正确但无法闭环 |
| Laya 的排序与版图质量无关 | Laya 未在版图数据上训练；512-token 编码器 + 9 个粗旋钮 | Laya 实际给出的是近乎随机的先验 |

## 3. 新架构

```text
电路 builder ──► 结构分析（匹配对、对称网络、电流路径层级、级）
                   │
         ProPlan（动作空间：纵横比、最大 finger、配对模式、dummy、轨宽、decap、电容位置、屏蔽、re-finger）
                   │
   模板语法（知识编译层） ─ 共享扩散阵列 / 共质心 / 2D 交叉折叠 / dummy / 保护环 / 双保护条 / 电源网格 /
                   │        tap 列 / decap 填充 / MIM 单元阵列 / 多晶电阻蛇形 / 对称 trunk-bus 走线
                   ▼
   Magic DRC + GDS ─► Netgen LVS ─► 分布 RC 提取 ─► 物理原理图仿真 ─► 后仿 ─► 知识卡 critic
                   │                                                   │
                   └──── 并行候选（4–10 路）◄── Laya（选项文本按动作注入知识卡）+ 知识先验 + 探索
                                                   │
                                      trajectory.jsonl / 自博弈数据 ─► Laya 微调（版图策略）
```

### 3.1 模板语法（`src/chipjev/layout/pro/`）

- `mos.py` 共享扩散 finger 阵列：几何数值取自 PDK PCell 与 `sky130A.tech`（接触 0.17 µm、区宽 0.29 µm、
  短沟道 pitch 拉伸、栅头 0.275/0.32 µm 等），每个 S/D 区全高接触；一侧或两侧连续多晶栅条；端部 dummy 与匹配
  finger 共享扩散，栅极经外翻多晶头接到轨；M2 strap 横跨扩散区。
- `analysis.py` 从连接关系推断匹配对（输入对、镜像负载、共源共栅对、交叉镜像）与对称网络；**相同尺寸不等于匹配**。
- `planner.py` 图案（ABBA 一维共质心、mirror 两阵列对称）、DP 求每个 finger 的 S/D 方向以共享扩散；
  faithful 模式保持原理图 finger 宽与数目；大器件 2D 交叉折叠（ABBA/BAAB 行交替）；超高 finger 切段加 tap 列。
- `floorplan.py` 同高货架装箱（shelf packing）+ 纵横比扫描；N/P 阱堆叠或并排（竖直双保护条）；
  每行一条带 tap 的 M1+M2 宽轨；阱四周闭合保护环；M3 电源 strap 把所有行轨连成网格；空闲区填 MOS decap。
- `router.py` M3 竖直 trunk + M4 水平 bus；对称网络镜像落点、自对称网络落在轴上；最受约束的网络先布；
  多 trunk 网络先规划 bus 高度再落 trunk；无关网络避开匹配阵列；空间不足时加宽通道重试。
- `passives.py` MIM：等大单元 tile、连续 M4 顶板、底板放在低阻节点、全高 M3 底板引出；电阻：等长单元蛇形串联。
- `integrity.py` 逻辑—物理清单校验（finger 宽度和、dummy/decap 必须短接且接轨、电阻链与方块数、电容值），
  在任何仿真前拒绝篡改。

### 3.2 电学保真：不让版图偷偷改器件

实测发现：`wnflag=1` 下 SKY130 按 W/NF 选模型 bin，即便同 bin 内，W 相关参数也会移动固定偏置电流源的工作点。
一个高增益两级运放在按纵横比 re-finger 后，比例镜像的单位 finger 宽不再一致，增益从 64.6 dB 掉到 31 dB——**物理原理图（无寄生）就已失效**。因此：

1. **faithful 默认**：版图保持原理图 finger 宽与数目；只选择图案、折叠、dummy、轨、decap 等。
2. **三段归因**：`verify()` 对 pro 版图额外仿真 `reference.spice`（声明的物理网表，无寄生），得到
   原理图 → 物理原理图（re-finger 影响）→ 后仿（寄生影响）。
3. **re-finger 是显式动作**（`ProPlan.refinger`），只有物理原理图与后仿都重新合格才会被接受。
4. **layout-aware sizing**：`chipjev design --technology sky130 --finger-max 6` 让电路搜索按版图单元 finger 仿真，
   `finger_max_um` 随设计记录传入版图、提取和后仿；冻结研究的默认行为不变（仍为 50 µm）。

### 3.3 知识卡、检索与 critic（`layout/pro/knowledge.py`）

31 张卡片，25 张出自 IITM EE5325 第 48 讲（逐页标注），其余来自 SKY130 规则/模型与通用实践。每张卡声明作用位置：

| 作用位置 | 张数 | 例子 |
| --- | --- | --- |
| template（编译进生成器） | 18 | 共质心、dummy、同向、同电流方向、dummy 走线、单元器件、保护环、双保护条、叠层电源轨 |
| check（critic 可执行检查） | 21 | 质心距离、dummy 缺失、电流方向平衡、对称 trunk、轨 IR 压降、电流密度、输入电容失衡、输入-输出耦合、纵横比、LU(DRC) |
| action（loop 可调取舍） | 14 | 小阵列宜交指/大阵列宜共质心、**布线寄生限速时简单排列可能优于交指**（讲义 s17）、屏蔽但勿贴近高速线、decap、轨宽、re-finger |

检索是**确定性键控**（动作字段 + 实测症状），不是向量相似度：例如 PM 后仿下降 → 对 `pair_pattern` 动作注入
"布线寄生限速时简单排列可能优于交指"与"缩短高阻节点、Cc 靠近输出级"；供电电流后仿偏移 → 对 `rail_um` 注入
"叠层宽轨降低电源阻抗"、对 `refinger` 注入"re-finger 改变模型 bin，需要重新验证"。

### 3.4 目标驱动 loop（`search/pro_layout.py`，CLI 默认）

每轮从当前最优 ProPlan 生成一步邻居；知识先验（卡片与症状匹配 + critic 未通过项）与 Laya 概率（选项文本含注入卡片）
加权排序，保留一个探索名额；候选**并行**跑完整 DRC/LVS/PEX/物理原理图/后仿/critic；接受顺序：
后仿合格 > 目标（quality = critic 分 − 10·log10(面积/种子面积)，或 area/gbw/gain/pm）。
每个决策与被评估选项的实测结果写入 `trajectory.jsonl`。demo 的 `LayoutEvaluator` 与 `worker.py` 已切换到新生成器，
事件协议（rendered/evaluated/selected）保持兼容。

停止规则（每轮开始前按此顺序检查）：已有合格版图后连续 `patience`（默认 2）轮没有更好的合格版图即收敛停止；
已评估版图数达到 `max_evaluations`（严格生效，最后一批截断到剩余名额）；按上一轮耗时估计下一轮会超出
`budget_seconds` 时不再开始；incumbent 的一步邻居都已试过。停止原因写入 `optimization.json` 的 `stop`，
demo 页面在步骤 9 显示。demo 设置为 13 个版图、40 s、patience 2；CLI `chipjev layout` 默认
`--evaluations 8 --seconds 60 --patience 2`。

并行 worker 通过进程队列实时上报每个候选的验证步骤（layout → drc → lvs → extracting → postsimulating，
DRC/LVS 带 running/passed/failed 与违例数或器件/网络数，以及 worker 端时间戳）。网页把 Magic DRC 与
Netgen LVS 作为 layout loop（步骤 5–9）里的两个独立步骤显示，步骤 9 到 5 画有反馈箭头和迭代计数。每轮迭代
（种子 plan，然后是 Laya 从 incumbent 提出的一批候选，并行验证）按该批最慢的候选推进：当前步骤的标记和指向它的
箭头高亮，新一轮开始时反馈箭头高亮并流动；DRC/LVS 每轮重新检查并显示该批的结果（全部通过为绿色对勾，否则红叉
与被拒数量）。很快的步骤在画面上至少停留 0.35–1.1 s，不影响实测计时；最终状态取自被选中版图自己的 DRC/LVS 报告；
阶段计时用 worker 端时间戳。任何一个候选失败（例如布线空间不足）只记为被拒，不再中断整个 demo。

## 4. 实测结果

### 4.1 同一尺寸下与当前版本对比

| 电路 | 当前版本（Codex loop 最小面积） | 新版本（默认 plan） |
| --- | --- | --- |
| demo 高增益两级（cmota+inv_cas，13 MOS） | 8,686 µm²，合格 | **1,406 µm²，合格**（6.2×） |
| demo 高 GBW 两级（20 pF Miller） | 86,621 µm²，合格 | **21,945 µm²，合格**（3.9×）；re-finger 18,571 µm² 合格 |
| demo 单级高效 OTA（898 µm 输入对） | 24,485 µm²，合格 | **14,562 µm²，合格**（1.7×，近方形） |
| 新 prompt：telescopic | 8/8 不合格（saturation），最小 7,788 µm² | **1,696 µm²，合格** |
| 新 prompt：5T OTA | 8/8 不合格（currents），8,146 µm² | 1,775 µm²，currents 不合格（原理图电流恰在 10 µA 门限） |
| 新 prompt：两级 Miller | 8/8 不合格（stability），19,763 µm² | 9,082 µm²，stability 不合格（该偏置下原理图 PM 59.94° 已不合格） |

所有新版本 DRC=0、LVS 通过；生成 + Magic DRC/提取/GDS 0.5–1.0 s。后仿偏差示例（telescopic）：
增益 −0.03 dB、PM −0.4°、功耗 −1.7%。

### 4.2 鲁棒性：冻结 SKY130 研究的全部合格设计

135 个设计（12 任务 × ChipJev/TPE/random × 5 种子中有合格结果者），默认 plan 一次生成：
**132 个 DRC=0 且 LVS 通过（97.8%）**。剩余 3 个是同一设计的 3 个目标（输入对仅 0.75 µm 宽，需要"扩散外 strap"模板）。

"加宽电源轨"动作（`rail_um` 2.0）起初在测过的全部设计上都 DRC 失败（64–128 个 met2.2）：M3 电源 strap 下的
via2 阵列超出了 M2 轨的末端，留下相距 0.08 µm 的孤立 M2 焊盘，loop 只能一直拒绝这个动作。现在 via 只放在
strap 与轨的重叠区内；`rail_um` = 0.6 / 1.0 / 2.0 时 135 个设计均为 132 个 DRC+LVS 干净（同样 3 个布线失败）。

奇数 finger 的差分对原先生成 `A..A B..B A..A`（奇数长的 B 串无法共享扩散），整个对静默退回"左 A 右 B"：
高效 OTA 的 21 finger 输入对（切成 [4,4,4,3,3,3] 个抗 latch-up 段）质心误差 62.7 µm。奇数 finger 在一行内
不可能严格共质心（位置和之差必为奇数），现在用 `ABBA…ABBA + AB` 达到一个 pitch 的下限并保持共享扩散，交叉耦合的段/行再
抵消它。archived 设计中共质心（ABBA）模板的差分对从 70/142 升到 110/142；高效 OTA 输入对质心误差 62.7 → 0.12 µm、
面积 8,133 → 6,692 µm²；高增益两级 m6/m7 5.94 → 0.18 µm、面积 1,406 → 1,218 µm²；132 个干净设计的总面积 −10.7%
（单个最多 −33%），DRC/LVS 仍为 132/135。

最小宽度（0.42 µm）的 finger 放不下扩散区上方的 M2 strap（例如两级运放的共源共栅第二级、折叠共源共栅的
NMOS 对），此前 `plan_units` 直接拒绝，版图 loop 的每个候选都失败，demo 的在线搜索也因此找不到合格设计。
现在这类阵列把 strap 叠放在没有栅极 bar 的一侧（优先 rail 一侧）的扩散区外，M1 strip 向外延伸到各自的 strap，
M2 从其他网络的 strip 上方跨过；`side_needs` 相应地把 rail 金属推到 strap 之外。能放下 strap 的阵列完全不变。
结果：135 个 archived 设计全部 DRC=0 且 LVS 通过（135/135，原先的 3 个失败正是这种情况）；128 个版图面积完全不变，
4 个因可以用更紧凑的模板而略小。

### 4.3 端到端（demo 的 3 个 prompt，新鲜搜索，版图验证在电路搜索环内）

| prompt | Laya 决策 | 电路搜索 | 版图 loop（13 个完整候选） | 总计 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 高增益两级 | 3.0 s | 26.4 s | 28.5 s | **57.9 s** | 后仿合格，1,387 µm² |
| 高 GBW 两级 | 2.9 s | 73.7 s | 70.7 s | 147.4 s | 后仿合格，17,958 µm² |
| 单级高效 OTA | 3.4 s | 70.3 s | 69.1 s | 142.8 s | 后仿合格，10,854 µm² |

layout-aware sizing（`--finger-max 6`）重跑失败过的"两级 Miller GBW 10 pF"：搜索 104 s 得到 GBW 10.95 MHz、PM 61.1°；
版图 loop 35 s 后仿合格（GBW 10.44 MHz、PM 60.95°）。

### 4.4 Laya：检索注入 vs 实测结果微调

自博弈数据：28 条（设计×层级）记录，每条逐一评估全部 16 个一步动作（共 448 次完整物理流程评估；划分 1 用 18 条训练、10 条测试），
以实测目标的 softmax 作软标签，选项文本包含按动作注入的知识卡；按拓扑族划分训练/测试。

| 策略（未见拓扑族） | 划分 1：留出 tele+cmota（80 题） | 划分 2：留出 inv+cas（62 题） |
| --- | --- | --- |
| 随机 | 遗憾 4.29，选中最优 42.5% | 3.17，56.5% |
| 知识先验（仅检索） | 2.77，43.8% | 3.24，59.7% |
| Laya 基础模型 + 注入文本 | 3.67，41.3% | 4.95，53.2% |
| Laya（现用拓扑权重）+ 注入文本 | 3.48，57.5% | 4.21，50.0% |
| **Laya 自博弈微调（2.5 s）** | **0.80，70.0%** | **1.74，67.7%** |

样本量小（单目标、单种子、题目来自少数设计的随机子集），结论方向一致但幅度需扩大数据后确认。

## 5. 为什么不把知识只放进 prompt

1. Laya 是 512-token 的编码器 + 选项打分头，不是会读说明书推理的生成模型；注入的指南告诉它"什么是好的"，
   却不告诉它"这个动作对这个电路的影响方向与幅度"。实测它与随机相当。
2. 讲义约 90% 是结构性规则（共质心、dummy、同向、保护环、叠层电源……），根本不需要每次决策：
   编译进模板后每个版图都满足，速度 0 成本；放进 prompt 反而占掉稀缺的上下文。
3. 条件性规则本身有冲突（"用交指提高匹配" vs "限速时简单排列更好"），是否适用取决于实测症状——
   这正适合"按动作 + 症状检索"，并让微调学会何时采信。

## 6. 推荐路线（回答"注入 / 预训练 / 结合"）

1. **把规则编译成语法与检查（主杠杆）。** 用大模型离线把讲义、PDK 手册抽成结构化知识卡，人工审核后实现为模板或
   critic 检查；卡片带出处与作用位置，可追溯。
2. **动作级检索注入（保留）。** 只为"条件性取舍"卡片，键控检索，写进选项文本和先验；同时用于解释与 UI。
3. **用 EDA 实测做 Laya 微调（必须）。** 自博弈生成 (状态, 选项+卡片, 实测结果) 软标签，按拓扑族留出评估；
   检索文本随训练一起出现（retrieval-augmented fine-tuning），推理仍是 System One（约 10 ms，无检索延迟）。
4. **品味（taste）用专家成对偏好补充。** 对两个都合格的方案做人工偏好（`layout_preferences.py` 已有接口）。
5. **不做讲义文本预训练。** 语料小、定性、无几何/结果监督，无法转化为决策能力。

## 7. 局限与下一步

- 输入对 < 0.86 µm 宽时需要"扩散外 strap"模板（3/135）；MIM/电阻边界 dummy；输入对独立保护环；
  M5 电源网格（大电流输出级的轨阻仍造成约 −8% 电流偏移）；Magic antennacheck 与 EM 限值接入 critic。
- critic 的 IR/EM/耦合为代理量；质心检查对 mirror 图案会给出预期内的警告。
- 自博弈规模需要扩大到数百设计、多目标、多层级；并比较 layout-aware sizing 与 re-finger 两条路线。
- 端到端数字为单次运行；GPU 搜索不可逐位复现，应按研究协议报告多种子中位数。

## 8. 复现

```bash
# 新生成器 + Laya 在环 loop（默认）；--generator groups 使用旧流程，--legacy 使用最早的单行流程
PYTHONPATH=src .venv/bin/python -m chipjev layout RESULT.json.gz --output runs/pro --evaluations 12 --parallel 4
# layout-aware sizing
PYTHONPATH=src .venv/bin/python -m chipjev design "..." --technology sky130 --finger-max 6
# 自博弈数据与版图策略微调
PYTHONPATH=src .venv/bin/python -m chipjev.decisions.layout_selfplay collect designs.txt --output runs/selfplay
PYTHONPATH=src .venv/bin/python -m chipjev.decisions.layout_selfplay train runs/selfplay/rows.jsonl \
    --holdout tele cmota --output runs/layout-policy
PYTHONPATH=src .venv/bin/python -m chipjev layout RESULT.json.gz --output runs/pro --layout-policy runs/layout-policy/typed-decisions.pt
# 渲染对比图
.venv/bin/python reproduce/draw_pro_layouts.py out.png "title=path/layout.mag" ...
# 测试
PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/test_pro_layout.py
```
