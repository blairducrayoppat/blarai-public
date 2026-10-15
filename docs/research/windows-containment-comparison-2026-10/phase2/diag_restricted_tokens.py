import sys

sys.path.insert(0, 'C:/Users/__USER__/BlarAI-worktrees/phase2-arms/tools/probes/containment_arms')
import effective_access as ea
import run_arm
import winsec as w

elevated = w.process_token()
logon = w.logon_sid(elevated)
syn = ea.synthetic_sid('blarai-1740-write')
USERS, AU, RESTRICTED, EVERYONE = ea.USERS, ea.AUTH_USERS, ea.RESTRICTED, ea.EVERYONE
INTERACTIVE = 'S-1-5-4'
CMD = '"C:/Windows/System32/cmd.exe" /c exit 0'
PY = '"C:/blarai-spike-1740/toolchain/Python314/python.exe" -I -c pass'


def trial(name, flags, lst, il=True, maxpriv=True):
    try:
        if il:
            tok = w.limited_restricted(elevated, flags=flags, restricting=lst)
        else:
            f = flags | (w.DISABLE_MAX_PRIVILEGE if maxpriv else 0)
            tok = w.restricted_token(elevated, flags=f, deny_only=[w.ADMINISTRATORS, w.LOCAL_ACCOUNT_AND_ADMIN], restricting=lst)
        out = []
        for c in (CMD, PY):
            r = run_arm.launch(tok, c, run_arm.WORKTREE, None, 30, [])
            out.append(hex(r['exit_code']))
        print(f'{name:<58} cmd={out[0]:<12} python={out[1]}', flush=True)
    except Exception as exc:
        print(f'{name:<58} ERROR {exc}', flush=True)


trial('no restricting SIDs (WRITE_RESTRICTED flag only)', w.WRITE_RESTRICTED, [])
trial('write-restricted [Everyone]', w.WRITE_RESTRICTED, [EVERYONE])
trial('write-restricted [logon]', w.WRITE_RESTRICTED, [logon])
trial('write-restricted [Everyone, logon]', w.WRITE_RESTRICTED, [EVERYONE, logon])
trial('write-restricted [syn, Everyone, logon] (B2)', w.WRITE_RESTRICTED, [syn, EVERYONE, logon])
trial('write-restricted [syn, Everyone, logon] no IL change', w.WRITE_RESTRICTED, [syn, EVERYONE, logon], il=False)
trial('write-restricted [syn, Everyone, logon] no IL, keep privs', w.WRITE_RESTRICTED, [syn, EVERYONE, logon], il=False, maxpriv=False)
trial('fully restricted [Everyone, Users, AU, logon, RESTRICTED, syn] (B3)', 0, [syn, EVERYONE, USERS, AU, logon, RESTRICTED])
trial('fully restricted [+ Interactive]', 0, [syn, EVERYONE, USERS, AU, logon, RESTRICTED, INTERACTIVE])
trial('write-restricted [syn, Everyone, logon, Users, AU, Interactive]', w.WRITE_RESTRICTED, [syn, EVERYONE, logon, USERS, AU, INTERACTIVE])
