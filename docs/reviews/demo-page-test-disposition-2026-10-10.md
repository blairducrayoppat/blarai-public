# Disposition: independent review of the demo-page test fix (#1722 follow-up)

**Review:** the independent adversarial-reviewer agent of the #1739/#1740 review, 2026-10-10 about 23:20 -04:00, on
branch `fix/1722-demo-page-test` at `587ce186` over `main` `e675e32f`. It read the change against #1722's description
("Not in scope: demo.html and the demo-film-v1 release (LA's to decide)") and the #1722 journal fragment. It confirmed
that README.md no longer mentions demo.html and that `_tracked()` is `git ls-files`, so an untracked or deleted demo.html
still fails the kept assertion.
**Author of the fix and of this disposition:** the #1740 session.
**Outcome:** VERIFIED as the one correct fix; one should-fix in the same file, fixed.

```disposition
finding-1-module-docstring-still-says-the-readme-links-demo-html | FIXED | c6a6c3d7
```
