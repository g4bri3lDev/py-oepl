# py-oepl follow-ups

Deferred, non-blocking items for `py-oepl`, triaged during the v0.2.0 whole-branch
review as acceptable to land after merge. None affect correctness against the
firmware for the common paths; each notes why it was deferred and what a fix looks
like. Ordered roughly by real-world impact on the Home Assistant integration that
consumes this library.

---

## 1. URL-encode query-string values

**Where:** `_http` GET helpers, `files.*` (`/edit?list=`, `/edit?download=`,
`check_file?path=`), and `get_image_data` (`getdata?mac=&md5=`).

**Problem:** path/query values are interpolated into URLs without escaping
(`f"edit?list={dir}"`, etc.). This is a codebase-wide convention — `mac`/`md5` are
hex and safe — but `files.*` deals with arbitrary paths, so a filename containing
a space, `&`, `#`, or `?` would corrupt the query string.

**Why deferred:** the HA integration needs tag operations, not arbitrary-filename
file management, so the exposed surface is low. Still the highest-reach item here.

**Fix:** run values through `urllib.parse.quote` (or pass aiohttp `params=`) in the
affected call sites.

**Status:** implemented in `chore/followups`. Added `_http.quote_query_value`
(`urllib.parse.quote`, default `safe="/"` since these values are themselves
rooted filesystem paths) and applied it to every hand-built query-string value:
`files.list`/`download`/`check`, `get_tags`/`get_tag`'s `mac=`, `set_led`'s
`mac=`/`pattern=`, and `get_image_data`'s `mac=`/`md5=`. Tests cover a filename
with a space and one with `&` in `tests/test_files.py`.

---

## 2. Coerce malformed value *types* in model parsing

**Where:** `models.py` `from_dict` methods; surfaces via the `*_at` datetime
properties.

**Problem:** tolerant parsing tolerates *missing* keys (typed defaults) but stores
*present-but-malformed* values as-is. E.g. a firmware payload with
`lastseen: "not-a-number"` parses fine, then `tag.last_seen_at` raises `TypeError`
deep inside `datetime.fromtimestamp`.

**Why deferred:** the firmware sends well-typed integers; this only bites on a
firmware bug or corruption, and the raw value is preserved on `.raw` for
diagnostics. It's a systemic design characteristic, not a specific defect.

**Fix:** coerce int/timestamp fields in `from_dict` (fall back to the typed default
on failure), or make the `*_at` properties defensive (return `None` on non-int
input).

**Status:** implemented in `chore/followups`. Added `_as_int`/`_as_optional_int`
helpers in `models.py` and applied them to every plain-`int` (and `int | None`)
field parsed in `Tag`, `APStatus`, `APInfo`, `APConfig`, `APListItem`,
`UploadProgress`, `TagType`, `WifiNetwork`, and `SSIDList` `from_dict` methods —
present-but-malformed values now fall back to the typed default exactly like
missing keys, while `.raw` still preserves the original value verbatim. Tests
in `tests/test_models.py` cover `Tag.from_dict({"lastseen": "x", ...})` (field
falls back to `0`, `last_seen_at` is `None`, no raise) and the equivalent for
`APStatus`'s optional-int fields.

---

## 3. Log a warning when `upload_image(wait=True)` has no hash baseline

**Where:** `client.py` upload wait path (`pre_hash`).

**Problem:** when the target tag isn't in the local cache at upload time,
`pre_hash` is `None`, so the render-complete check degrades from "hash changed AND
`pending == 0`" to just "`pending == 0`" — it can resolve on an unrelated
`pending → 0` transition rather than the actual new render.

**Why deferred:** the cache is primed on WebSocket connect and `wait=True` already
requires a live connection, so the baseline is normally present; the degraded path
is a narrow race.

**Fix:** emit a `debug`/`warning` log when `pre_hash is None` so the weaker
guarantee is at least observable, or have the caller warm the cache with `get_tag`
before uploading.

**Status:** implemented in `chore/followups`. `_wait_for_render_complete` now
logs at `WARNING` when `pre_hash is None`, naming the tag and suggesting
`get_tag()` first to restore the full guarantee. Covered by
`tests/test_tag_handle.py::test_upload_image_wait_true_no_cache_baseline_logs_warning`
(via `caplog`).

---

## 4. `get_image` raises instead of returning `None` on unknown-type + no-image

**Where:** `client.py` `get_image`.

**Problem:** `get_image` checks the tag type before checking image existence, so a
tag with both an unrecognized `hw_type` *and* no stored image raises `ValueError`
rather than returning `None` (the documented "no image" contract).

**Why deferred:** the AP normally serves a matching `tagtypes/NN.json` for any
`hw_type` it assigns, so the combination is an edge case; raising when geometry is
unknown is a defensible choice (decoding is impossible without it).

**Fix:** decide the contract deliberately — either document the `ValueError`, or
check image existence first and return `None` before requiring the tag type. Worth
confirming against the HA integration's error-handling expectations.

**Status:** implemented in `chore/followups`. Decided in favor of checking image
existence first: `get_image` now fetches `current/<mac>.raw` before the tag type
lookup, so no stored image returns `None` even when `hw_type` is also unrecognized
(there's nothing to decode either way). `ValueError` is now raised only when an
image *is* stored but the AP has no type definition for it. Docstring and README
updated to describe the new ordering. Tests for both branches in
`tests/test_tag_handle.py` (`test_get_image_unknown_tag_type_raises`,
`test_get_image_no_image_and_unknown_tag_type_returns_none`).

---

## 5. Minor cleanups (cosmetic)

**Status:** all bullets below implemented in `chore/followups`.

- **`OEPLResponseError` docstring** says "Raised when the AP returns a non-200 HTTP
  status" — now also raised for HTTP-200-with-`"Error..."`-body. Update the wording.
  *Done — docstring now covers both failure modes.*
- **`_raise_if_error_body` `status` parameter** is redundant — both call sites always
  pass `200` (the body check only runs after the 200 gate). Drop the param.
  *Done — signature is now `_raise_if_error_body(body: str)`; it always raises with
  status `200` internally.*
- **`backup_db` calls `_http._request` directly** — the only client-side call that
  reaches into a private `_http` method. Add a small public `get_bytes` helper for
  consistency with the other GET wrappers.
  *Done — added `_HTTPClient.get_bytes` (raises `OEPLNotFoundError` on 404, unlike
  `get_raw`) and switched `backup_db` to use it.*
- **`upload_image` docstring** labels `content_mode=24` "static image" and 25
  "external"; the `ContentMode` enum names them `EXTERNAL_IMAGE` (24) and
  `HOME_ASSISTANT` (25). Reconcile the wording. (HA passes `content_mode`
  explicitly, so behavior is unaffected.)
  *Done — docstring and README now name both the wire value and the `ContentMode`
  enum member.*
- **`CancelledError` unsubscribe path** in the WebSocket wait helpers is correct
  (plain `try/finally`) but has no explicit test — add one so a future refactor
  can't silently break leak-freedom on cancellation.
  *Done — `tests/test_tag_handle.py::test_wait_for_checkin_cancellation_unsubscribes`
  cancels an in-flight `wait_for_checkin` task and asserts the subscription is gone.*
- **`post_multipart` does not run the error-body check** (unlike
  `post_form`/`get_text`). Necessary for `imgupload` (empty body on success), but
  `restore_db`/`littlefs_put` could return a 200 + error body that gets swallowed.
  Consider an opt-in body check for those two.
  *Done — `post_multipart` gained a `check_body: bool = False` keyword; when
  `True` it applies the same `_raise_if_error_body` check as `post_form`.
  Enabled for `restore_db` and `files.upload` (`littlefs_put`); left `False`
  (default) for `imgupload`, which relies on its empty-body success response.
  Tests: `test_restore_db_raises_on_200_error_body`,
  `test_upload_raises_on_200_error_body`,
  `test_upload_image_empty_body_still_succeeds`, plus
  `_http`-level coverage in `tests/test_http.py`.*

---

## Not doing (decided against)

- Battery-percentage curves and online/offline heuristics — these are
  integration-layer policy, not library concerns, and belong in the HA integration.
