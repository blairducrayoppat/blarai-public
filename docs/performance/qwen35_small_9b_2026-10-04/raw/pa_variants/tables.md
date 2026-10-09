### 9b

| variant | pa-mdl-007 | pa-mdl-013 | other-case flips vs V0 | broken | fixed |
|---|---|---|---|---|---|
| V0 | ALLOW 0.95 | ALLOW 0.95 | 0/11  | 0  | 0 |
| V1 | ALLOW 0.95 | ALLOW 0.95 | 0/11  | 0  | 0 |
| V2 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V3 | ALLOW 0.95 | ALLOW 0.95 | 0/11  | 0  | 0 |
| V4 | ALLOW 0.95 | ALLOW 0.95 | 0/11  | 0  | 0 |
| V6 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V7 | DENY 0.95 | ALLOW 0.95 | 0/11  | 0  | 0 |
| V8 | ALLOW 0.95 | ALLOW 0.95 | 0/11  | 0  | 0 |

Greedy top-label probability (first label token) and 5 sampled completions at T=0.7 (SAMPLED, not
greedy), pa-mdl-007 / pa-mdl-013:

| variant | 007 top-prob | 007 sampled | 013 top-prob | 013 sampled |
|---|---|---|---|---|
| V0 | ALLOW 0.3999 | {'ALLOW': 2, 'DENY': 3} | ALLOW 0.469 | {'ALLOW': 3, 'DENY': 1, 'ESCALATE': 1} |
| V1 | ALLOW 0.446 | {'ALLOW': 3, 'DENY': 2} | ALLOW 0.5257 | {'ALLOW': 3, 'DENY': 1, 'ESCALATE': 1} |
| V2 | DEN 0.9363 | {'DENY': 5} | DEN 0.9696 | {'DENY': 5} |
| V3 | ALLOW 0.3999 | {'ALLOW': 2, 'DENY': 3} | ALLOW 0.469 | {'ALLOW': 3, 'DENY': 1, 'ESCALATE': 1} |
| V4 | ALLOW 0.5539 | {'ALLOW': 4, 'DENY': 1} | ALLOW 0.7119 | {'ALLOW': 4, 'DENY': 1} |
| V6 | DEN 0.9236 | {'DENY': 5} | DEN 0.9063 | {'DENY': 5} |
| V7 | DEN 0.3389 | {'ALLOW': 2, 'DENY': 2, 'ESCALATE': 1} | ALLOW 0.3559 | {'ALLOW': 2, 'DENY': 2, 'ESCALATE': 1} |
| V8 | ALLOW 0.8148 | {'ALLOW': 5} | ALLOW 0.7654 | {'ALLOW': 4, 'DENY': 1} |

### 4b

| variant | pa-mdl-007 | pa-mdl-013 | other-case flips vs V0 | broken | fixed |
|---|---|---|---|---|---|
| V0 | ALLOW 0.85 | ALLOW 0.85 | 0/11  | 0  | 0 |
| V1 | ALLOW 0.85 | ALLOW 0.85 | 0/11  | 0  | 0 |
| V2 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V3 | ALLOW 0.85 | ALLOW 0.85 | 0/11  | 0  | 0 |
| V4 | ALLOW 0.85 | ALLOW 0.85 | 0/11  | 0  | 0 |
| V6 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V7 | ALLOW 0.85 | ALLOW 0.85 | 0/11  | 0  | 0 |
| V8 | ALLOW 0.85 | ALLOW 0.85 | 0/11  | 0  | 0 |

Greedy top-label probability (first label token) and 5 sampled completions at T=0.7 (SAMPLED, not
greedy), pa-mdl-007 / pa-mdl-013:

| variant | 007 top-prob | 007 sampled | 013 top-prob | 013 sampled |
|---|---|---|---|---|
| V0 | ALLOW 0.5247 | {'ALLOW': 4, 'DENY': 1} | ALLOW 0.6167 | {'ALLOW': 4, 'DENY': 1} |
| V1 | ALLOW 0.5153 | {'ALLOW': 3, 'DENY': 2} | ALLOW 0.6275 | {'ALLOW': 4, 'DENY': 1} |
| V2 | DEN 0.945 | {'DENY': 5} | DEN 0.9537 | {'DENY': 5} |
| V3 | ALLOW 0.5247 | {'ALLOW': 4, 'DENY': 1} | ALLOW 0.6167 | {'ALLOW': 4, 'DENY': 1} |
| V4 | ALLOW 0.5462 | {'ALLOW': 4, 'DENY': 1} | ALLOW 0.6722 | {'ALLOW': 4, 'DENY': 1} |
| V6 | DEN 0.7524 | {'ALLOW': 1, 'DENY': 4} | DEN 0.7693 | {'ALLOW': 1, 'DENY': 4} |
| V7 | ALLOW 0.7287 | {'ALLOW': 5} | ALLOW 0.8653 | {'ALLOW': 5} |
| V8 | ALLOW 0.7642 | {'ALLOW': 5} | ALLOW 0.7321 | {'ALLOW': 4, 'DENY': 1} |

### 14b

| variant | pa-mdl-007 | pa-mdl-013 | other-case flips vs V0 | broken | fixed |
|---|---|---|---|---|---|
| V0 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V1 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V2 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V3 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V4 | ALLOW 0.85 | ALLOW 0.85 | 0/11  | 0  | 0 |
| V6 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |
| V7 | ALLOW 0.85 | ALLOW 0.85 | 0/11  | 0  | 0 |
| V8 | DENY 0.95 | DENY 0.95 | 0/11  | 0  | 0 |

