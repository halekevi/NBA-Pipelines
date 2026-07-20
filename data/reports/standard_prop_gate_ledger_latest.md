# Standard prop-type gate ledger

Window: 2026-07-10, 2026-07-11, 2026-07-12, 2026-07-13, 2026-07-14, 2026-07-15, 2026-07-17, 2026-07-18, 2026-07-19 (9 days)

Gate key = **sport + prop_type + direction** (single and combo listed separately).

| gate | rule |
|---|---|
| **ban** | HR < 40% with n ≥ 8 |
| **hard_gate** | HR < 48% with n ≥ 8 |
| **soft_gate** | HR < 55% with n ≥ 8 |
| **keep** | HR ≥ 55% with n ≥ 8 |
| **thin** | n < 8 (watch / don’t overfit) |

## MLB

### Single props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| 1st Inning Runs Allowed | OVER | 0 | 0 | 18 | 0 | — | **thin** |
| 1st Inning Walks Allowed | OVER | 0 | 0 | 14 | 0 | — | **thin** |
| Earned Runs Allowed | OVER | 0 | 14 | 0 | 14 | 0.0 | **ban** |
| Earned Runs Allowed | UNDER | 29 | 29 | 5 | 58 | 50.0 | **soft_gate** |
| Hits | OVER | 0 | 15 | 5 | 15 | 0.0 | **ban** |
| Hits Allowed | OVER | 5 | 15 | 0 | 20 | 25.0 | **ban** |
| Hits Allowed | UNDER | 34 | 29 | 0 | 63 | 54.0 | **soft_gate** |
| Pitcher Strikeouts | OVER | 39 | 49 | 14 | 88 | 44.3 | **hard_gate** |
| Pitches Thrown | OVER | 24 | 35 | 0 | 59 | 40.7 | **hard_gate** |
| Pitching Outs | OVER | 23 | 23 | 0 | 46 | 50.0 | **soft_gate** |
| Plate Appearances | UNDER | 10 | 44 | 5 | 54 | 18.5 | **ban** |
| RBIs | UNDER | 5 | 5 | 0 | 10 | 50.0 | **soft_gate** |
| Runs | OVER | 25 | 25 | 0 | 50 | 50.0 | **soft_gate** |
| Runs | UNDER | 25 | 13 | 0 | 38 | 65.8 | **keep** |
| Singles | OVER | 25 | 20 | 0 | 45 | 55.6 | **keep** |
| Singles | UNDER | 5 | 0 | 0 | 5 | 100.0 | **thin** |
| Total Bases | OVER | 53 | 95 | 10 | 148 | 35.8 | **ban** |
| Walks | OVER | 4 | 0 | 0 | 4 | 100.0 | **thin** |
| Walks Allowed | OVER | 10 | 10 | 0 | 20 | 50.0 | **soft_gate** |
| Walks Allowed | UNDER | 15 | 16 | 0 | 31 | 48.4 | **soft_gate** |

### Combo props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Hits+Runs+RBIs | OVER | 104 | 119 | 10 | 223 | 46.6 | **hard_gate** |

#### Suggested actions
- **ban:** Earned Runs Allowed OVER 0.0% (0/14); Hits OVER 0.0% (0/15); Hits Allowed OVER 25.0% (5/20); Plate Appearances UNDER 18.5% (10/54); Total Bases OVER 35.8% (53/148)
- **hard_gate:** Hits+Runs+RBIs OVER 46.6% (104/223); Pitcher Strikeouts OVER 44.3% (39/88); Pitches Thrown OVER 40.7% (24/59)
- **keep:** Runs UNDER 65.8% (25/38); Singles OVER 55.6% (25/45)

## SOCCER

### Single props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Goalie Saves | OVER | 0 | 2 | 0 | 2 | 0.0 | **thin** |
| Goalie Saves | UNDER | 6 | 0 | 0 | 6 | 100.0 | **thin** |
| Shots | OVER | 4 | 6 | 2 | 10 | 40.0 | **hard_gate** |
| Shots | UNDER | 6 | 6 | 2 | 12 | 50.0 | **soft_gate** |
| Shots On Target | OVER | 0 | 2 | 0 | 2 | 0.0 | **thin** |

### Combo props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Goalie Saves (Combo) | OVER | 0 | 2 | 0 | 2 | 0.0 | **thin** |
| Goalie Saves (Combo) | UNDER | 2 | 0 | 0 | 2 | 100.0 | **thin** |
| Shots (Combo) | OVER | 0 | 8 | 0 | 8 | 0.0 | **ban** |
| Shots (Combo) | UNDER | 2 | 0 | 0 | 2 | 100.0 | **thin** |
| Shots On Target (Combo) | OVER | 0 | 2 | 0 | 2 | 0.0 | **thin** |
| Shots On Target (Combo) | UNDER | 2 | 0 | 0 | 2 | 100.0 | **thin** |

#### Suggested actions
- **ban:** Shots (Combo) OVER 0.0% (0/8)
- **hard_gate:** Shots OVER 40.0% (4/10)

## WNBA

### Single props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| 3-PT Attempted | UNDER | 4 | 0 | 0 | 4 | 100.0 | **thin** |
| 3-PT Made | OVER | 1 | 0 | 0 | 1 | 100.0 | **thin** |
| 3-PT Made | UNDER | 0 | 5 | 0 | 5 | 0.0 | **thin** |
| Assists | UNDER | 4 | 5 | 0 | 9 | 44.4 | **hard_gate** |
| Blocked Shots | OVER | 5 | 0 | 0 | 5 | 100.0 | **thin** |
| Blocked Shots | UNDER | 0 | 5 | 0 | 5 | 0.0 | **thin** |
| Defensive Rebounds | UNDER | 26 | 10 | 0 | 36 | 72.2 | **keep** |
| FG Attempted | OVER | 2 | 0 | 0 | 2 | 100.0 | **thin** |
| FG Attempted | UNDER | 3 | 5 | 0 | 8 | 37.5 | **ban** |
| Free Throws Attempted | OVER | 0 | 4 | 0 | 4 | 0.0 | **thin** |
| Free Throws Attempted | UNDER | 0 | 0 | 2 | 0 | — | **thin** |
| Free Throws Made | OVER | 0 | 7 | 0 | 7 | 0.0 | **thin** |
| Free Throws Made | UNDER | 3 | 0 | 0 | 3 | 100.0 | **thin** |
| Offensive Rebounds | UNDER | 4 | 0 | 0 | 4 | 100.0 | **thin** |
| Points | OVER | 17 | 18 | 0 | 35 | 48.6 | **soft_gate** |
| Points | UNDER | 19 | 14 | 5 | 33 | 57.6 | **keep** |
| Rebounds | OVER | 6 | 13 | 0 | 19 | 31.6 | **ban** |
| Rebounds | UNDER | 10 | 9 | 5 | 19 | 52.6 | **soft_gate** |
| Two Pointers Attempted | OVER | 0 | 4 | 0 | 4 | 0.0 | **thin** |
| Two Pointers Attempted | UNDER | 6 | 4 | 0 | 10 | 60.0 | **keep** |
| Two Pointers Made | OVER | 4 | 0 | 0 | 4 | 100.0 | **thin** |
| Two Pointers Made | UNDER | 13 | 0 | 5 | 13 | 100.0 | **keep** |

### Combo props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| 3-PT Made (Combo) | OVER | 3 | 0 | 0 | 3 | 100.0 | **thin** |
| 3-PT Made (Combo) | UNDER | 0 | 5 | 0 | 5 | 0.0 | **thin** |
| Assists (Combo) | UNDER | 9 | 4 | 0 | 13 | 69.2 | **keep** |
| Points (Combo) | OVER | 23 | 19 | 0 | 42 | 54.8 | **soft_gate** |
| Points (Combo) | UNDER | 2 | 0 | 0 | 2 | 100.0 | **thin** |
| Pts+Asts | OVER | 11 | 16 | 0 | 27 | 40.7 | **hard_gate** |
| Pts+Asts | UNDER | 12 | 9 | 0 | 21 | 57.1 | **keep** |
| Pts+Rebs | OVER | 25 | 29 | 5 | 54 | 46.3 | **hard_gate** |
| Pts+Rebs | UNDER | 24 | 19 | 0 | 43 | 55.8 | **keep** |
| Pts+Rebs+Asts | OVER | 18 | 33 | 0 | 51 | 35.3 | **ban** |
| Pts+Rebs+Asts | UNDER | 24 | 3 | 0 | 27 | 88.9 | **keep** |
| Rebs+Asts | OVER | 24 | 8 | 0 | 32 | 75.0 | **keep** |
| Rebs+Asts | UNDER | 8 | 5 | 0 | 13 | 61.5 | **keep** |

#### Suggested actions
- **ban:** Pts+Rebs+Asts OVER 35.3% (18/51); FG Attempted UNDER 37.5% (3/8); Rebounds OVER 31.6% (6/19)
- **hard_gate:** Pts+Asts OVER 40.7% (11/27); Pts+Rebs OVER 46.3% (25/54); Assists UNDER 44.4% (4/9)
- **keep:** Assists (Combo) UNDER 69.2% (9/13); Pts+Asts UNDER 57.1% (12/21); Pts+Rebs UNDER 55.8% (24/43); Pts+Rebs+Asts UNDER 88.9% (24/27); Rebs+Asts OVER 75.0% (24/32); Rebs+Asts UNDER 61.5% (8/13); Defensive Rebounds UNDER 72.2% (26/36); Points UNDER 57.6% (19/33); Two Pointers Attempted UNDER 60.0% (6/10); Two Pointers Made UNDER 100.0% (13/13)
