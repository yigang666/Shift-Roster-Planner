# Business rules

The [PRD v1.1](Shift_Roster_Planner_PRD_v1.1.md) governs any discrepancies. Default settings are in `config/rules.json`.

| Rule | Implementation and consequence |
| --- | --- |
| H01, H03, H07 | Work uses complete Singapore-local intervals. Reject overlapping work and adjacent work exceeding 12 continuous hours. Explicitly reject night work followed immediately by a Day or Standby assignment. |
| H02, H11 | A leave record occupies the full roster date. The validator rejects assigning work over effective Leave. An eligible Critical case may request cancellation through the separate leave workflow. |
| H04, H05 | S_OT ends at 20:00. N_EARLY starts at 18:00 and ends at 08:00 the following date. Its 14-hour exception covers the isolated shift. |
| H06 | Compute minimum staffing separately for 08:00–18:00, 18:00–20:00 and 20:00–08:00. Each minimum is 3 and the normal daytime target is 4 before 18:00. Protect the baseline deficits across all altered dates and require the target to meet the minimum. |
| H08 | The confirmation service records and checks consent for every changed employee before committing an entire plan. |
| H09, H10 | Split work at local midnight for daily and calendar-month totals. Use 12 hours daily and 264 monthly. Include the full 14 hours of N_EARLY in month totals and require month and boundary data before commit. |
| H12 | Baseline Standby deviations are diagnostics. Per-person 12-day cycle diagnostics require a known cycle anchor and a complete roster block. |
| H13 | Independent minimum rest has no configured threshold. Continuous-work check remains applicable. |
| H14 | Each complete Day and Night interval requires at least one Senior covering it end to end. S alone and N_EARLY together cannot fulfill the Day requirement by piecing coverage together. A missing Senior makes that date Critical even with sufficient staff. |

Normal coverage and smaller or simpler adjustments rank feasible options. Cross-team and cross-date swaps are eligible. The action list excludes direct reassignment and Off-to-Standby by default pending confirmation. Standby conversion and Standby OT have the same time interval but carry distinct administrative labels.
