# OpenEPaperLink AP firmware bugs

Bugs found in the OpenEPaperLink AP firmware while building and hardware-testing
`py-oepl` v0.2.0 against a real AP (env `ESP32_S3_16_8_YELLOW_AP`, firmware **2.91**,
sha `9dc57673`). Line references are against the firmware source at commit
`5f95cea9`, file `ESP32_AP-Flasher/src/web.cpp` unless noted.

These are **AP-side** issues, not `py-oepl` issues. `py-oepl` already works around all
three. They are recorded here as upstream-PR candidates for
[OpenEPaperLink](https://github.com/OpenEPaperLink/OpenEPaperLink); none have been
reported yet.

---

## 1. `/save_cfg` reports errors as HTTP 200, double-sends, and lies on missing MAC

**Severity:** medium (clients cannot detect failures from the status code)

**Handler:** `save_cfg` POST, `web.cpp:387-427`.

Three distinct problems in one handler:

1. **Errors returned as HTTP 200.** When the MAC is not found, the handler sends
   `200 "Error while saving: mac not found"` (`web.cpp:422`) instead of a 4xx. A
   well-behaved HTTP client that trusts the status code treats this as success.

2. **Double-send on the mac-not-found path.** After sending the error at
   `web.cpp:422`, control falls through to the unconditional
   `request->send(200, "text/plain", "Ok, saved")` at `web.cpp:426`. Two responses
   are queued for one request.

3. **Missing/invalid MAC silently "succeeds".** If the `mac` param is absent (or
   `hex2mac` fails), neither inner branch runs and the request hits only the
   trailing `200 "Ok, saved"` at `web.cpp:426` — the AP claims success for a
   request it did nothing with.

**Suggested fix:** return `400`/`404` on the error paths and remove the
unconditional trailing `200 "Ok, saved"` so exactly one response is sent and the
status code reflects the outcome. Note that the neighbouring `tag_cmd` handler
already does this correctly (`400 "Error: mac not found"`, `web.cpp:515`), as does
`jsonupload` (`400 "mac not found"`, `web.cpp:1015`) — `save_cfg` is the outlier.

**How py-oepl works around it:** `_http` inspects 200 response bodies and raises
`OEPLResponseError` when the body starts with `"Error"`. This is a heuristic on
firmware strings and can be dropped once the firmware returns proper status codes.

---

## 2. `/save_apcfg` dereferences `sleeptime2` unguarded → AP crash risk

**Severity:** high (null-pointer dereference on a valid-looking partial request)

**Handler:** `save_apcfg` POST, `web.cpp:659-661`.

```cpp
if (request->hasParam("sleeptime1", true)) {
    config.sleepTime1 = static_cast<uint8_t>(request->getParam("sleeptime1", true)->value().toInt());
    config.sleepTime2 = static_cast<uint8_t>(request->getParam("sleeptime2", true)->value().toInt());
}
```

Every other field in this handler is individually guarded by its own
`hasParam(...)` check, which makes partial config writes safe (post one key, leave
the rest untouched). The `sleeptime1` branch is the exception: it reads
`sleeptime2` **without a guard of its own**. If a client posts `sleeptime1`
without `sleeptime2`, `getParam("sleeptime2", true)` returns `nullptr` and the
`->value()` call dereferences it — a crash on the AP.

This is easy to trigger precisely because the rest of the handler advertises
"set one field at a time" semantics.

**Suggested fix:** guard `sleeptime2` independently, or require the pair together:

```cpp
if (request->hasParam("sleeptime1", true)) {
    config.sleepTime1 = ...;
}
if (request->hasParam("sleeptime2", true)) {
    config.sleepTime2 = ...;
}
```

**How py-oepl works around it:** `set_ap_config_item()` rejects `sleeptime1` and
`sleeptime2` as single-key writes (raising `ValueError`), and a dedicated
`set_sleep_window(start_hour, end_hour)` always posts both keys together. So the
library can never send the crashing partial request.

---

## 3. HTTP `HEAD` requests are broken in the AP's HTTP stack

**Severity:** low (affects clients that probe with HEAD)

Reported from field use: issuing an HTTP `HEAD` request to the AP does not behave
correctly (the ESPAsyncWebServer setup on the AP does not handle it the way a
`GET` of the same resource would). Clients should probe resources with `GET`
rather than `HEAD`.

**How py-oepl works around it:** the library never issues a `HEAD` request anywhere;
existence checks use `GET` (returning `None` on 404) or the dedicated
`/check_file` endpoint.

---

## Verification notes

- Bugs 1 and 2 were confirmed by reading the handler source and, for bug 1, by
  observing the empty/`"Error..."` 200 responses against the live AP.
- Bug 2's crash was reasoned from the source (unguarded `nullptr` deref); it was
  **not** deliberately triggered against hardware to avoid crashing a live AP in
  use.
- Bug 3 is a user-reported field observation.
