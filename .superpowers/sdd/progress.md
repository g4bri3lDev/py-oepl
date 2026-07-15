# SDD progress — py-oepl remediation (plan: ~/.claude/plans/can-you-review-the-starry-wolf.md)
Branch: fix/firmware-contract (base 7712444)

## Baseline repro (Task 1) — complete, v0.1.0 vs live AP 11.0.30.148 (fw 2.91)
- P0-5 ✅ repro: GET tagtypes/e0.json→404, E0.json→200; lib get_tag_type(0xE0)→None
- P0-3 ✅ repro: default LEDPattern encodes 10e022000000000000000100; byte0 low nibble = mode = 0 = firmware "stop" → no-op
- P0-4 ✅ repro: on_ap_status fired 2× in 95s (sys msgs lack lowbattcount/timeoutcount except ~1/min)
- P0-1 ✅ repro, ROOT CAUSE BIGGER THAN PLANNED: aiohttp FormData puts "Content-Type: text/plain; charset=utf-8" on every text field → ESPAsyncWebServer treats those parts as FILES, params never register, hasParam("mac") false → upload silently ignored, fallback onRequest returns bare 200 EMPTY body. Verified: identical fields via curl → registers; manual multipart (Content-Disposition-only text parts) via aiohttp → registers. PNG would additionally fail TJpgDec ("invalid jpg" via wsErr). FIX = manual multipart encoder + JPEG output.
- /imgupload returns EMPTY 200 body even on success → body-check ("Ok, saved") NOT reliable for imgupload; verify by effect (modecfgjson/hash). Body-check IS valid for save_cfg/tag_cmd/etc.
- User-reported AP quirk: HEAD requests (curl -I) broken in AP http impl → lib must never issue HEAD.
- AP briefly went unreachable during probe (recovered); tag alias "MVG 22" = actively used display, content mode 25 (HA-managed) — expect concurrent writers on test tag.
- HARDWARE INCIDENT + LESSONS: test upload of 296x128 jpg to 296x152 tag (M2 2.6", hwType 0x04) garbled the screen — AP does NO scaling. Restored with correct-size image. Lessons baked into A2/B4: (1) upload params rotate/lut/invert/alias must be omitted unless explicitly set (imgupload persists them to the tag record — always-sending clobbers config); (2) size validation/auto-fit belongs in TagHandle.upload_image via TagType.
Task A1: complete (commit 84905df, review clean) — LUT values fixed, LED mode/brightness encoding + validation, 52 tests green
Task A2: complete (commit 6a5b9b0, review clean) — manual multipart encoder, JPEG output, omission-based params, 56 tests green
Task A3: complete (commit 5e7b889, review clean) — open IntEnums, tolerant parsing, raw retention, Tag hash/modecfgjson/invert/update_last, *_at props, tagtype case fix; 97 tests green
  Deferred findings (final-review triage): (a) APConfig.from_dict apstate=""/None crashes int() coercion — guard in B2; (b) tolerant parsing stores malformed value types as-is (e.g. lastseen:"x" breaks last_seen_at later) — systemic design decision.
Task A4: complete (commit 75f6b92, review clean) — error bodies surfaced (post_form/get_text only), lazy owned session (inject-websession compliant), response release; 115 tests green
  Minor findings deferred to final review: OEPLResponseError docstring stale; _raise_if_error_body status param redundant; disconnect() vs in-flight bare HTTP calls (pre-existing).
Task A5: complete (commit c90dc82, review clean) — REBOOTING reconnect fix, warning-level parse failures, apitem/upload/touch/console/on_raw_message coverage, APListItem+UploadProgress models; 136 tests green
Task A6: complete (commit 3988b33, review clean) — README rewritten against real API, rich/epaper-dithering extras, CLI guard, OpenDisplay naming swept; 136 tests green
Phase A hardware gate: PASSED on live AP fw 2.91 — tagtype 0xE0 resolves; upload registers+renders (hash change, pending cleared, on_upload_progress 1/1); LED mode=1 sent; on_ap_status 19x/95s (baseline 2x). Phase A complete at 3988b33.
Task B1: complete (commits e18fa21+c52297d, review clean) — get_tag/save_tag_config/delete_tag/upload_json/get_image_data, full TagCommand, purge split to AP-wide purge_stale_tags (firmware discrepancy found+fixed); 157 tests green. Note for Phase B hw pass: upload_json flips content mode to 19 — restore contentMode 25 on test tag afterwards.
FIRMWARE BUGS FOUND (upstream PR candidates for OpenEPaperLink):
  1. web.cpp save_cfg: errors returned as HTTP 200 + "Error..." body; double-send in mac-not-found path; missing-mac path lies "Ok, saved" (web.cpp:387-427).
  2. web.cpp save_apcfg: getParam("sleeptime2") dereferenced UNGUARDED inside the sleeptime1 hasParam branch (web.cpp:659-662) — posting sleeptime1 without sleeptime2 null-derefs → AP crash risk. Found by B2 implementer, confirmed.
  3. AP HTTP: HEAD requests broken (user-reported) — library must never issue HEAD.
Task B2: complete (commits 19d89ed+f308410, review clean) — set_ap_config_item (single-key), set_sleep_window (sleeptime null-deref guard), set_var(s), wifi trio (JSON body, factory guard, restart caveat), backup/restore_db, set_time default, apstate hardening; 191 tests green
  Minor deferred: backup_db calls _http._request directly — add public get_bytes wrapper (final-review triage).
Task B3: complete (commits 74f6dd6+08d7366, review: 1 Medium found+fixed) — Files namespace (client.files: list/download/upload/delete/check over /edit + /check_file + /littlefs_put) + OTA methods (update_ota/rollback/run_update_actions/update_c6). Added minimal public _http helpers (delete_form, get_json_any, post_form timeout=) instead of calling _request from client code, per B2 review note. 214 tests green.
  Firmware discrepancies found (verified against SPIFFSEditor.cpp/ota.cpp, commit 5f95cea9):
  - /check_file NEVER 404s — missing file is 200 {"filesize":0,"md5":""} (ota.cpp:73-107); check() detects the empty-md5 sentinel itself rather than relying on 404.
  - /edit DELETE always responds 200 once "path" is present, even for a nonexistent file — SPIFFSEditor.cpp:98-104 never checks _fs.remove()'s return value.
  - /edit path conventions are inconsistent WITHIN the handler: edit/download/DELETE branches prepend "/" internally, but the list branch passes its param verbatim to _fs.open() (SPIFFSEditor.cpp:82-84) and ESP32 VFS rejects unrooted paths (silently lists nothing); /check_file and /littlefs_put also use the path verbatim. So download()/delete() strip a leading slash; list()/check()/upload() add one (list() fix = review finding 08d7366 — first version wrongly stripped, breaking list(entry.name) since subdirectory FileEntry.name is unrooted). upload() uses /littlefs_put (not /edit's own multipart upload) since it gives a real write-failure signal (507) instead of a post-hoc exists() check.
  - update_ota/update_c6 are NOT long-running from the caller's perspective (contrary to initial assumption) — both launch a background FreeRTOS task and ack immediately ("In progress"/"Ok"); actual download+flash is reported only over the WebSocket.
  Deferred (recorded by reviewer for final review, pre-existing codebase-wide convention): query-string values aren't URL-encoded.
Task B3: complete (commits 74f6dd6+08d7366, review clean after list() slash fix) — files namespace (/edit, check_file, littlefs_put), OTA methods; 214 tests green
Task B4: complete (commit f59142f, review clean) — TagHandle, fit modes, get_image→PIL, tag-type cache, filtered callbacks, wait_for_checkin, upload wait=True; 258 tests green
  Minor deferred (final review): pre_hash=None silently weakens wait=True check (log it or warm cache); get_image ValueError-before-None ordering on unknown-type+no-image edge; no explicit CancelledError-unsubscribe test.
Phase B hardware gate: PASSED on live AP — get_tag/TagHandle/get_image(G5 decode)/files roundtrip/backup_db/wifi read/set_variable/set_ap_config_item/save_tag_config/upload fit=contain wait=True render-confirmed. Phase B complete at f59142f.
Task C: complete (commits b8a0616 golden harness + fa97f23 rework + 0822a4c crash-fix, review clean after falsification-test + IndexError regression fix) — g5_decoder pure codec, image.py unified pipeline, numpy+ctypes dropped, ruff/mypy exclusions removed, 13 goldens pixel-exact; 272 tests green
