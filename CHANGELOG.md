# Changelog

## [0.2.0](https://github.com/g4bri3lDev/py-oepl/compare/v0.1.0...v0.2.0) (2026-07-16)


### Features

* AP operations API (variables, wifi, backup/restore, set_time default) ([19d89ed](https://github.com/g4bri3lDev/py-oepl/commit/19d89ed661295d2a51bcb6615db618c0f9ec5293))
* files namespace and OTA methods ([74f6dd6](https://github.com/g4bri3lDev/py-oepl/commit/74f6dd60f63ad7fbd4d69ac86323c9d41112d1d9))
* full websocket message coverage and reconnect fixes ([c90dc82](https://github.com/g4bri3lDev/py-oepl/commit/c90dc82bc5f1243eec16d9118f6e549f8f79d6d2))
* open enums, tolerant model parsing, full tag fields ([5e7b889](https://github.com/g4bri3lDev/py-oepl/commit/5e7b889fb4d76d6997b2ea8d43ce0becc8cdafbd))
* set_ap_config_item + set_sleep_window with sleeptime crash guard ([f308410](https://github.com/g4bri3lDev/py-oepl/commit/f30841029a15341e50fbe3bcaf28043b0a031a36))
* tag operations API (get_tag, save_tag_config, delete_tag, upload_json, get_image_data) ([e18fa21](https://github.com/g4bri3lDev/py-oepl/commit/e18fa21180c7265dad2721c4debe103db8b36dce))
* TagHandle convenience API, get_image, render-waiting ([f59142f](https://github.com/g4bri3lDev/py-oepl/commit/f59142ff11f965af5a6b26ef355e4d4e8544ad61))


### Bug Fixes

* correct LUT enum values and LED pattern mode encoding to match firmware ([84905df](https://github.com/g4bri3lDev/py-oepl/commit/84905dfb76f03a03965b65bc2003d179bc76c637))
* hand-build imgupload multipart and send JPEG (AP cannot parse aiohttp FormData) ([6a5b9b0](https://github.com/g4bri3lDev/py-oepl/commit/6a5b9b0de9d99ab834cc359297b805123317671e))
* harden decode_g5 against malformed payloads ([0822a4c](https://github.com/g4bri3lDev/py-oepl/commit/0822a4cd30755545626f2c4bc372fc0f821c7540))
* post-merge follow-ups (url-encoding, type coercion, contracts, cleanups) ([9a6e1b4](https://github.com/g4bri3lDev/py-oepl/commit/9a6e1b4884d45a53f02b6e2ab211bbf993b58d77))
* root the list() path — /edit's list branch takes it verbatim ([08d7366](https://github.com/g4bri3lDev/py-oepl/commit/08d73665f107a89bdd3333b64787f47ff1032220))
* split AP-wide purge out of delete_tag into purge_stale_tags() ([c52297d](https://github.com/g4bri3lDev/py-oepl/commit/c52297d0208f3c009afdec5a91a6678a9d8e02c9))
* surface AP error bodies, lazy owned session, release leaked responses ([75f6b92](https://github.com/g4bri3lDev/py-oepl/commit/75f6b92eb253cfe537472d08d61fb32f43fe3dd9))


### Documentation

* record upstream firmware bugs and post-merge follow-ups ([4389f37](https://github.com/g4bri3lDev/py-oepl/commit/4389f3751b4c38bc0e1b64c366f00eb3b216c138))
* rewrite README against real API; make rich/epaper-dithering optional extras ([3988b33](https://github.com/g4bri3lDev/py-oepl/commit/3988b33c7a3568374d684981a19e2c904dc023b6))

## 0.1.0 (2026-04-12)


### Features

* add tag command ([cc61115](https://github.com/g4bri3lDev/py-oepl/commit/cc61115ae23aef04e27e877a9adf01c46d9fafc6))
* initial implementation with claude ([d2bdc69](https://github.com/g4bri3lDev/py-oepl/commit/d2bdc69a7006aaab6d18f405f944a65f56494147))


### Bug Fixes

* minor fixes ([41b62e1](https://github.com/g4bri3lDev/py-oepl/commit/41b62e1b6ebc741d8fbb219dc33522924307683f))
* minor fixes ([a8019ac](https://github.com/g4bri3lDev/py-oepl/commit/a8019ac074500cd0c3ec997459a4ed8ea981072d))
