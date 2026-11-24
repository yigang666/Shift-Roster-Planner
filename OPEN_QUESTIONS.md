# Open business questions

Confirm these PRD items before adopting the app for live roster decisions.

| PRD | Pending decision | MVP behavior |
| --- | --- | --- |
| Q01 | Can Off become Standby? | Disabled by default; Reset-to-Standby is allowed. |
| Q02 | Which day defines the daily hour limit, and how should Night Early be treated? | Split by Singapore calendar day; allow the isolated Night Early shift exception. |
| Q03 | Where do overnight hours belong at month end? | Split actual time between calendar months. |
| Q04 | Is a minimum rest interval required? | Use continuous-work protections; no independent rest interval. |
| Q05 | Must Standby count be preserved after changes? | Report baseline rotation deviations; allow conversion in effective roster. |
| Q06 | Can a surplus shift be directly reassigned? | Disabled by default. |
| Q07 | Must Day have three complete D assignments? | Use headcount by staffed interval with mandatory full-shift Senior coverage. |
| Q08 | How should overnight work interact with full-day Leave and what codes are used? | Apply Leave to the roster start date; use the import code mapping. |
| Q09 | What existing overtime and swap codes occur in real schedules? | Use explicit import mappings, and request correction for unfamiliar codes. |
| Q10 | What search bounds and ranking fit manager practice? | Start with the documented defaults and allow configurable search bounds. |
| Q11 | Do Off and Reset carry different penalties? | Apply the same rest-day penalty. |
| Q12 | Where will managers run the shared service and how will they identify themselves? | A shared app instance with operator names and shared persisted state. |
