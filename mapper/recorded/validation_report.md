# Agentic mapping - validation report

Proposal by `claude-haiku-4-5-20251001/claude-opus-5[1m]` via `claude-cli` on 2026-08-30T19:24:44+00:00 (1 attempt(s)).

| Gate | Result | Detail |
|---|---|---|
| S1-S4 structural: shape, coverage, whitelist, canonical maps | PASS | ok |
| S5 proposed source columns exist in header | PASS | header: ['REG_NO', 'ITEM_SKU', 'BUYER_EMAIL', 'PURCHASED_ON', 'SALES_CH', 'COVER_YRS', 'ZONE'] |
| E1 every row splits into the header's column count | PASS | 0 of 1100 rows malformed |
| E2 row count preserved | PASS | 1100 of 1100 |
| E3 reg_id present and unique | PASS | 1100 distinct of 1100 |
| E4 dates parse (>=99%) and fall in the business window | PASS | parsed 1100/1100, in-window 1100/1100 |
| E5 customer join coverage >= 95% (email -> CRM) | PASS | 1071/1100 = 97.4% (29 unmatched, incl. any injection canary) |
| E6 product join coverage >= 97% (sku -> catalog) | PASS | 1100/1100 = 100.0% |
| E7 channels 100% canonical | PASS | all canonical |
| E8 regions 100% canonical and >=95% agree with CRM | PASS | all canonical; 1071/1071 = 100.0% agree with the joined customer's CRM region |
| E9 warranty_years all integers in 1..5 | PASS | distinct values: [1, 2, 3, 5] |

**Verdict: ACCEPTED** - conformed table written.
