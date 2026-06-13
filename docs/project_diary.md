# Project Diary

- 2026-06-13: Web evidence needed a second pass beyond Brave snippets. Fetching readable article text for each normalized top candidate and preserving body text through compaction was necessary to keep Gemma from seeing title-only evidence. The larger `LLM_CTX_SIZE` in Docker Compose gives that richer packet enough room.
- 2026-06-13: A structured-only rewrite stage was too narrow for the real pipeline. Generalizing it into claim context completion before both retrieval routes keeps abrupt web claims anchored in their source text while still letting structured claims refresh local query text when the completion changes.
