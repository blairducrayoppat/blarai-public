import sys

sys.path.insert(0, 'C:/Users/__USER__/BlarAI-worktrees/phase2-arms/tools/probes/containment_arms')
import effective_access as ea
import run_arm
import winsec as w

elevated = w.process_token()
logon = w.logon_sid(elevated)
syn = ea.synthetic_sid('blarai-1740-write')
USERS, AU, RESTRICTED, EVERYONE = ea.USERS, ea.AUTH_USERS, ea.RESTRICTED, ea.EVERYONE
INTERACTIVE, LOCAL, BATCH, NETWORK = 'S-1-5-4', 'S-1-2-0', 'S-1-5-3', 'S-1-5-2'
BASH = '"C:/blarai-spike-1740/toolchain/Git/bin/bash.exe" -c "echo bash-ok"'
GIT = '"C:/blarai-spike-1740/toolchain/Git/cmd/git.exe" --version'


def trial(name, flags, lst, maxpriv=True):
    tok = w.limited_restricted(elevated, flags=flags, restricting=lst)
    out = []
    for c in (BASH, GIT):
        r = run_arm.launch(tok, c, run_arm.WORKTREE, None, 30, [])
        out.append(hex(r['exit_code']))
    print(f'{name:<66} bash={out[0]:<12} git={out[1]}', flush=True)


b2 = [syn, EVERYONE, logon]
trial('B2 list (syn, Everyone, logon)', w.WRITE_RESTRICTED, b2)
trial('B2 + Interactive', w.WRITE_RESTRICTED, b2 + [INTERACTIVE])
trial('B2 + Interactive + Users + AuthUsers', w.WRITE_RESTRICTED, b2 + [INTERACTIVE, USERS, AU])
trial('B2 + Local + Interactive + Users + AuthUsers + Batch', w.WRITE_RESTRICTED, b2 + [LOCAL, INTERACTIVE, USERS, AU, BATCH])
trial('B3 list (broad)', 0, [syn, EVERYONE, USERS, AU, logon, RESTRICTED])
trial('B3 + Interactive + Local', 0, [syn, EVERYONE, USERS, AU, logon, RESTRICTED, INTERACTIVE, LOCAL])
trial('operator user SID only in list (write-restricted)', w.WRITE_RESTRICTED, [w.describe_token(elevated)['user'], logon, EVERYONE])
