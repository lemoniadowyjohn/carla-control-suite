# V131 patch notes

Candidate branch `integration/v131-pre-claude-candidate` is based on production `225ed15d0da6444cc257835ca777aba281553f3c`. Source integration includes the verified portions of #65, #67, #69 stack, #49, #50, #55, #56, #64 plus V129 T1 partial and T2 mirror work. PR #54 edits were confirmed in #55 and not separately stacked. #70 and #63 were excluded because #70 remains failing and #63 awaits OC-A/review.

P0 follow-up `7b0194caf6dfac4bbcbc63e0ab5b9397b95ae1f2` makes the legacy cache purge a non-destructive stub and removes both automatic purge call sites. Regression test proves CARLA user cache/temp sentinel files remain and startup paths do not invoke cleanup. Focused lifecycle/ownership suite: 51 passed.

Whole-range `git diff --check` is clean. The exact independent review at `c95f9b4ece19b98fad2a1818f658fbe8686f0faa` confirmed P0 and whitespace fixes; disposition remains REQUEST_CHANGES for RQ5 split, RQ3 completeness, CRS adoption, and applied-intrinsics wiring. No live CARLA or scientific experiment was executed.
