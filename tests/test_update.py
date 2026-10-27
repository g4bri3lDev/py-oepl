"""Tests for the Updates namespace (client.updates). Mock-only: these flash a real AP."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses

from oepl import APInfo, Tag, UploadProgress
from oepl.client import OEPLClient
from oepl.exceptions import OEPLTimeoutError, OEPLUpdateError
from oepl.update import (
    Release,
    TagFirmware,
    UpdateStage,
    format_radio_version,
    normalize_version,
    same_version,
)

from .test_files import _parse_multipart

HOST = "192.168.1.1"
BASE = f"http://{HOST}"
REPO = "OpenEPaperLink/OpenEPaperLink"
RELEASES = f"https://api.github.com/repos/{REPO}/releases"
DOWNLOAD = f"https://github.com/{REPO}/releases/download/3.00"
RAW = f"https://raw.githubusercontent.com/{REPO}"
ENV = "ESP32_S3_16_8_YELLOW_AP"


@pytest.fixture
async def client():
    c = OEPLClient(HOST)
    yield c
    if c._session is not None:
        await c._session.close()


def _github_release(tag="3.00", published="2026-10-21T21:31:24Z", assets=None, **extra):
    names = assets if assets is not None else ["filesystem.json", "binaries.json", f"{ENV}.bin", "firmware_C6.json"]
    return {
        "tag_name": tag,
        "name": tag,
        "published_at": published,
        "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
        "body": "What changed",
        "assets": [
            {"name": n, "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/{n}"} for n in names
        ],
        **extra,
    }


def _release(**kwargs) -> Release:
    return Release.from_github(_github_release(**kwargs))


def _uploads(m) -> dict[str, bytes]:
    """Path to content of every /littlefs_put upload, in order."""
    uploads = {}
    for _args, kwargs in m.requests.get(("POST", aiohttp.client.URL(f"{BASE}/littlefs_put")), []):
        fields, files = _parse_multipart(kwargs["data"], kwargs["headers"]["Content-Type"])
        uploads[fields["path"].decode()] = files["data"]
    return uploads


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "normal"),
    [("3.00", "3"), ("3.0", "3"), ("2.90", "2.9"), ("2.9", "2.9"), ("3.10", "3.1"), ("10", "10"), ("2.98", "2.98")],
)
def test_normalize_version(version, normal):
    assert normalize_version(version) == normal


def test_firmware_reports_its_version_without_the_release_tags_zeros():
    # Seen on a real AP: it reports "3.0", the release is tagged "3.00".
    assert same_version("3.0", "3.00")
    assert not same_version("2.98", "3.00")


def test_radio_version_is_written_in_hex():
    assert format_radio_version(36) == "0024"


def test_ap_info_radio():
    # From a real AP's /sysinfo.
    info = APInfo.from_dict({"ap_version": 36, "hasC6": 1, "hasH2": 0})
    assert info.radio_chip == "C6"
    assert info.radio_version == 36
    assert APInfo.from_dict({"hasH2": 1}).radio_chip == "H2"
    assert APInfo.from_dict({}).radio_chip is None
    assert APInfo.from_dict({"ap_version": 0}).radio_version is None


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------


def test_release_from_github():
    release = _release()
    assert release.tag == "3.00"
    assert release.published_at == datetime(2026, 10, 21, 21, 31, 24, tzinfo=UTC)
    assert release.notes == "What changed"
    assert release.supports(ENV)
    assert not release.supports("SOME_OTHER_BOARD")
    assert release.radio_manifest_url("C6") == f"{DOWNLOAD}/firmware_C6.json"
    assert release.radio_manifest_url("H2") is None


def test_a_release_with_the_installed_version_is_no_update():
    build_time = int(datetime(2026, 10, 21, 21, 20, tzinfo=UTC).timestamp())
    assert not _release(tag="3.00").is_update("3.0", build_time)


def test_a_newer_release_is_an_update():
    build_time = int(datetime(2026, 10, 20, tzinfo=UTC).timestamp())
    assert _release(tag="3.00").is_update("2.98", build_time)


def test_a_release_older_than_a_developers_build_is_no_update():
    build_time = int(datetime(2026, 11, 1, tzinfo=UTC).timestamp())
    assert not _release(tag="3.00").is_update("3.01-dev", build_time)


async def test_latest_release_is_the_newest_one_for_the_board(client):
    with aioresponses() as m:
        m.get(
            RELEASES,
            payload=[
                _github_release("3.01", draft=True),
                _github_release("3.00", assets=["filesystem.json", "binaries.json", "OTHER.bin"]),
                _github_release("2.98"),
                _github_release("2.97"),
            ],
        )
        release = await client.updates.latest_release(ENV)
    assert release is not None
    assert release.tag == "2.98"


async def test_latest_release_none_when_no_release_fits(client):
    with aioresponses() as m:
        m.get(RELEASES, payload=[_github_release(assets=["binaries.json"])])
        assert await client.updates.latest_release(ENV) is None


async def test_radio_version_of_a_release(client):
    manifest = [
        {"filename": "bootloader_C6.bin", "address": "0x0", "version": "0001"},
        {"filename": "partition-table_C6.bin", "address": "0x8000", "version": "0001"},
        {"filename": "OpenEPaperLink_esp32_C6.bin", "address": "0x10000", "version": "0024"},
    ]
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/firmware_C6.json", body=json.dumps(manifest))
        assert await client.updates.radio_version(_release(), "C6") == 36
        assert await client.updates.radio_version(_release(), "H2") is None


async def test_filesystem_version(client):
    with aioresponses() as m:
        m.get(f"{BASE}/version.txt", body="3.00\n")
        assert await client.updates.filesystem_version() == "3.00"


# ---------------------------------------------------------------------------
# Filesystem and tag types
# ---------------------------------------------------------------------------


def _fs_entry(name, md5, size=4):
    return {"name": name, "path": f"/www/{name}", "size": size, "md5": md5, "url": f"{RAW}/sha/{name}"}


async def test_filesystem_uploads_only_what_changed_and_the_version_last(client):
    files = [_fs_entry("index.html.gz", "same"), _fs_entry("main.js.gz", "new")]
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/filesystem.json", body=json.dumps(files))
        m.get(f"{BASE}/check_file?path=/www/index.html.gz", payload={"filesize": 4, "md5": "same"})
        m.get(f"{BASE}/check_file?path=/www/main.js.gz", payload={"filesize": 4, "md5": "old"})
        m.get(f"{RAW}/sha/main.js.gz", body=b"js!!")
        m.post(f"{BASE}/littlefs_put", body="Ok", repeat=True)
        await client.updates.update_filesystem(_release())

    assert list(_uploads(m).items()) == [("/www/main.js.gz", b"js!!"), ("/www/version.txt", b"3.00")]


async def test_filesystem_runs_the_update_actions_first(client):
    files = [{**_fs_entry("update_actions.json", "x"), "path": "/update_actions.json"}]
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/filesystem.json", body=json.dumps(files))
        m.get(f"{RAW}/sha/update_actions.json", body=b'{"deletefile": []}')
        m.post(f"{BASE}/littlefs_put", body="Ok", repeat=True)
        m.post(f"{BASE}/update_actions", body="Clean up finished")
        await client.updates.update_filesystem(_release())

    assert list(_uploads(m)) == ["/update_actions.json", "/www/version.txt"]


async def test_filesystem_failure_keeps_the_old_version(client):
    files = [_fs_entry("main.js.gz", "new"), _fs_entry("main.css.gz", "new")]
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/filesystem.json", body=json.dumps(files))
        m.get(f"{BASE}/check_file?path=/www/main.js.gz", payload={"filesize": 0, "md5": ""})
        m.get(f"{BASE}/check_file?path=/www/main.css.gz", payload={"filesize": 0, "md5": ""})
        m.get(f"{RAW}/sha/main.js.gz", status=404)
        m.get(f"{RAW}/sha/main.css.gz", body=b"css!")
        m.post(f"{BASE}/littlefs_put", body="Ok", repeat=True)
        with pytest.raises(OEPLUpdateError, match="main.js.gz"):
            await client.updates.update_filesystem(_release())

    # The other files still went through; the version claims nothing.
    assert list(_uploads(m)) == ["/www/main.css.gz"]


async def test_tag_types_update_only_where_the_repo_is_newer(client):
    with aioresponses() as m:
        m.get(
            f"{BASE}/edit?list=%2Ftagtypes",
            payload=[
                {"type": "file", "name": "01.json", "size": 1},
                {"type": "file", "name": "02.json", "size": 1},
                {"type": "file", "name": "F0.json", "size": 1},
            ],
        )
        m.get(f"{RAW}/master/resources/tagtypes/01.json", body=b'{"version": 3}')
        m.get(f"{BASE}/edit?download=tagtypes%2F01.json", body=b'{"version": 2}')
        m.get(f"{RAW}/master/resources/tagtypes/02.json", body=b'{"version": 2}')
        m.get(f"{BASE}/edit?download=tagtypes%2F02.json", body=b'{"version": 2}')
        # A custom type the repository does not have.
        m.get(f"{RAW}/master/resources/tagtypes/F0.json", status=404)
        m.post(f"{BASE}/littlefs_put", body="Ok", repeat=True)
        await client.updates.update_tag_types()

    assert _uploads(m) == {"/tagtypes/01.json": b'{"version": 3}'}


# ---------------------------------------------------------------------------
# Flashing
# ---------------------------------------------------------------------------


def _binaries():
    return json.dumps([{"name": f"{ENV}.bin", "url": f"{DOWNLOAD}/{ENV}.bin", "size": 1234, "md5": "abc"}])


def _console(client, *lines):
    """A response callback that has the AP print *lines* while it answers."""

    def callback(url, **kwargs):
        for line in lines:
            client._fire_console(line)
        return CallbackResult(body="In progress")

    return callback


async def test_firmware_flash_follows_the_console_until_it_succeeds(client):
    client._connected = True
    progress = []
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/binaries.json", body=_binaries())
        m.get(f"{BASE}/github_proxy", status=400, body="url missing")
        m.post(
            f"{BASE}/update_ota",
            callback=_console(
                client,
                "start downloading",
                "Progress: 50% 617 1234",
                "Firmware update successful",
                "Reboot system now",
                "[reboot]",
            ),
        )
        m.post(f"{BASE}/reboot", body="OK Reboot")
        await client.updates.update_firmware(_release(), ENV, on_progress=progress.append)

    ((_args, kwargs),) = m.requests[("POST", aiohttp.client.URL(f"{BASE}/update_ota"))]
    assert kwargs["data"] == {"url": f"{DOWNLOAD}/{ENV}.bin", "md5": "abc", "size": "1234"}
    assert [p.percent for p in progress] == [0, 50, 100]
    assert {p.stage for p in progress} == {UpdateStage.FIRMWARE}
    # The AP keeps running the old image until it is rebooted; its page has a
    # button for that, which nobody presses here.
    assert ("POST", aiohttp.client.URL(f"{BASE}/reboot")) in m.requests


async def test_firmware_from_before_the_github_proxy_downloads_through_the_web_proxy(client):
    client._connected = True
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/binaries.json", body=_binaries())
        m.get(f"{BASE}/github_proxy", status=404)
        m.post(f"{BASE}/update_ota", callback=_console(client, "Firmware update successful"))
        m.post(f"{BASE}/reboot", body="OK Reboot")
        await client.updates.update_firmware(_release(), ENV)

    ((_args, kwargs),) = m.requests[("POST", aiohttp.client.URL(f"{BASE}/update_ota"))]
    assert kwargs["data"]["url"].startswith("http://openepaperlink.eu/getupdate/?url=https%3A%2F%2Fgithub.com")


async def test_firmware_flash_failure_raises_what_the_ap_said(client):
    client._connected = True
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/binaries.json", body=_binaries())
        m.get(f"{BASE}/github_proxy", status=400)
        m.post(f"{BASE}/update_ota", callback=_console(client, "Failed to download firmware file (HTTP code 404)"))
        with pytest.raises(OEPLUpdateError, match="HTTP code 404"):
            await client.updates.update_firmware(_release(), ENV)
        # Rebooting would only restart the old image.
        assert ("POST", aiohttp.client.URL(f"{BASE}/reboot")) not in m.requests


async def test_firmware_flash_times_out_without_an_outcome(client):
    client._connected = True
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/binaries.json", body=_binaries())
        m.get(f"{BASE}/github_proxy", status=400)
        m.post(f"{BASE}/update_ota", body="In progress")
        with pytest.raises(OEPLTimeoutError):
            await client.updates.update_firmware(_release(), ENV, timeout=0.01)


async def test_flashing_needs_a_connected_client(client):
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/binaries.json", body=_binaries())
        m.get(f"{BASE}/github_proxy", status=400)
        with pytest.raises(OEPLUpdateError, match="connected"):
            await client.updates.update_firmware(_release(), ENV)
        assert ("POST", aiohttp.client.URL(f"{BASE}/update_ota")) not in m.requests


async def test_firmware_for_another_board_is_refused(client):
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/binaries.json", body=_binaries())
        with pytest.raises(OEPLUpdateError, match="OTHER"):
            await client.updates.update_firmware(_release(), "OTHER")


async def test_radio_flash_gets_the_release_directory(client):
    client._connected = True
    with aioresponses() as m:
        m.post(
            f"{BASE}/update_c6",
            callback=_console(client, "C6 flash starting", "Progress: 100%", "Finished!"),
        )
        await client.updates.update_radio(_release(), "C6")

    ((_args, kwargs),) = m.requests[("POST", aiohttp.client.URL(f"{BASE}/update_c6"))]
    assert kwargs["data"] == {"url": DOWNLOAD}


async def test_radio_flash_failure_raises(client):
    client._connected = True
    with aioresponses() as m:
        m.post(f"{BASE}/update_c6", callback=_console(client, "The radio doesn't respond. :-( Try the update again."))
        with pytest.raises(OEPLUpdateError, match="doesn't respond"):
            await client.updates.update_radio(_release(), "C6")


async def test_install_stops_before_flashing_when_files_fail(client):
    client._connected = True
    with aioresponses() as m:
        m.get(f"{DOWNLOAD}/filesystem.json", body=json.dumps([_fs_entry("main.js.gz", "new")]))
        m.get(f"{BASE}/check_file?path=/www/main.js.gz", payload={"filesize": 0, "md5": ""})
        m.get(f"{RAW}/sha/main.js.gz", status=404)
        with pytest.raises(OEPLUpdateError):
            await client.updates.install(_release(), ENV)
        assert ("POST", aiohttp.client.URL(f"{BASE}/update_ota")) not in m.requests


async def test_radio_progress_runs_once_across_its_images(client):
    """The AP reports each image from 0 to 100%; the bar goes up once, by size."""
    client._connected = True
    sizes = {"bootloader_C6.bin": 22176, "partition-table_C6.bin": 3072, "OpenEPaperLink_esp32_C6.bin": 344528}
    release = Release.from_github(
        {
            **_github_release(),
            "assets": [
                {"name": name, "size": size, "browser_download_url": f"{DOWNLOAD}/{name}"}
                for name, size in {**sizes, "firmware_C6.json": 254}.items()
            ],
        }
    )
    # As a real AP printed it (progress lines thinned out).
    console = [
        "C6 flash starting",
        "downloading /firmware_C6.json",
        "  bootloader_C6.bin (version 0001)",
        "downloading /bootloader_C6.bin",
        "  partition-table_C6.bin (version 0001)",
        "downloading /partition-table_C6.bin",
        "  OpenEPaperLink_esp32_C6.bin (version 0024)",
        "downloading /OpenEPaperLink_esp32_C6.bin",
        "Connected to ESP32-C6 at 921600 baud",
        "Flashing /bootloader_C6.bin",
        "Progress: 100%",
        "Flash verified",
        "Flashing /partition-table_C6.bin",
        "Progress: 100%",
        "Flash verified",
        "Flashing /OpenEPaperLink_esp32_C6.bin",
        "Progress: 0%",
        "Progress: 50%",
        "Progress: 100%",
        "Flash verified",
        "Finished!",
    ]
    progress = []
    with aioresponses() as m:
        m.post(f"{BASE}/update_c6", callback=_console(client, *console))
        await client.updates.update_radio(release, "C6", on_progress=progress.append)

    percents = [p.percent for p in progress]
    assert percents == sorted(percents)
    # The bootloader and partition table are 7% of the bytes.
    assert percents == [0, 5, 6, 6, 53, 100, 100]


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

TAG_MAC = "6400000000000006"
TAG_VERSIONS = f"{RAW}/master/binaries/Tag/tagotaversions.json"
TAG_IMAGE = f"{RAW}/master/binaries/Tag/SOL_M2_29_UC_0029.bin"
IMAGE = b"firmware image"
IMAGE_MD5 = hashlib.md5(IMAGE).hexdigest()


def _tag(mac=TAG_MAC, **fields):
    return Tag.from_dict({"mac": mac, "hwType": 0x11, "lastseen": 1000, "ver": 0x27, **fields})


def _tag_versions(**extra):
    return json.dumps(
        [
            {
                "11": {"type": "SOL_M2_29_UC", "version": "0029", "md5": IMAGE_MD5},
                "2F": {
                    "type": "chroma29_8151",
                    "version": "0015",
                    "md5": "a",
                    "type_1": "chroma29_8151_B",
                    "version_1": "0016",
                    "md5_1": "b",
                },
                **extra,
            }
        ]
    )


async def test_tag_firmware_by_hardware_type(client):
    with aioresponses() as m:
        m.get(TAG_VERSIONS, body=_tag_versions(), repeat=True)
        firmware = await client.updates.tag_firmware(_tag())
        assert await client.updates.tag_firmware(_tag(hwType=0xE0)) is None
    assert firmware == TagFirmware("SOL_M2_29_UC", "0029", IMAGE_MD5)
    assert firmware.number == 0x29
    assert firmware.file_name == "SOL_M2_29_UC_0029.bin"


async def test_chroma_tags_pick_their_variant_from_the_mac(client):
    with aioresponses() as m:
        m.get(TAG_VERSIONS, body=_tag_versions(), repeat=True)
        plain = await client.updates.tag_firmware(_tag("00001F0000000001", hwType=0x2F))
        # 0x3F >> 5 is variant 1.
        variant = await client.updates.tag_firmware(_tag("00003F0000000001", hwType=0x2F))
    assert (plain.name, plain.version) == ("chroma29_8151", "0015")
    assert (variant.name, variant.version, variant.md5) == ("chroma29_8151_B", "0016", "b")


async def test_tag_firmware_versions_include_old_names(client):
    listing = [
        {"name": n}
        for n in ("SOL_M2_29_UC_0029.bin", "SOL_M2_29_UC_19.bin", "SOL_M2_29_UC_0027.bin", "SOL_M2_29_SSD_0029.bin")
    ]
    with aioresponses() as m:
        m.get(f"https://api.github.com/repos/{REPO}/contents/binaries/Tag", payload=listing)
        versions = await client.updates.tag_firmware_versions("SOL_M2_29_UC")
    assert [v.version for v in versions] == ["19", "0027", "0029"]


def _tag_events(client, *events):
    """A save_cfg callback that has the AP report *events* afterwards."""

    def callback(url, **kwargs):
        loop = asyncio.get_running_loop()
        for delay, event in enumerate(events, 1):
            fire = client._fire_tag_update if isinstance(event, Tag) else client._fire_upload_progress
            loop.call_later(delay * 0.001, fire, event)
        return CallbackResult(body="Ok")

    return callback


async def test_update_tag_stages_the_image_and_follows_the_tag(client):
    client._connected = True
    client._tags[TAG_MAC] = _tag()
    progress = []
    with aioresponses() as m:
        m.get(f"{BASE}/check_file?path=/SOL_M2_29_UC_0029.bin", payload={"filesize": 0, "md5": ""})
        m.get(TAG_IMAGE, body=IMAGE)
        m.post(f"{BASE}/littlefs_put", body="Ok")
        m.post(
            f"{BASE}/save_cfg",
            callback=_tag_events(
                client,
                # A check-in from before the update was queued does not count.
                _tag(lastseen=1000, ver=0x29),
                UploadProgress(src=TAG_MAC, current=1, total=4),
                UploadProgress(src=TAG_MAC, current=3, total=4),
                # A block asked for again does not move the progress back.
                UploadProgress(src=TAG_MAC, current=2, total=4),
                UploadProgress(src="00000000000000AA", current=4, total=4),
                UploadProgress(src=TAG_MAC, current=4, total=4),
                _tag(lastseen=2000, ver=0x29, wakeupReason=0xFC),
            ),
        )
        await client.updates.update_tag(
            TAG_MAC, TagFirmware("SOL_M2_29_UC", "0029", IMAGE_MD5), on_progress=progress.append
        )

    assert _uploads(m) == {"/SOL_M2_29_UC_0029.bin": IMAGE}
    ((_args, kwargs),) = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
    assert kwargs["data"] == {
        "mac": TAG_MAC,
        "contentmode": "5",
        "modecfgjson": '{"filename": "/SOL_M2_29_UC_0029.bin"}',
    }
    assert [p.percent for p in progress] == [None, None, 25, 75, 100, 100]
    assert {p.stage for p in progress} == {UpdateStage.TAG}


async def test_update_tag_reuses_an_image_the_ap_has(client):
    client._connected = True
    client._tags[TAG_MAC] = _tag()
    with aioresponses() as m:
        m.get(f"{BASE}/check_file?path=/SOL_M2_29_UC_0029.bin", payload={"filesize": 14, "md5": IMAGE_MD5})
        m.post(f"{BASE}/save_cfg", callback=_tag_events(client, _tag(lastseen=2000, ver=0x29)))
        await client.updates.update_tag(TAG_MAC, TagFirmware("SOL_M2_29_UC", "0029", IMAGE_MD5))
    assert _uploads(m) == {}


async def test_a_tag_refusing_the_image_raises(client):
    client._connected = True
    client._tags[TAG_MAC] = _tag()
    with aioresponses() as m:
        m.get(f"{BASE}/check_file?path=/SOL_M2_29_UC_19.bin", payload={"filesize": 9, "md5": "x"})
        m.post(f"{BASE}/save_cfg", callback=_tag_events(client, _tag(lastseen=2000, wakeupReason=0xE0)))
        with pytest.raises(OEPLUpdateError, match="refused"):
            await client.updates.update_tag(TAG_MAC, TagFirmware("SOL_M2_29_UC", "19"))


async def test_an_image_that_fails_its_md5_is_not_staged(client):
    client._connected = True
    with aioresponses() as m:
        m.get(f"{BASE}/check_file?path=/SOL_M2_29_UC_0029.bin", payload={"filesize": 0, "md5": ""})
        m.get(TAG_IMAGE, body=b"truncated")
        with pytest.raises(OEPLUpdateError, match="MD5"):
            await client.updates.update_tag(TAG_MAC, TagFirmware("SOL_M2_29_UC", "0029", IMAGE_MD5))
    assert _uploads(m) == {}
    assert ("POST", aiohttp.client.URL(f"{BASE}/save_cfg")) not in m.requests


async def test_a_tag_that_never_reports_times_out(client):
    client._connected = True
    with aioresponses() as m:
        m.get(f"{BASE}/check_file?path=/SOL_M2_29_UC_0029.bin", payload={"filesize": 14, "md5": IMAGE_MD5})
        m.post(f"{BASE}/save_cfg", body="Ok")
        with pytest.raises(OEPLTimeoutError):
            await client.updates.update_tag(TAG_MAC, TagFirmware("SOL_M2_29_UC", "0029", IMAGE_MD5), timeout=0.01)


async def test_tags_are_updated_one_at_a_time(client):
    client._connected = True
    other = "6400000000000007"
    client._tags.update({TAG_MAC: _tag(), other: _tag(other)})
    order = []
    firmware = TagFirmware("SOL_M2_29_UC", "0029", IMAGE_MD5)

    def save_cfg(url, data, **kwargs):
        mac = data["mac"]
        order.append(f"start {mac}")
        asyncio.get_running_loop().call_later(
            0.01, lambda: (order.append(f"done {mac}"), client._fire_tag_update(_tag(mac, lastseen=2000, ver=0x29)))
        )
        return CallbackResult(body="Ok")

    with aioresponses() as m:
        m.get(f"{BASE}/check_file?path=/SOL_M2_29_UC_0029.bin", payload={"filesize": 14, "md5": IMAGE_MD5}, repeat=True)
        m.post(f"{BASE}/save_cfg", callback=save_cfg, repeat=True)
        await asyncio.gather(client.updates.update_tag(TAG_MAC, firmware), client.updates.update_tag(other, firmware))
    assert order == [f"start {TAG_MAC}", f"done {TAG_MAC}", f"start {other}", f"done {other}"]
