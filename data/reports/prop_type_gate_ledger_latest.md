# Prop-type gate ledger (single + combo per sport)

Window: 2026-07-10, 2026-07-11, 2026-07-12, 2026-07-13, 2026-07-14, 2026-07-15, 2026-07-17, 2026-07-18, 2026-07-19

Gate key = **sport + pick_type + prop_type + direction** (single and combo both listed).

| gate | rule |
|---|---|
| ban | HR < 40%, n ≥ 8 |
| hard_gate | HR < 48%, n ≥ 8 |
| soft_gate | HR < 55%, n ≥ 8 |
| keep | HR ≥ 55%, n ≥ 8 |
| thin | n < 8 |

## MLB

### Standard

#### Single props

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

#### Combo props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Hits+Runs+RBIs | OVER | 104 | 119 | 10 | 223 | 46.6 | **hard_gate** |

### Goblin

#### Single props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| 1st Inning Walks Allowed | OVER | 0 | 0 | 5 | 0 | — | **thin** |
| Earned Runs Allowed | OVER | 253 | 113 | 14 | 366 | 69.1 | **keep** |
| Hits | OVER | 1241 | 724 | 77 | 1965 | 63.2 | **keep** |
| Hits Allowed | OVER | 305 | 127 | 15 | 432 | 70.6 | **keep** |
| Hitter Strikeouts | OVER | 943 | 425 | 24 | 1368 | 68.9 | **keep** |
| Pitcher Strikeouts | OVER | 326 | 51 | 16 | 377 | 86.5 | **keep** |
| Pitches Thrown | OVER | 73 | 30 | 0 | 103 | 70.9 | **keep** |
| Pitching Outs | OVER | 181 | 57 | 0 | 238 | 76.1 | **keep** |
| Plate Appearances | OVER | 4 | 5 | 0 | 9 | 44.4 | **hard_gate** |
| Runs | OVER | 19 | 28 | 0 | 47 | 40.4 | **hard_gate** |
| Singles | OVER | 33 | 40 | 0 | 73 | 45.2 | **hard_gate** |
| Total Bases | OVER | 1251 | 738 | 77 | 1989 | 62.9 | **keep** |
| Walks | OVER | 5 | 10 | 0 | 15 | 33.3 | **ban** |
| Walks Allowed | OVER | 234 | 61 | 5 | 295 | 79.3 | **keep** |

#### Combo props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Hits+Runs+RBIs | OVER | 1758 | 960 | 69 | 2718 | 64.7 | **keep** |


## SOCCER

### Standard

#### Single props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Goalie Saves | OVER | 0 | 2 | 0 | 2 | 0.0 | **thin** |
| Goalie Saves | UNDER | 6 | 0 | 0 | 6 | 100.0 | **thin** |
| Shots | OVER | 4 | 6 | 2 | 10 | 40.0 | **hard_gate** |
| Shots | UNDER | 6 | 6 | 2 | 12 | 50.0 | **soft_gate** |
| Shots On Target | OVER | 0 | 2 | 0 | 2 | 0.0 | **thin** |

#### Combo props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Goalie Saves (Combo) | OVER | 0 | 2 | 0 | 2 | 0.0 | **thin** |
| Goalie Saves (Combo) | UNDER | 2 | 0 | 0 | 2 | 100.0 | **thin** |
| Shots (Combo) | OVER | 0 | 8 | 0 | 8 | 0.0 | **ban** |
| Shots (Combo) | UNDER | 2 | 0 | 0 | 2 | 100.0 | **thin** |
| Shots On Target (Combo) | OVER | 0 | 2 | 0 | 2 | 0.0 | **thin** |
| Shots On Target (Combo) | UNDER | 2 | 0 | 0 | 2 | 100.0 | **thin** |

### Goblin

#### Single props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Goalie Saves | OVER | 6 | 4 | 0 | 10 | 60.0 | **keep** |
| Shots | OVER | 14 | 0 | 0 | 14 | 100.0 | **keep** |


## TENNIS

### Goblin

#### Single props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Total Games | OVER | 1 | 0 | 0 | 1 | 100.0 | **thin** |
| Total Games Won | OVER | 1 | 1 | 0 | 2 | 50.0 | **thin** |


## WNBA

### Standard

#### Single props

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

#### Combo props

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

### Goblin

#### Single props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| 3-PT Attempted | OVER | 11 | 9 | 0 | 20 | 55.0 | **keep** |
| 3-PT Made | OVER | 92 | 19 | 0 | 111 | 82.9 | **keep** |
| Assists | OVER | 191 | 39 | 0 | 230 | 83.0 | **keep** |
| Blocked Shots | OVER | 4 | 0 | 0 | 4 | 100.0 | **thin** |
| Free Throws Attempted | OVER | 4 | 0 | 0 | 4 | 100.0 | **thin** |
| Free Throws Made | OVER | 3 | 0 | 0 | 3 | 100.0 | **thin** |
| Points | OVER | 20 | 1 | 0 | 21 | 95.2 | **keep** |
| Rebounds | OVER | 139 | 31 | 0 | 170 | 81.8 | **keep** |
| Turnovers | OVER | 7 | 11 | 0 | 18 | 38.9 | **ban** |

#### Combo props

| Prop | Dir | Hit | Miss | Void | n | HR% | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| Pts+Asts | OVER | 5 | 4 | 0 | 9 | 55.6 | **keep** |
| Pts+Rebs | OVER | 12 | 4 | 0 | 16 | 75.0 | **keep** |
| Pts+Rebs+Asts | OVER | 14 | 19 | 0 | 33 | 42.4 | **hard_gate** |
| Rebs+Asts | OVER | 32 | 5 | 0 | 37 | 86.5 | **keep** |

