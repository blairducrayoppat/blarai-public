# Case 4 run sheet: what the Lead Architect types, in order

Every line below is typed by you, exactly as written. The session prepares the machine (steps 0 and 1), you run the probe (steps 2 to 5), the
session collects and cleans up (steps 6 and 7), you remove the account (step 8, your own sheet, part C), the session checks (step 9).
Expect the whole thing to take about twenty minutes of your time. Any password prompt is yours to type; never paste a password anywhere else.

Paths used throughout:

| Name | Path |
|---|---|
| probe program | `C:\ProgramData\BlarAI\case4-pub\bin\ncoprobe.exe` |
| probe proof (written by the session at step 1) | `C:\ProgramData\BlarAI\case4-pub\bin\nco-probe-live.json` |
| drop folder (where each run writes its record) | `C:\ProgramData\BlarAI\case4-pub\drop` |

## 0. Session: the standard-token control (blarai-spike), before anything of yours

Run by the session in its elevated console from the live folder, under the password-reset design you approved on 2026-10-13. Nothing for you to type.
The session records the sha256 of the live matrix bytes in the prepare record (they differ from the repository copy).

```
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-matrix.ps1 -SelfTest -WriteProof
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-matrix.ps1 -DryRun
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-matrix.ps1 -Run -Phase taskcheck
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-matrix.ps1 -Run -Phase n1
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-matrix.ps1 -Check
```

## 1. Session: prepare

```
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-c4-driver.ps1 -SelfTest -WriteProof
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-c4-driver.ps1 -DryRun
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-c4-driver.ps1 -Prepare
```

After `-Prepare` the test sublayer S2 and its provider exist (nothing else), the public folder exists, and the session tells you to go on.

## 2. You: enable the account (your sheet, the clause under part A)

Computer Management > Local Users and Groups > Users > right-click `nco-probe` > Properties > untick **Account is disabled** > OK.

## 3. You: condition F (filtered token), three times

Open your normal console (Windows key + R, type `cmd`, Enter: NOT "Run as administrator"). First move it out of your profile folder, which
`nco-probe` cannot read (a console started there would fail for the other account):

```
cd /d C:\ProgramData\BlarAI\case4-pub
```

Then type this line; it asks for the `nco-probe` password; a new black window opens, runs the probe, prints its record and waits for a key. Read the
last lines, press a key, close it. Repeat three times.

```
runas /user:nco-probe "cmd /k C:\ProgramData\BlarAI\case4-pub\bin\ncoprobe.exe run --cond F --live C:\ProgramData\BlarAI\case4-pub\bin\nco-probe-live.json --out C:\ProgramData\BlarAI\case4-pub\drop --wait"
```

The first launch creates a profile folder for `nco-probe`; that is expected and your sheet's part C.3 removes it.

## 4. You: condition E (elevated token), three times, TWO steps each time

Step one, in your normal console (still in `C:\ProgramData\BlarAI\case4-pub` after the `cd` above): open a console that runs AS `nco-probe` (it asks
for the `nco-probe` password):

```
runas /user:nco-probe cmd
```

Step two, INSIDE that new `nco-probe` window (its title says nco-probe), paste this one line. It asks Windows to elevate; the prompt that appears is
for the `nco-probe` account. If the prompt asks for a user name and password, type `nco-probe` and its password. If Windows refuses to elevate, or the
prompt only offers your own account, cancel it: that refusal is the result and the session records it. Do NOT type your own password here.

```
powershell -NoProfile -Command "Start-Process cmd -Verb RunAs -ArgumentList '/k C:\ProgramData\BlarAI\case4-pub\bin\ncoprobe.exe run --cond E --live C:\ProgramData\BlarAI\case4-pub\bin\nco-probe-live.json --out C:\ProgramData\BlarAI\case4-pub\drop --wait'"
```

Read the last lines of the window that opens, press a key, close both windows. Repeat three times (step one then step two each time).

Why two steps: an elevation requested from your own console elevates YOU, and the probe's record would then name your account; the session marks such a
run invalid and it is not counted.

## 5. You: controls S and A, three times each

S (your own account, normal console, not elevated): open `cmd` normally and type, three times:

```
C:\ProgramData\BlarAI\case4-pub\bin\ncoprobe.exe run --cond S --live C:\ProgramData\BlarAI\case4-pub\bin\nco-probe-live.json --out C:\ProgramData\BlarAI\case4-pub\drop
```

A (your own account, elevated): open `cmd` with "Run as administrator" (approve the prompt) and type, three times:

```
C:\ProgramData\BlarAI\case4-pub\bin\ncoprobe.exe run --cond A --live C:\ProgramData\BlarAI\case4-pub\bin\nco-probe-live.json --out C:\ProgramData\BlarAI\case4-pub\drop
```

Tell the session when all twelve runs are done (3 F, 3 E, 3 S, 3 A).

## 6. Session: collect

```
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-c4-driver.ps1 -Collect
```

## 7. Session: finish (remove S2, the provider, any filter the probe left, and the public folder; verify by direct reads)

```
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-c4-driver.ps1 -Finish
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-matrix.ps1 -Check
```

## 8. You: part C of your sheet

Remove `nco-probe` from Network Configuration Operators, delete the account, delete its profile entry. Tell the session when done.

## 9. Session: part D checks (read-only)

```
pwsh -NoProfile -File C:\ProgramData\BlarAI\trackb-live\spike-nep5-c4-driver.ps1 -PartD
```

## Stop lines

If any probe window ends with a line that starts with `STOP:` (the probe could not confirm it removed the filter it added, or the run was launched
as the wrong account), stop there and tell the session before launching another run.

## If anything looks wrong

Stop and tell the session what you see. Do not delete anything by hand. The session's `-Finish` and the matrix's `-Remove` are the removers; the
manual rollback snippet is printed by `-DryRun` for the case where neither can run.
