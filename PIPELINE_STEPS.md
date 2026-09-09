# PFMEA AI-Assist — Build Traceability

Each step is one small, independently-testable Python block. We build and
test one at a time, in order — no step starts until the one before it works
on a real file.

| # | Step | Script | Status |
|---|------|--------|--------|
| 1 | Read the uploaded plant Excel and report its structure (sheets, columns, row count, sample rows) — nothing else | `step1_read_excel.py` | DONE |
| 2 | Let the user map their own column names to our standard PFMEA fields (Process Step, Failure Mode, Effect, Severity, Cause, Occurrence, Current Control, Detection) | `step2_column_mapping.py` | TODO |
| 3 | Normalize the mapped sheet into one clean internal table (one row per failure mode), regardless of the plant's original layout | `step3_normalize.py` | TODO |
| 4 | Compute RPN + Risk Level from existing Severity/Occurrence/Detection (pure math, no AI) | `step4_rpn.py` | TODO |
| 5 | Embed the AIAG-VDA handbook PDF into a local vector store (RAG source) | `step5_embed_handbook.py` | TODO |
| 6 | For each process step, retrieve relevant handbook chunks + call the LLM to draft Failure Mode/Effect/Cause/S/D/Prevention | `step6_generate.py` | TODO |
| 7 | Compare the AI draft against the plant's real recorded value, produce agree/disagree + reason | `step7_compare.py` | TODO |
| 8 | Write the final output Excel: plant's original columns untouched on the left, AI Suggestion columns added on the right | `step8_write_output.py` | TODO |

## Why this order

Steps 1–4 need no API key and no AI at all — they're pure file-handling and
arithmetic, so we can prove the plumbing works on a real plant sheet before
any LLM cost or RAG complexity enters the picture. Step 5 onward is where
AIAG-VDA/RAG and the LLM get involved, per `pfmea_outputs/PFMEA_Pipeline_Overview.txt`
from the `claude/fmea-car-manufacturing-4pthaq` branch.

## Step 1 — what it does

`step1_read_excel.py <path-to-excel>` opens the file, and for every sheet
prints: sheet name, dimensions, column headers (row 1), and the first 3
data rows. No interpretation, no mapping, no writing — just proof we can
reliably read whatever format the plant hands us. Run it on the sample
Excel before writing any more code.
