### 2026-10-18 — A scrub that names the shapes it knows is blind to the one nobody listed

*Plain summary: the public-identifier scrub never knew the Microsoft-account SID shape, so the operator's account SID sat in 73 public research records; a disclosure-pack review caught it, and the fix's own test fixture then leaked four real sub-authorities until a second review caught that too.*

The Q1 MSRC pack review (round 5, #1793) found the operator's Microsoft-account SID, `S-1-11-96-...`, in the container
token group lists of 24 pack files. The scrub and its `--check` passed those files clean, because the identity lock only
knew machine SIDs (`S-1-5-21-...`), host names, the account name and user paths. When I grepped the repository the same
hour, the SID was in 73 tracked JSON records under `docs/research/windows-containment-comparison-2026-10/`, 334 times,
and in the same 73 files on the public mirror, which is public. The control had been reporting zero for a shape it had
no rule for. A clean `--check` meant "none of the shapes I list", and every report since had read it as "no identifiers".

The LA decided two things (#1793 c4432): publish the forward scrub at once, ahead of the embargo on everything else,
and leave the public history as it is rather than rewrite it. Removing it from history would have meant a force-push.
Recreating the repository would have lost its stars and links. The SID gives no access by itself; Microsoft can link it
to the account. He judged a forward fix enough.

The fix went through three adversarial reviews, and the first two failed for reasons worth keeping. In round 1 the new
test fixture carried four of the operator's real sub-authorities under a docstring saying "made up". The author had
copied them from the records. The lock could not see them, because the test built the `S-1-11-96` prefix at run time.
Merged and pushed, the fix would have published part of the identifier it existed to remove. The reviewer found it by
reading the live token and searching every tracked file for each sub-authority. That search is now a lock of its own.
It reads the account SIDs from the current token at test time, so no value is ever written into the tree.

In round 2 that new lock was too eager. It failed on any token without an account SID, which would have turned every
blarai-coder gate red. It also matched two 5-digit sub-authorities that collide with real process ids and ports. Its
failure message told the reader to "replace it with an invented number", which in a measurement record means altering
evidence. The landed form runs and fails closed when the token has an account SID, and skips visibly when it has none.
It matches only sub-authorities of 8 digits or more. Its message says to scrub an identifier, or to stop and report a
coincidental number, never to edit a record. I rejected pinning hashes of the long sub-authorities: a 10-digit space is
small enough to brute-force, so the hashes would have published the values in effect.

The four real sub-authorities stayed reachable in the audit branch's history. So the work landed as one squashed commit
on a fresh branch (`49db6013`, merged `--no-ff` as `7580d07c`). The audit branch `fix/scrub-account-sids` is kept and
never pushed, so the early fixture never reaches main or origin. The standing gate on merged main read 14669 / 0 / 0 /
621, as predicted. The land worktree read 14638 / 5 / 26 of the same 14669, every difference an environment delta of
the worktree.

The general point: a scrub that enumerates identifier shapes certifies only those shapes. Its zero is as wide as its
list, so a new identifier class needs a new rule, and every report should say which classes it checked. Two reviews
also caught the fix leaking the very thing it removed. A privacy fix gets the same adversarial review as a security
control, because it is one.

**Next:** the forward publish to the public mirror through `publish-public-snapshot.ps1` (dry run first). Add the
account-SID shape to the snapshot leak gate's private pattern file as an independent second lock. Re-scrub the
research-data folders the reviewer listed (mxc-denied-subtree, redirector-egress, mxc-proxy-egress) with the merged tool.
