# Changelog

## [0.5.0](https://github.com/g4bri3lDev/py-oepl/compare/v0.4.0...v0.5.0) (2026-08-27)


### Features

* expose the AP's own hostname rule ([#14](https://github.com/g4bri3lDev/py-oepl/issues/14)) ([4fbacdd](https://github.com/g4bri3lDev/py-oepl/commit/4fbacddf0fd654dededf5a048e5e02a2c2fdcf3c))

## [0.4.0](https://github.com/g4bri3lDev/py-oepl/compare/v0.3.0...v0.4.0) (2026-08-13)


### Features

* expose protocol knowledge consumers were reinventing ([#12](https://github.com/g4bri3lDev/py-oepl/issues/12)) ([56a4eaf](https://github.com/g4bri3lDev/py-oepl/commit/56a4eaf794967639ef696cefdb34dd7330cbaa82))

## [0.3.0](https://github.com/g4bri3lDev/py-oepl/compare/v0.2.3...v0.3.0) (2026-08-12)


### Features

* add TagCapability flags and TagType.has_button/has_led ([#10](https://github.com/g4bri3lDev/py-oepl/issues/10)) ([9e3370c](https://github.com/g4bri3lDev/py-oepl/commit/9e3370cd4adc4832bc39ecad9f49258a4fe45d13))

## [0.2.3](https://github.com/g4bri3lDev/py-oepl/compare/v0.2.2...v0.2.3) (2026-08-12)


### Bug Fixes

* keep __version__ in sync with releases ([#6](https://github.com/g4bri3lDev/py-oepl/issues/6)) ([459b98c](https://github.com/g4bri3lDev/py-oepl/commit/459b98c3fc96a1c12d23326b646201439e3bdecc))
* keep plain v* release tags in manifest mode ([#8](https://github.com/g4bri3lDev/py-oepl/issues/8)) ([7af5923](https://github.com/g4bri3lDev/py-oepl/commit/7af5923761c013c95843bb0be9b16bc4971bcc41))

## [0.2.2](https://github.com/g4bri3lDev/py-oepl/compare/v0.2.1...v0.2.2) (2026-08-12)


### Bug Fixes

* support epaper-dithering 6.x and align with HA core ([#4](https://github.com/g4bri3lDev/py-oepl/issues/4)) ([d97a713](https://github.com/g4bri3lDev/py-oepl/commit/d97a713f7f5c04e20f67f84c2959fef21258b47f))

## [0.2.1](https://github.com/g4bri3lDev/py-oepl/compare/v0.2.0...v0.2.1) (2026-07-16)


### Bug Fixes

* CI and golden-image hygiene ([0d33b77](https://github.com/g4bri3lDev/py-oepl/commit/0d33b776ff1441d03848c3301e9a691eddc47c72))
* license is Apache-2.0, add LICENSE file (metadata wrongly claimed MIT) ([564bd6c](https://github.com/g4bri3lDev/py-oepl/commit/564bd6c80f50758a30935f9aea4eea564ede103b))

## [0.2.0](https://github.com/g4bri3lDev/py-oepl/compare/v0.1.0...v0.2.0) (2026-07-16)


### Features

* AP operations API (variables, wifi, backup/restore, set_time default) ([9870b15](https://github.com/g4bri3lDev/py-oepl/commit/9870b151229979f2bd4109f750d4480d2ffe3d16))
* files namespace and OTA methods ([67ff220](https://github.com/g4bri3lDev/py-oepl/commit/67ff22058bbb7b7cd9402a11cef8d51fb838064f))
* full websocket message coverage and reconnect fixes ([f33b0f1](https://github.com/g4bri3lDev/py-oepl/commit/f33b0f1bcea3a2c21375e4de43f49d1c5761c7da))
* open enums, tolerant model parsing, full tag fields ([63249b0](https://github.com/g4bri3lDev/py-oepl/commit/63249b0fd17b33e572dc3cf531631cc97db0cd34))
* set_ap_config_item + set_sleep_window with sleeptime crash guard ([f3fee95](https://github.com/g4bri3lDev/py-oepl/commit/f3fee955dd6153d46546cf7cfd5493d9d6d353ae))
* tag operations API (get_tag, save_tag_config, delete_tag, upload_json, get_image_data) ([c46002b](https://github.com/g4bri3lDev/py-oepl/commit/c46002b473bdd325e9ccd3cbb7092912db653d7d))
* TagHandle convenience API, get_image, render-waiting ([51b6344](https://github.com/g4bri3lDev/py-oepl/commit/51b6344cc8578aabef6dfef1e420674415bf2c73))


### Bug Fixes

* correct LUT enum values and LED pattern mode encoding to match firmware ([df758a9](https://github.com/g4bri3lDev/py-oepl/commit/df758a9e588436f4d0aa9f3b56f177127cf73dc2))
* hand-build imgupload multipart and send JPEG (AP cannot parse aiohttp FormData) ([aa3c6fd](https://github.com/g4bri3lDev/py-oepl/commit/aa3c6fd79adf1397b5b6e1703c320cbbb354133c))
* harden decode_g5 against malformed payloads ([72f9cc6](https://github.com/g4bri3lDev/py-oepl/commit/72f9cc6290706125ede85d236f905ffe92662731))
* post-merge follow-ups (url-encoding, type coercion, contracts, cleanups) ([3fe6621](https://github.com/g4bri3lDev/py-oepl/commit/3fe662139267276b3044bfa935665561ee06229a))
* root the list() path — /edit's list branch takes it verbatim ([bb2b1aa](https://github.com/g4bri3lDev/py-oepl/commit/bb2b1aa1ace67314be7b9858d4c5d75f687838b3))
* split AP-wide purge out of delete_tag into purge_stale_tags() ([97cd99f](https://github.com/g4bri3lDev/py-oepl/commit/97cd99f56b9cad67b946c2b407181b79cb4243de))
* surface AP error bodies, lazy owned session, release leaked responses ([4605d4d](https://github.com/g4bri3lDev/py-oepl/commit/4605d4d154f41c5f3e0503fc1258b32ef8813928))


### Documentation

* record upstream firmware bugs and post-merge follow-ups ([814270f](https://github.com/g4bri3lDev/py-oepl/commit/814270fa802ede0b68f35330b27b4d2e62524e58))
* rewrite README against real API; make rich/epaper-dithering optional extras ([e3282f0](https://github.com/g4bri3lDev/py-oepl/commit/e3282f017f4829cf09f43382bcea10542dcf8b49))

## 0.1.0 (2026-04-12)


### Features

* add tag command ([cc61115](https://github.com/g4bri3lDev/py-oepl/commit/cc61115ae23aef04e27e877a9adf01c46d9fafc6))
* initial implementation with claude ([d2bdc69](https://github.com/g4bri3lDev/py-oepl/commit/d2bdc69a7006aaab6d18f405f944a65f56494147))


### Bug Fixes

* minor fixes ([41b62e1](https://github.com/g4bri3lDev/py-oepl/commit/41b62e1b6ebc741d8fbb219dc33522924307683f))
* minor fixes ([a8019ac](https://github.com/g4bri3lDev/py-oepl/commit/a8019ac074500cd0c3ec997459a4ed8ea981072d))
