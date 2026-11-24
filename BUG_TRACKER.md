# MVP bug tracker

| ID | Severity | Reproduction and observed result | Expected result | Root cause and fix |
|---|---|---|---|---|
| QA-01 | High | Cancel leave over a recorded night shift for an employee now working the next morning. The raw leave cancellation restored both adjacent assignments. | Reject cancellation until the work schedule permits restoring the shift. | The UI used the storage transformation directly. The service now independently validates restored shifts and rejects a conflicting write. |
| QA-02 | High | Save and accept a swap, add leave, then reverse the leave. A content-only baseline comparison could make the pre-edit plan eligible again. | A plan invalidated by a roster change remains stale after a reversal. | Effective-roster changes now persist the stale status atomically with the roster. |
| QA-03 | High | Request a change on a non-target shift already missing its full-shift Senior. The old validator permitted work changes that preserved the same Senior gap. | A changed shift must satisfy H14. | Transition validation now checks H14 on affected work intervals, preserving visibility of untouched inherited gaps. |
| QA-04 | Medium | Enable Standby OT and disable Standby Conversion for a Senior on Standby. Search omitted the enabled extension. | Return S_OT and preserve existing refusals across equivalent actions. | Search previously generated only the canonical Conversion. It now falls back to S_OT and treats equivalent extension refusals consistently. |

QA-01 and QA-02 have named workflow regression tests. QA-03 has a focused validator regression in addition to TC29 and TC33. QA-04 has a configuration and equivalent-refusal regression. Date scope and available data are reported separately from business-rule validation.
