# Shift Roster Planner & Arrangement Advisor

## Product Requirements Document (PRD) v1.1

- 日期：2026-11-24
- 状态：需求基线，待确认事项见第 12 节
- 使用者：两名 Shift Manager
- 产品定位：内部排班决策辅助工具（Decision Support System）
- 数据规模：19 名员工，4 个组（14 Senior、5 Junior）
- v1.1 变更：新增员工资历分类及完整12小时 Senior Coverage 强制约束；保留 v1.0 其他规则。

## 1. 产品背景与目标

目前员工请假导致部分日期白班或晚班人力不足。Manager 需要手动检查员工前后班次、工时、休息日及其他请假情况，寻找 OT、Recall、Swap 等方案，再逐一询问员工是否同意。该过程繁琐且容易遗漏跨日、跨月冲突。

产品目标：导入已有 Schedule，识别人力缺口，自动搜索可行调班方案，按优先级展示具体人员、日期、变更、额外工时和影响；由 Manager 获取员工同意后提交变更。

非目标：自动批准请假、自动强制调班、员工自助门户、工资计算、历史 OT 公平分配、云服务或大模型依赖。

## 2. 用户与使用流程

仅两名 Manager 使用。两人共享同一份有效 roster；无需员工账号。Manager 负责导入数据、模拟请假、选择方案、记录员工同意或拒绝、提交及导出。建议记录操作人和时间。

流程：导入 Schedule → 校验 → 输入新增 Leave 或选择已有缺口 → Coverage Checker → Arrangement Solver → 排序及比较 → Manager 联系员工 → 记录反馈 → 重新验证 → 整组提交 → 导出最新 Roster。

拒绝某项安排后，保留原排班，记录对应人员、日期和拒绝范围，重新搜索。任何建议方案均不自动生效。

## 3. 已确认业务背景

| 项目 | 规则 |
|---|---|
| 员工 | 19 人 |
| 分组 | 4 组，三组各 5 人，一组 4 人 |
| 基础周期 | DNOR DNOR DNOS（12 天） |
| 每日班组 | 一组白班、一组晚班 |
| Standby | 每人每 12 天一次，轮流安排，每个自然日 1–2 人（基础 roster） |
| 实际输入 | 已有 Schedule，可能包含 Leave 和偏离基础周期的记录 |
| 跨组安排 | 允许 |
| 历史 OT 公平性 | 不需要 |
| 员工资历 | Senior = 非新人；Junior = 新人 |

| 示例组别 | 总人数 | Senior | Junior |
|---|---:|---:|---:|
| A | 5 | 4 | 1 |
| B | 5 | 4 | 1 |
| C | 5 | 3 | 2 |
| D | 4 | 3 | 1 |
| 合计 | 19 | 14 | 5 |

组名为示例，实际人员资历由 Manager 在员工主数据中配置，不根据姓名或组别推断。

基础周期用于参考、校验和可选生成，不得覆盖导入的真实 Schedule。组别用于展示，不限制候选人搜索。Standby 转 D 后允许实际 S 数减少；原始轮换要求与调整后覆盖要求分别处理。

### 3.1 Shift 定义

| Code | Start | End | Hours |
|---|---|---|---:|
| D | 08:00 | 20:00 | 12 |
| N | 20:00 | 次日 08:00 | 12 |
| O | — | — | 0 |
| R | — | — | 0 |
| S | 08:00 | 18:00 | 10 |
| S_OT | 08:00 | 20:00 | 12 |
| N_EARLY | 18:00 | 次日 08:00 | 14 |
| L | — | — | 0（请假状态，不代表原始班次） |

N 和 N_EARLY 的班次日期为开始日期。实际工作区间使用完整 datetime，时区 Asia/Singapore。

## 4. Manpower Coverage

| 时间段 | 正常标准 | 紧急最低标准 |
|---|---:|---:|
| 08:00–18:00 | 4 | 3 |
| 18:00–20:00 | 3 | 3 |
| 20:00–次日 08:00 | 3 | 3 |

以上时间段模型沿用此前方案：正常白班为 3D 加 1S（S 是补充人数而非独立岗位）；允许等效人数覆盖。晚间 18–20 点可由 D、S_OT、N_EARLY 补充。夜间至少 3 人。若业务要求必须有三个完整 D 而非等效分段覆盖，需确认后启用额外约束。

- NORMAL：所有区间达到正常标准。
- DEGRADED：达到紧急最低标准但未达到正常标准，提示 Manager。
- CRITICAL：任一区间低于紧急最低标准，必须提示缺口。

按实际工作区间的起止事件计算覆盖，不重复统计同一员工。输出日期、区间、当前人数、目标人数、缺口、人员名单。已有其他缺口不得被隐藏或恶化；相关搜索范围内未解决缺口必须明确标注，不能将部分修复称为完整方案。

### 4.1 Senior Coverage（新增强制要求）

每个 Day Shift（08:00–20:00）和 Night Shift（20:00–次日08:00）至少有一名 Senior（非新人）完整覆盖该12小时区间。正常及紧急标准均适用，不允许因 Critical 或人数充足而豁免。

- Senior D、S_OT 或 S 转 D 可满足白班要求；普通 S 仅至18:00，不满足完整覆盖。
- Senior N 或 N_EARLY 可满足晚班要求；N_EARLY 仅覆盖白班最后2小时，不能独自满足白班 Senior 要求。
- 同一完整班次必须存在至少一名全程覆盖的 Senior，不能将不同 Senior 的部分区间拼接作为替代。此为对新增规则的明确实施解释。
- Leave 员工不计入覆盖；资历未知不得计为 Senior。
- 即使人数达标，Senior 不足仍判定 CRITICAL；单独显示 SENIOR_SHORTAGE，可与 HEADCOUNT_SHORTAGE 同时出现。
- Solver 必须同时满足人数与 Senior 约束，并检查所有受影响班次，不得通过调走唯一 Senior 制造新的缺口。
- 输出每个完整班次的 Senior 人数、姓名、缺口及调整前后对比。

## 5. Hard Constraints（强制约束）

| ID | 规则 | 实现要求 |
|---|---|---|
| H01 | Night Shift Protection | 刚结束 N/N_EARLY 不得立即接 D 或 S；同时禁止其他导致超时的连续接班 |
| H02 | Leave Protection | 请假期间不得安排工作；仅 Critical 情况允许提出取消 Leave 请求，员工同意并完成取消后才可提交 |
| H03 | No Overlap | 同一员工工作区间不得重叠 |
| H04 | Standby OT | S 最多延长 2 小时至 20:00 |
| H05 | Night Early Start | 明确允许 18:00 至次日 08:00，连续 14 小时，为 H07/H09 的特定例外，不得泛化为其他 14 小时班次 |
| H06 | Coverage Protection | 不得造成新的最低人力缺口或恶化已有缺口；完整方案须修复目标缺口 |
| H07 | Continuous Working | 一般连续工作不超过 12 小时，H05 除外 |
| H08 | Confirmation | 涉及员工全部同意后才允许整组提交 |
| H09 | Daily Hours | 一般每天最多 12 小时；H05 例外的自然日累计口径待确认 |
| H10 | Monthly Hours | 每人每月最多 264 小时，N_EARLY 按实际 14 小时计入，不豁免月上限 |
| H11 | Full-day Leave | 不支持半天或小时级请假 |
| H12 | Standby Rotation | 基础 roster 每个自然日 1–2 人 Standby，每人每 12 天一次；调整后允许转换为 D |
| H13 | Rest | 未定义独立最短休息小时数；不得把连续工时限制误认为最短休息规则 |
| H14 | Senior Coverage | 每个完整 D/N 时间区间至少一名全程在岗 Senior；正常与紧急标准均不可豁免 |

连续工时检查须合并首尾相接的工作区间。跨日和跨月检查须读取边界外相关班次。建议暂按自然日、自然月拆分实际工时；N_EARLY 仅豁免其自身引起的超限，不允许额外工作叠加。该统计口径为建议，正式上线前须确认。若数据不足以验证月上限或前后班次，标记 UNVERIFIED，不允许正式提交。

## 6. Arrangement Actions

| Action | 变更 | 额外计划工时 | 状态 |
|---|---|---:|---|
| Standby OT | S → S_OT | +2 | 已确认 |
| Standby Conversion | S → D | +2 | 已确认 |
| Night Early Start | N → N_EARLY | +2 | 已确认 |
| Off Recall | O → D/N | +12 | 已确认 |
| Reset Recall | R → D/N | +12 | 已确认 |
| Reset Standby | R → S | +10 | 已确认 |
| Off Standby | O → S | +10 | 按重复 R → S 的表述推定，待确认 |
| Same-day Swap | 两名员工同日交换班次 | 按实际差额 | 已确认 |
| Cross-date Swap | 不同日期交换班次 | 按实际差额 | 已确认 |
| Cross-team Swap | 跨组交换 | 按实际差额 | 已确认 |
| Direct Reassignment | 如富余 N → D | 0 | 建议，待确认 |
| Cancel Leave Request | 恢复经确认的原班次 | 按恢复工时 | Critical 时允许询问 |
| Combined Arrangement | 多人、多日、多种 Action | 按实际差额 | 已确认目标能力 |

S_OT 与 S→D 覆盖时间相同，应合并等效方案或明确其行政记录差异。Swap 必须验证所有参与员工及受影响日期，不能假设必然增加人力。额外计划工时不等同于工资意义上的 OT。

## 7. 数据设计

### 7.1 存储策略

MVP 采用 UTF-8 CSV 存储业务数据，JSON 存储规则。Python Data Access Layer 隔离文件操作，便于迁移 SQLite。两名 Manager 使用同一个应用实例和共享数据源，不能各自维护独立 CSV 副本。

### 7.2 CSV Schema

| 文件 | 字段（建议） | 用途 |
|---|---|---|
| members.csv | member_id,name,team,active,experience_level | 员工主数据（SENIOR/JUNIOR） |
| master_roster.csv | date,member_id,source_shift,planned_shift,leave_status,import_id | 不可变导入基线 |
| leaves.csv | leave_id,member_id,start_date,end_date,status,source,original_shift,updated_by,updated_at | 已有及新增 Leave 的规范化记录 |
| plans.csv | plan_id,base_revision,status,score,created_by,created_at | 方案主记录 |
| arrangements.csv | action_id,plan_id,member_id,date,old_shift,new_shift,action,consent_status | 方案明细 |
| unavailability.csv | member_id,date,action,reason,status | 拒绝及不可用条件 |
| shift_definitions.csv | shift,start_time,end_time,end_day_offset,hours | 班次定义 |
| audit_log.csv | event_id,actor,timestamp,event_type,entity_id,revision,details | 审计历史 |

主键：members.member_id；master_roster 的 (import_id,date,member_id)；其余使用各自唯一 ID。所有外键、枚举、日期、重复行由应用验证。日期 ISO YYYY-MM-DD。experience_level 为必填枚举 SENIOR/JUNIOR；缺失或非法值须提示 Manager 修正，不能默认为 SENIOR。初始测试数据按 14 Senior、5 Junior 及第3节分布生成。

### 7.3 原始 Schedule 含 Leave 的处理

支持横向 roster（员工 × 日期）导入并转换为纵向格式；也支持标准纵向 CSV。实际 Leave code 通过导入映射配置，不假设只有 L。

```csv
date,member_id,source_shift,planned_shift,leave_status,import_id
2026-12-01,A01,D,D,none,I001
2026-12-01,A02,L,,approved,I001
2026-12-01,A03,N,N,none,I001
2026-12-01,A04,S,S,none,I001
```

A02 的原始班次未知，不能擅自推断为 D。可根据可信周期及相邻记录提出推断供 Manager 确认；未确认时不能生成确定的取消 Leave 恢复方案。导入 Leave 与 leaves.csv 关联去重，避免双重扣减。保留原始代码和导入文件；新 Leave 及已批准安排以变更记录覆盖基线。取消 Leave 不删除历史记录。

全日 Leave 对跨午夜 N 的具体含义（按班次开始日期还是自然日禁止任何工作）需确认；建议先按 roster 班次日期处理并在 UI 明示，不能悄悄采用另一口径。

### 7.4 两名 Manager 并发保护

建议单一 Streamlit 服务进程或具备跨进程文件锁的服务；所有写入通过 Data Access Layer。使用 revision 乐观并发检查，提交前加锁、重新读取、重新校验。CSV 多文件提交采用完整快照目录加原子切换 manifest 的方式，避免只写入 Swap 的一半；保留旧版本用于恢复。第二名 Manager 提交过期方案时提示刷新并重新计算。若不能可靠实现上述机制，改用 SQLite 事务，CSV 保留为导入导出格式。禁止直接编辑正在使用的 CSV。

### 7.5 规则配置示例

```json
{
  "timezone": "Asia/Singapore",
  "coverage": {"day_08_18_normal": 4, "day_08_18_min": 3, "day_18_20_min": 3, "night_min": 3},
  "senior_coverage": {"day_min": 1, "night_min": 1, "require_same_senior_full_shift": true, "emergency_exception": false},
  "base_standby": {"min": 1, "max": 2, "cycle_days": 12},
  "hours": {"continuous_max": 12, "daily_max": 12, "monthly_max": 264, "minimum_rest_hours": null, "night_early_exception": true},
  "actions": {"standby_ot": true, "standby_conversion": true, "night_early": true, "off_recall": true, "reset_recall": true, "reset_standby": true, "off_standby": false, "cross_date_swap": true, "cross_team_swap": true, "direct_reassignment": false, "critical_leave_cancel_request": true},
  "search": {"days_before": 3, "days_after": 3, "max_changed_members": 4, "max_changed_assignments": 8, "time_limit_seconds": 30},
  "ot_fairness": false
}
```

搜索参数为建议默认值，不是已确认业务限制；待确认动作默认关闭。

## 8. Arrangement Solver 与优先级

推荐 Python + Google OR-Tools CP-SAT。Rule Engine 独立于 Solver，负责校验候选和最终方案。AI 不参与硬约束判断。

### 8.1 搜索流程

1. 读取指定 revision 的有效 roster，合并已批准 Leave 和已提交 Arrangement；可模拟 pending Leave。
2. 检测目标缺口；无缺口则返回无需安排。
3. 读取搜索窗口、相关完整月份及边界班次。
4. 为所有 19 名员工生成允许的候选动作，排除拒绝及不合规人员。
5. 建立员工、日期、班次决策变量及人数覆盖、Senior 完整班次覆盖、工时、Swap 联动约束。对每个完整 D/N 区间，约束能够全程覆盖该区间的 Senior 员工决策变量之和至少为1；独立 Validator 再次验证。
6. 搜索单人和多人组合，验证目标缺口与所有受影响日期。
7. 去除重复和无关变更；按优先级排序，展示可行方案。
8. 若 Critical 且常规方案不可用，单独展示有条件的取消 Leave 请求，不计入已可执行方案。
9. Manager 记录反馈后重新求解；提交前再次校验。

### 8.2 搜索完整性

“所有方案”指在明确日期窗口、允许动作、最大变更人数和次数内的可行方案。默认前后 3 天，可扩大至 12 天或自定义范围。月工时检查不受搜索窗口限制。支持 Top N 展示及分页；采用重复求解加排除已找到解的约束，或固定范围可行解枚举。区分 COMPLETE、PARTIAL/TIMEOUT、INFEASIBLE、UNKNOWN。超时不能宣称无解或已找到全部方案。取消 Leave 的条件方案与普通可行方案分开。

### 8.3 排序策略（建议）

先按硬约束过滤，再按以下字典序排序：

1. 正常覆盖优先于仅满足紧急标准。
2. 常规方案优先于需要取消 Leave 的条件方案。
3. 优先减少受影响员工数及休息日占用。
4. 优先减少额外计划工时及跨日期变更。
5. 优先简单方案，稳定排序以便复现。

建议同等级动作偏好：S OT/转换、N Early Start、简单 Swap、跨日期 Swap、O/R Recall、复杂组合。此偏好不是绝对顺序，必须以实际覆盖及影响为准。不对 O 和 R 设置不同惩罚，除非 Manager 确认两者区别。不考虑历史 OT 公平性。

### 8.4 输出字段

方案编号、排名、覆盖等级、涉及员工、每项变更的日期及前后班次、额外工时、员工月工时前后对比、受影响日期、覆盖前后对比（含 Senior 名单及人数）、规则检查结果、推荐理由、需确认人员、搜索范围及完整性状态。

## 9. 功能需求与验收标准

| ID | 功能 | 优先级 | 验收标准 |
|---|---|---|---|
| FR01 | Schedule 导入 | P0 | 支持含 Leave 的 CSV、横纵格式转换、错误行预览、重复校验；不覆盖历史 |
| FR02 | Roster 查看 | P0 | 按月、组、员工查看原始和有效排班 |
| FR03 | Leave 管理 | P0 | 新增全日/多日 Leave、模拟、取消、导入去重 |
| FR04 | Coverage Dashboard | P0 | 精确显示三个时间区间人数缺口、完整 D/N Senior 缺口和状态 |
| FR05 | Constraint Validator | P0 | 检查全部硬约束（含 H14）、跨日跨月及数据完整性 |
| FR06 | Arrangement Advisor | P0 | 搜索允许动作及多人组合，支持跨组跨日期 Swap |
| FR07 | Ranking & Compare | P0 | 展示排名、影响、工时、人数及 Senior 覆盖和搜索完整性 |
| FR08 | Confirmation Workflow | P0 | 全员同意后提交；拒绝后重新计算；取消 Leave 单独确认 |
| FR09 | Shared Data & Audit | P0 | 两人共享数据，拒绝过期提交，原子更新、可追溯 |
| FR10 | CSV Export | P0 | 导出最新有效 roster、变更清单及方案 |
| FR11 | Base Roster Generator | P1 | 可选生成基础周期，不覆盖导入数据 |
| FR12 | Rule Configuration | P1 | Manager 可调整搜索参数和已批准业务配置，记录版本 |
| FR13 | Notification Draft | P1 | 生成 Teams/Email 联系员工的文字，不自动发送 |
| FR14 | Advanced Analysis | P2 | 未来人力预测、批量 Leave 模拟、统计报表 |

P0 为 MVP 必须交付，P1 为后续迭代，P2 为长期扩展。

## 10. UI 与方案状态

五个主要页面：

1. Master Roster：导入预览、月历、组别及 Senior/Junior 筛选、资历标识、原始/有效切换。
2. Leave Management：已有及新增 Leave、模拟、取消记录。
3. Manpower Dashboard：日期和时段覆盖、人数及 Senior 缺口独立定位。
4. Arrangement Advisor：搜索参数、排名、方案对比（含 Senior 覆盖）、员工确认清单。
5. Confirmation & History：确认、拒绝、提交、审计及导出。

状态机：PROPOSED → AWAITING_CONFIRMATION → READY_TO_COMMIT → COMMITTED。其他状态 REJECTED、CANCELLED、STALE、UNVERIFIED。条件取消 Leave 的方案在 Leave 正式取消前不可进入可提交状态；任何已确认方案若基线变化须重新校验。

## 11. 测试与验收场景

| ID | 场景 | 预期 |
|---|---|---|
| TC01 | 原始 roster 满足正常覆盖 | 无需安排 |
| TC02 | 导入已含 Leave，再次导入同一记录 | 不重复扣减 |
| TC03 | 白班仅 2D+1S，晚间缺 1 人 | S_OT 或 N_EARLY 可补晚间；仍提示正常覆盖缺口 |
| TC04 | N 刚结束，立即接 D/S | 拒绝 |
| TC05 | N_EARLY 单次 14 小时 | 允许指定例外，仍检查月上限及相邻班次 |
| TC06 | 普通连续 14 小时工作 | 拒绝 |
| TC07 | O/R Recall 导致月工时 265 | 拒绝 |
| TC08 | 月工时恰好 264 | 其他规则满足时允许 |
| TC09 | N 跨月 | 按已确认统计口径计算两月工时 |
| TC10 | 同日 Swap 造成夜班不足 | 拒绝 |
| TC11 | 跨日期 Swap 解决目标但造成未来缺口 | 拒绝 |
| TC12 | 多人组合恢复正常标准 | 返回人员、日期及完整变更 |
| TC13 | Critical 且常规无解 | 可提出取消 Leave 请求，不自动取消 |
| TC14 | Leave 原班次未知 | 禁止未经确认的恢复 |
| TC15 | 一名员工拒绝 Swap | 整组不提交，重新计算 |
| TC16 | 两名 Manager 同时提交 | 后提交的过期方案被拒绝或重新验证 |
| TC17 | 写入中途故障 | 不产生半完成 Swap，旧快照可恢复 |
| TC18 | 搜索超时 | 显示部分结果或未知，不宣称穷尽 |
| TC19 | 缺少完整月工时或边界班次 | 标记未验证，不允许提交 |
| TC20 | 仅 3 人紧急覆盖 | DEGRADED，不误报 NORMAL |
| TC21 | R→S 且满足全部约束 | 可进入候选方案 |
| TC22 | N_EARLY 与相邻班次形成超限 | 拒绝，例外不得扩展 |

| TC23 | 白班3名 Junior，无 Senior | CRITICAL，触发搜索 |
| TC24 | 晚班3名 Junior，无 Senior | CRITICAL，触发搜索 |
| TC25 | 白班1 Senior D + 2 Junior D | DEGRADED，满足紧急标准 |
| TC26 | 白班3 Junior D + 1 Senior S | CRITICAL，Senior 未覆盖18–20点 |
| TC27 | TC26 的 Senior S 转 D 或 S_OT | 其他约束满足时 NORMAL |
| TC28 | Senior N_EARLY 覆盖完整夜班 | 满足夜班 Senior 约束，不满足白班完整 Senior 约束 |
| TC29 | Swap 调走另一班唯一 Senior | 拒绝 |
| TC30 | 两名 Senior 分段覆盖白班但无人全程覆盖 | 拒绝 |
| TC31 | Senior Leave 导致人数仍足但无 Senior | CRITICAL，搜索 Senior 候选 |
| TC32 | 员工资历缺失或非法 | 导入校验报错，不计为 Senior |
| TC33 | 多人跨日期组合同时修复人数和 Senior 缺口 | 仅返回所有受影响班次合规的完整方案 |
| TC34 | 无可用 Senior 且 Critical | 可建议符合条件的 Senior 取消 Leave；未同意不得提交 |
| TC35 | 虚拟员工数据 | 19人，14 Senior、5 Junior，符合四组分布 |

建议用 pytest 建立单元、集成、端到端及小规模穷举对照测试。上线前以匿名化真实 roster 回测 Manager 已处理案例。

## 12. 待确认事项与决策记录

| ID | 待确认事项 | 建议处理 |
|---|---|---|
| Q01 | 重复 R→S 是否表示 O→S 和 R→S | R→S 已确认；O→S 暂关闭 |
| Q02 | 12 小时每日上限按自然日、班次日还是滚动 24 小时；N_EARLY 的例外范围 | 建议自然日拆分，明确例外后上线 |
| Q03 | 月工时按实际自然月拆分还是班次开始月归属 | 建议自然月实际工时拆分 |
| Q04 | 最短休息时间是否另有公司规定 | 不擅自设定；正式上线前核实 |
| Q05 | 1–2 S 是否也要求调整后严格保留 | 建议仅基础 roster，因 S 可转换且为补充人数 |
| Q06 | 富余 N 直接转 D 是否允许，不要求对换 | 建议支持，默认关闭 |
| Q07 | 白班是否必须有三个完整 D，或允许分段等效覆盖 | 当前采用分段人数模型，待确认 |
| Q08 | 全日 Leave 对跨午夜班次的日期口径、实际 Leave codes | 导入样例后确认 |
| Q09 | 实际 Schedule 是否包含既有 OT、Swap 或其他班次代码 | 导入映射支持扩展 |
| Q10 | 搜索窗口、最大变更人数、排序偏好 | 可配置，Manager 试用后调整 |
| Q11 | O 与 R 是否有额外业务差异 | 暂同等处理 |
| Q12 | 两名 Manager 的部署位置及身份识别方式 | 建议经批准的内部共享服务，非公网 |

已关闭决策：N Early Start 允许；O/R 可 Recall；S 可转 D；跨日期及跨组 Swap 允许；不支持部分日 Leave；不考虑历史 OT 公平性；月上限 264 小时；两名 Manager；输入 Schedule 包含 Leave。

## 13. 技术架构与实施计划

推荐：Python、Pandas 或标准 csv、OR-Tools CP-SAT、Streamlit、pytest。业务数据 CSV，规则 JSON；不需要 LLM API。部署在经批准的本地或内部环境，限制访问，备份数据，不将真实员工数据提交到公开 GitHub。

```text
shift-roster-planner/
  app.py
  data/                 # 私有数据及版本快照
  config/rules.json
  domain/               # Member, Shift, Leave, Plan
  repository/           # CSV adapter, locking, revision
  engine/
    roster_importer.py
    effective_roster.py
    coverage_checker.py
    constraint_validator.py
    arrangement_solver.py
    priority_ranker.py
  services/             # confirmation, commit, export
  tests/
  examples/             # 虚拟员工及测试 roster
  README.md
```

| 阶段 | 交付 | 退出标准 |
|---|---|---|
| Phase 1 | 数据模型、CSV 导入、有效 roster、Leave 管理 | FR01–03 通过，含 Leave 样例可复现 |
| Phase 2 | Coverage 与工时校验 | FR04–05 通过，跨日跨月测试通过 |
| Phase 3 | Solver、动作、排序 | FR06–07 通过，与小规模穷举结果一致 |
| Phase 4 | 确认、并发保护、导出、UI 集成 | FR08–10 通过，故障恢复测试通过 |
| Phase 5 | Manager UAT、规则确认、上线 | P0 全部通过，关键待确认事项关闭，真实数据使用获批准 |
| Phase 6 | P1/P2 功能 | 按实际反馈迭代 |

## 14. Definition of Done

MVP 必须能够读取包含既有 Leave 的真实结构 Schedule，输入新增全日 Leave，准确识别人数与 Senior 缺口，搜索并排序指定范围内合规方案，解释每项人员变更及工时影响，记录 Manager 获得的员工同意，拒绝不合规或过期提交，完整保存历史并导出有效 roster。所有关键测试通过（包括 TC23–TC35）；每个已提交方案必须通过 H14；未确认规则不得被开发 Agent 自行当作既定需求。对无法求解、数据不足或超时的情况必须明确报告。

开发 Agent 应先实现领域模型和测试，再实现求解器与 UI。不得为了使测试通过而放宽硬约束；任何规则变更须更新本 PRD、配置及对应测试。
