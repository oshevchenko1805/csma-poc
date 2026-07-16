# Experiment results — comparison tables

Legend: mean±std (k) with k = sample size; single sample shows mean only.  — = no runs;  n/a = not applicable (architecture does not attempt recovery by design);  n/d = runs exist but attack never detected;  fail (0/k) = recovery attempted in all k applicable runs, none succeeded.

### MTTD, s (mean±std)

| Attack | A | B | C |
| --- | --- | --- | --- |
| GPS spoofing | — | — | — |
| Comm disruption | — | — | — |
| Command injection | — | — | — |
| GPS spoofing + local detector takeout | n/d | n/d | 8.101±0.233 (10) |

### MTTR, s (mean±std)

| Attack | A | B | C |
| --- | --- | --- | --- |
| GPS spoofing | — | — | — |
| Comm disruption | — | — | — |
| Command injection | — | — | — |
| GPS spoofing + local detector takeout | n/a | n/a | 0.019±0.006 (10) |

### Impact scope (mean±std)

| Attack | A | B | C |
| --- | --- | --- | --- |
| GPS spoofing | — | — | — |
| Comm disruption | — | — | — |
| Command injection | — | — | — |
| GPS spoofing + local detector takeout | 0.00±0.00 (10) | 0.00±0.00 (10) | 1.20±0.63 (10) |

### Detection rate

| Attack | A | B | C |
| --- | --- | --- | --- |
| GPS spoofing | — | — | — |
| Comm disruption | — | — | — |
| Command injection | — | — | — |
| GPS spoofing + local detector takeout | 0/10 (0%) | 0/10 (0%) | 10/10 (100%) |

### False-positive rate (baseline runs)

| Architecture | False-positive rate (baseline) |
| --- | --- |
| A | — |
| B | — |
| C | — |
