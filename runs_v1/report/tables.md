# Experiment results — comparison tables

Legend: mean±std (k) with k = sample size; single sample shows mean only.  — = no runs;  n/a = not applicable (architecture does not attempt recovery by design);  n/d = runs exist but attack never detected;  fail (0/k) = recovery attempted in all k applicable runs, none succeeded.

### MTTD, s (mean±std)

| Attack | A | B | C |
| --- | --- | --- | --- |
| GPS spoofing | 2.942±0.241 (10) | 2.925±0.208 (10) | 2.858±0.217 (10) |
| Comm disruption | 3.204±0.308 (10) | 3.045±0.451 (10) | 3.020±0.349 (10) |
| Command injection | 0.016±0.008 (10) | 0.011±0.006 (10) | 0.009±0.003 (10) |

### MTTR, s (mean±std)

| Attack | A | B | C |
| --- | --- | --- | --- |
| GPS spoofing | n/a | n/a | 0.017±0.003 (10) |
| Comm disruption | n/a | n/a | 8.062±0.004 (10) |
| Command injection | n/a | n/a | 0.001±0.000 (10) |

### Impact scope (mean±std)

| Attack | A | B | C |
| --- | --- | --- | --- |
| GPS spoofing | 1.00±0.00 (10) | 1.00±0.00 (10) | 1.00±0.00 (10) |
| Comm disruption | 1.00±0.00 (10) | 1.00±0.00 (10) | 1.00±0.00 (10) |
| Command injection | 1.00±0.00 (10) | 1.00±0.00 (10) | 1.00±0.00 (10) |

### Detection rate

| Attack | A | B | C |
| --- | --- | --- | --- |
| GPS spoofing | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) |
| Comm disruption | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) |
| Command injection | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) |

### False-positive rate (baseline runs)

| Architecture | False-positive rate (baseline) |
| --- | --- |
| A | 1/10 (10%) |
| B | 1/10 (10%) |
| C | 0/10 (0%) |
