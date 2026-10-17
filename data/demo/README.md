# Chronicle demo dataset

Synthetic corpus used for the demo video and integration testing.  
**No real people, no real PII.**  All names, emails and events are fictional.

## What it contains

```
part_a/   (April – early May 2026 — initial ownership state)
  email/
    e01_payments_intro.md    Alex Nova announces they own payments
    e02_infra_role.md        Manager assigns all service owners
    e03_migration_deadline.md  Migration set for 30 Jun 2026
  slack/
    s01_channel_day.md       Team chat confirming owners
  notes/
    n01_q2_plan.md           Q2 ownership snapshot + key dates
    n02_meeting_notes.md     3 May sync — Alex still owns payments

part_b/   (mid-May 2026 — ownership handover)
  email/
    e04_handover.md          Alex Nova hands payments to Blake Shore (15 May)
    e05_blake_confirms.md    Blake confirms ownership
  notes/
    n03_status_update.md     New ownership table + completed items
```

## Ownership chain (payments service)

| Period              | Owner      | Evidence doc        |
|---------------------|------------|---------------------|
| 3 Apr – 14 May 2026 | Alex Nova  | demo0001, demo0002  |
| 15 May 2026 →       | Blake Shore| demo0007, demo0008  |

## Question types this dataset exercises

| Question | Expected answer |
|---|---|
| Who owns the payments service? | Blake Shore |
| Who owned the payments service on 3 May 2026? | Alex Nova |
| Who owned the payments service on 20 May 2026? | Blake Shore |
| Who handed off the payments service? | Alex Nova (to Blake Shore) |
| What is the payments migration deadline? | 30 June 2026 |
| What did Casey West ship on 20 May 2026? | Shared session store |
| What does Blake Shore own? | payments service, data-pipeline service |

## How to ingest

```bash
python -m chronicle.ingest --corpus data/demo/part_a --state data/demo/state --part a
python -m chronicle.ingest --corpus data/demo/part_b --state data/demo/state --part b
```

The state directory will contain `claims.jsonl` which P2 ingests into the bi-temporal store.
