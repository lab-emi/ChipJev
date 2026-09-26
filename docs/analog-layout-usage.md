# 目标驱动模拟版图：运行与验收

实现对应 [设计方案](analog-layout-loop-v2.md)。当前支持 SKY130 1.8 V MOS、poly R、MIM C；新命令默认使用分组生成器和有限布局动作搜索。旧实验的默认仿真 API 和数据不变，原单行版图可通过 `--legacy` 比较。

## 运行

```bash
PYTHONPATH=src .venv/bin/python -m chipjev layout \
  experiments/layout/results/opamp-speed/result.json \
  --output runs/my-layout --device cuda --evaluations 8 --seconds 60
```

默认目标是缩小面积，同时必须通过严格功能/性能检查、全量 DRC、LVS、独立器件清单验证、分布式 RC 后仿及完整模拟测量。匹配组默认必须保留边缘 dummy。对每个候选固定输入偏置、电源、负载与温度。未指定输入偏置时，先在原理图探索一次并冻结，候选之间不会重新找工作点。

live demo 的高增益电路搜索以连续尺寸作低成本探索，另外两个 prompt 在制造网格上探索。三个 prompt 的严格验收、最终 xschem 原理图和所有布局均使用与 PCell 一致的制造网格尺寸。只有网格尺寸原理图和参考布局在同一个共模点通过，才接收该电路；随后固定此点比较布局，不能为某个布局重新校准共模点。

交互 demo 为在线仿真单独使用 2.5 秒超时，给网页服务与视频采集的调度开销留出余量；电路搜索仍受 180 秒总预算约束。原论文默认的 2 秒在线超时保持不变。调度、数值计算与预算截止仍可能影响搜索轨迹，单次成功耗时不是成功率承诺。

`--no-laya` 运行几何/测量提案器消融。`--input-bias 0.85` 指定工作点。`--objective` 支持 `area/gain/gbw/fom/noise/matching`。更细的约束通过 `--goal goal.json`：

```json
{
  "objective": "area",
  "require_dummies": true,
  "minimum": {"psrr_min_db": 30},
  "maximum": {"input_noise_rms_v": 0.0001, "internal_supply_drop_v": 0.005},
  "analog": {"noise_low_hz": 10, "noise_high_hz": 1000000,
             "supply_resistance_ohm": 20, "load_step_a": 0.00005,
             "pulse_rise_s": 0.0000000001, "temperature_c": 27}
}
```

这些数值只是输入格式示例，不是自动给用户假定的规格。缺失、非有限或未测量的指标不能通过约束。找不到合格解时返回失败，并保留所有候选与 `optimization.json`。时间预算在 EDA 阶段之间检查，已经启动的有超时上限的仿真允许结束。

`--sizing-evaluations 4` 额外尝试相邻电气 sizing，使用同一固定偏置与已选布局计划；这是独立的联合调整预算，结果写入 `joint-refinement.json`，不混入固定电路的面积改进。拓扑仍由现有电路搜索决定。

## 当前闭环能改变什么

- 依据输入差分对、连接和尺寸相同的电流镜等角色形成匹配组；不会把所有相同 W/L 的 MOS 自动视为匹配对。
- 交指、集中排列或二维共质心，8/12/20/32 单元的行打包，一列/两列 floorplan，以及合法的二倍单元分解。
- 同极性共享 guard domain、逐单元 tap 和明确连接的边缘 dummy；保留总宽度并报告网格量化及每个逻辑器件的物理映射。
- M1/M2 接入、M3 行总线、M4 列干线、需要跨列时使用 M5。按电流/压降粗估产生更宽电源候选，rail 动作也在相邻端口间距允许时加宽接入线；供电总线采用冗余过孔。
- 明确进入 reference/LVS/PEX 的 2 pF/5 pF tiled MIM decap，以及供电侧/输出侧放置。`shield_inputs` 是接地 M4 隔离干线的位置选择，**不是全路径屏蔽或基底噪声签核**。
- 几何代理和测量核模型只用于建议下一候选；Laya 对短列表中的合法动作给出概率，保留独立探索。接受与回退由实际 EDA 决定，保留面积/GBW/噪声的 Pareto 候选。

Laya 使用有限上下文，优先接收最新失败项、关键实测指标、目标与当前计划，再附器件角色摘要。每次决策保存完整状态和实际送入模型的压缩文本、token 数及截断标记；不能用冗长器件描述挤掉闭环反馈。

供电宽度的粗估依据固定 PDK 的 sheet R，不包含未经提供的 EM 电流密度限值。实际 PEX OP 电压给出内部 rail drop 与 ground rise；路线电阻之和另标为代理，不能当作有效电阻或 EM 通过。

## 证据

`physical.json`、`optimization.json`、`manifest.json`、`layout.mag/.gds/.svg`、`layout-intent.svg`、`reference.spice`、`lvs.spice`、`pex.spice` 以及每一候选的原始 DRC/LVS/ngspice 日志都保留。reference 在提取前生成；不能从提取网表反向补写。导出的 GDS 有独立回读验证测试。

模拟 fixture 输出输入折算积分噪声、谱密度、PSRR、供电阶跃、DC/内部 rail drop，以及 ±10 mV 扫描范围内相对 VDD/2 输出目标的差分偏移。偏移不在扫描范围内时为 `null`。差分 AC 输入归一为 1 V。全部 fixture 条件随测量保存。默认只要求测量成功，额外规格必须显式给定。

```bash
# 固定工作点的器件角与可复现 PDK local mismatch；样本失败会返回失败状态
PYTHONPATH=src .venv/bin/python -m chipjev layout INPUT.json \
  --output runs/robust --corners tt ss ff --mismatch-samples 8
PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/test_analog_layout.py tests/test_physical.py
```

随机种子映射为 ngspice 网表的 `.options seed=seed+1`，在 PDK 随机参数求值前生效；不能仅依赖启动配置中的 `setseed`。这是 PDK 局部随机失配，不能证明共质心对空间/热梯度的抑制。RC/passive corner 保持标称，未宣称制造良率。

## 工程师偏好数据接口

```bash
PYTHONPATH=src .venv/bin/python -m chipjev.decisions.layout_preferences export \
  runs/my-layout --family ota5 --output reviews.jsonl
```

导出的是同一目标下两个均合格方案的待审比较，`preferred/reviewer/reason` 留空，`label_source=unreviewed`。专家补全偏好和理由后才可标为 `expert`。训练命令拒绝未标注数据，按完整拓扑族划分训练和保留集：

```bash
PYTHONPATH=src .venv/bin/python -m chipjev.decisions.layout_preferences train \
  reviewed-a.jsonl reviewed-b.jsonl --holdout-family folded-cascode \
  --output runs/layout-weights --device cuda
```

当前发布仍使用现有的电路 typed-decision 权重，没有伪造专家标签或宣称已经训练出专业版图 taste。专家语料采集与跨族效果评估仍需要真实标注；代码已提供导出、校验、训练和保留集评估入口。

当前也没有扩散共享、全路径对称布线、完整 WPE/LOD/基底噪声/热场模型、全芯片密度/天线闭合或 EM 签核。几何代理尚未校准，三个公开 prompt 是开发回归，不是未见电路泛化基准。应从实际目标与失败轨迹继续扩展这些能力，而不是以视觉规则评分替代电气验收。
