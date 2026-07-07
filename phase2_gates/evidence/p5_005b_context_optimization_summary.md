# P5-005b Context Window + Optimization Characterization Summary

## Outcome

- Finished UTC: `2026-02-28T10:00:52.220355+00:00`
- Disposition: `CONTEXT_EXPANSION_FEASIBLE`
- Total tests: `8`
- Completed: `8`

## TPS Degradation Table

| Test | 512 | 2048 | 4096 | 6144 | 8192 | 12288 | 16384 | 20480 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A-01 14B Baseline Extended | — | — | 9.1 tps / 275ms / 9277MB | 7.2 tps / 327ms / 9374MB | 6.3 tps / 410ms / 9579MB | 5.4 tps / 440ms / 2932MB | 4.8 tps / 487ms / 2610MB | 4.4 tps / 619ms / 2991MB |
| A-02 14B + 0.6B Draft Extended | — | — | 10.0 tps / 460ms / 9855MB | 8.2 tps / 503ms / 10193MB | 6.7 tps / 672ms / 10531MB | 6.4 tps / 751ms / 10769MB | 6.0 tps / 853ms / 8551MB | 4.4 tps / 1096ms / 6196MB |
| B-01 14B + XAttention Only | 7.6 tps / 272ms / 8806MB | 7.2 tps / 302ms / 9018MB | 6.7 tps / 336ms / 9221MB | — | 6.0 tps / 362ms / 9631MB | — | — | — |
| B-02 14B + 0.6B Draft + XAttention | 13.7 tps / 366ms / 9495MB | 11.7 tps / 405ms / 9720MB | 9.7 tps / 463ms / 10051MB | — | 7.5 tps / 756ms / 10705MB | — | — | — |
| C-01 14B + 0.6B Draft (NAT=3) | 12.9 tps / 361ms / 9397MB | — | 10.7 tps / 428ms / 10035MB | — | 8.2 tps / 683ms / 10716MB | — | — | — |
| C-02 14B + 0.6B Draft (NAT=7) | 14.3 tps / 421ms / 9584MB | — | 10.7 tps / 607ms / 10055MB | — | 6.8 tps / 663ms / 10733MB | — | — | — |
| C-03 14B + 0.6B Draft (NAT=10) | 16.1 tps / 459ms / 9737MB | — | 8.2 tps / 556ms / 10050MB | — | 7.3 tps / 786ms / 10700MB | — | — | — |
| D-01 Best Config Extended | — | — | 11.2 tps / 408ms / 9907MB | — | 7.7 tps / 717ms / 10605MB | 6.0 tps / 839ms / 11244MB | 4.9 tps / 973ms / 11877MB | 4.2 tps / 1152ms / 12517MB |

## OOM Boundary Identification

- No OOM boundary reached — all bands through 20480 passed.

## Group D Selection Rationale

- Rationale: XAttention=OFF (B-02=9.74 vs A-02=10.02 tps @4096); NAT=3 selected (best 10.72 tps @4096 from NAT=3=10.72, NAT=5=10.02, NAT=7=10.65, NAT=10=8.22)
- XAttention: `False`
- num_assistant_tokens: `3`

## Best Configuration

- XAttention: `False`
- num_assistant_tokens: `3`
- Max safe context band: `20480`

## Memory Growth Curve (RSS peak MB)

### A-02: 14B + 0.6B Draft Extended

| Band | RSS Peak (MB) | Status |
| --- | --- | --- |
| 4096 | 9855 | ok |
| 6144 | 10193 | ok |
| 8192 | 10531 | ok |
| 12288 | 10769 | ok |
| 16384 | 8551 | ok |
| 20480 | 6196 | ok |

### D-01: Best Config Extended

| Band | RSS Peak (MB) | Status |
| --- | --- | --- |
| 4096 | 9907 | ok |
| 8192 | 10605 | ok |
| 12288 | 11244 | ok |
| 16384 | 11877 | ok |
| 20480 | 12517 | ok |

## Quality Gate Pass/Fail Matrix

| Gate | Pass/Fail | Detail |
| --- | --- | --- |
| G-01 | PASS | A-02 has 5 valid bands above 4096 (need >=3) |
| G-02 | PASS | D-01 has 5 valid bands (need >=3) |
| G-03 | PASS | All bands through 20480 passed — ceiling not reached |
| G-04 | PASS | Peak RSS 12517 MB at highest band (<= 15507 MB budget) |
| G-05 | PASS | Best config TPS at 8192 = 7.74 (need >=5.0) |

