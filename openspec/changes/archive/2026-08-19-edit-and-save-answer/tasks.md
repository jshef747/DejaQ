## 1. Cache store primitive

- [x] 1.1 Add `MemoryService.overwrite_answer(entry_id, answer, *, authored)` replacing only the answer
- [x] 1.2 Redirect an `alias_of` entry's write to its root and return the id actually written
- [x] 1.3 Cascade the new answer to every alias of the root, as `delete_entry` cascades deletions
- [x] 1.4 Preserve `score`, `hit_count`, `negative_count` and all `image_*`/`file_*` keys
- [x] 1.5 Raise `KeyError` for a missing entry, matching `update_score`/`get_negative_count`
- [x] 1.6 Accept `authored` on `store_interaction`; carry it from parent to alias in `store_alias`
- [x] 1.7 Expose `authored` on `CacheLookupResult` and populate it during lookup
- [x] 1.8 Skip `authored == "human"` entries in `evict_below_floor`

## 2. Edit service

- [x] 2.1 New `services/answer_edit.py` with `apply_edited_answer`
- [x] 2.2 Overwrite path when the entry exists; return `saved` and the written id
- [x] 2.3 Create path from the hash-verified replay when it does not; return `created`
- [x] 2.4 Return `not_cached` when there is nothing to overwrite and no replay
- [x] 2.5 Return `message_mismatch` on a replay whose hash does not match
- [x] 2.6 Reject an empty or oversized answer
- [x] 2.7 Lift the per-workspace override helpers into `services/workspace_overrides.py`

## 3. Feedback contract

- [x] 3.1 `FeedbackRequest.edited_answer`, requiring `rating="positive"` and `interaction_id`
- [x] 3.2 `edit_status` and `response_id` on `FeedbackResult` and `FeedbackResponse`
- [x] 3.3 Apply the edit before scoring, and score the id the edit wrote
- [x] 3.4 Do not score when the edit did not land
- [x] 3.5 Keep both legacy response shapes intact for requests without an edit
- [x] 3.6 Record `edited` on the `feedback_log` row

## 4. Protections

- [x] 4.1 `generalize_and_store_task` skips an `authored="human"` entry
- [x] 4.2 `_bg_generalize_and_store` carries the same guard
- [x] 4.3 Context adjuster skipped on a human-authored cache hit
- [x] 4.4 `x-dejaq-answer-authored` emitted, exposed via CORS, forwarded by the chat proxy

## 5. Chat app

- [x] 5.1 `edit-draft.ts` — `canSave`, `normalizeDraft`, `isSaveShortcut`, `editStatusNotice`
- [x] 5.2 Edit affordance in the hover-revealed meta row
- [x] 5.3 Inline editor matching the reading column's type metrics, auto-grow, caret to end
- [x] 5.4 Save/Cancel, Cmd/Ctrl+Enter and Esc, blast-radius line
- [x] 5.5 `saveEditedAnswer` in `chat-api.ts` and the proxy route mapping
- [x] 5.6 `handleSaveEdit` in `ChatApp`, withholding the replay for attachment turns
- [x] 5.7 `editedByUser` persisted; terminal thumbs-up state after a save

## 6. Tests & docs

- [x] 6.1 `tests/test_answer_edit_service.py`
- [x] 6.2 `tests/test_human_authored_entries.py`
- [x] 6.3 Router cases in `tests/test_feedback_router.py`
- [x] 6.4 `chat/app/components/edit-draft.test.ts`
- [x] 6.5 `docs/openai-compat-api.md` and `CLAUDE.md`
