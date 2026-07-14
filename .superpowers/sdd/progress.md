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
