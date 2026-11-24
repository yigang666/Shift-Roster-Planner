# 模拟原始排班数据

四份 CSV 共用上一级目录的 `members.csv`。覆盖 2026-11-29 至 2027-01-02，包含 19 位虚拟员工和 4 个组。在 **Master Roster** 上传员工文件和任意一份排班 CSV。横表请将请假代码设为 `AL`。

| 排班文件 | 检查日期 | 预期 |
| --- | --- | --- |
| `normal_long.csv` | 2026-12-03 | 覆盖正常，无需调班 |
| `day_senior_gap_long.csv` | 2026-12-03 | 三名 Senior 已请假。白班缺全程 Senior，18:00–20:00 也少一人。D01 的 S→D 可恢复正常 |
| `night_gap_wide.csv` | 2026-12-03 | 横向排班含 `AL`，原班次未知。夜班少一人，A01 可从休息改为夜班 |
| `month_end_incomplete_long.csv` | 2026-12-31 | 夜班跨月，缺少完整的 2027 年 1 月数据，求解应提示无法验证 |

回归测试中，搜索只检查目标日期，并将变更限制为一人一项。两份可修复数据还会验证员工同意、提交及导出。用 `python examples/simulated/generate.py` 重建 CSV。
