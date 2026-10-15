### 2026-10-10 — A test that encodes a page's content has to change in the same merge as the page

*Plain summary: removing the demo video link from the README (#1722) left main failing a test that still required the link; it was found by the next branch gate, a day later, and the test now guards only what the LA kept (demo.html stays in the tree until he decides).*

The #1740 branch gate failed six tests. Five were worktree artifacts: three need the gitignored model weights, and two follow a relative link to `../../../devplatform` that only resolves at the main checkout's folder depth. The sixth also failed on main's real checkout. `test_the_demo_page_the_readme_links_to_is_in_the_tree` asserted two things: that `demo.html` is tracked, and that README.md contains `demo.html`. #1722 (`a3d62601`) removed the README link on the LA's instruction and kept the page for his decision, so the second assertion encoded a state he had reversed. The last stamped gate (`ce925cf2`) predates that merge. The #1722 arc reviewed the README text and the publish read-back, but no gate ran on the merged tree before the ticket closed.

I kept the first assertion: a snapshot built from a tree without `demo.html` deletes the published player, and the LA has not decided on it. I dropped the second (`587ce186`) and corrected the module docstring after the independent review (`c6a6c3d7`). The rejected alternative was inverting the assertion to "the README must not link demo.html". That would be a new lock on #1722's outcome, not this test's job, and nobody asked for it.

No lesson is proposed. "Run the gate on merged main" is already doctrine; this is one more instance of skipping it on a documentation-only merge.

**Next:** the post-merge gate on main's real checkout restamps the baseline.
