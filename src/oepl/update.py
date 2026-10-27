"""Updates namespace — find and install AP firmware the way its update page does.

Nothing on the AP decides whether an update exists: its update page
(``wwwroot/ota.js``) does all of that in the browser, against the GitHub
releases of the repository the AP is configured with. This module reproduces
it so other clients get the same answer and the same sequence.

A release is usable for an AP when it carries ``filesystem.json`` (the files
of the web interface), ``binaries.json`` (one firmware image per build
environment) and ``<env>.bin`` for the AP's build environment
(``ota.js:initUpdate``).

Installing follows the page's "Update now!" (``ota.js:updateAll``): the
filesystem first, then the tag types, and the firmware only once every file
is in place — new firmware with half of its web interface missing is worse
than the old version. The radio co-processor (ESP32-C6/H2) is updated
separately, as on the page.

Progress and the outcome of a flash are only reported as console lines over
the WebSocket (``wsSerial``, ``web.cpp:293``), so :meth:`Updates.update_firmware`
and :meth:`Updates.update_radio` need a connected client.

Tags are updated through the AP too (``main.js``, the tag's "auto update"
button): their firmware lives on the repository's master branch, listed in
``binaries/Tag/tagotaversions.json``, and the AP hands it to the tag when it
next checks in. See :meth:`Updates.update_tag`.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import aiohttp

from .enums import ContentMode, WakeupReason
from .exceptions import (
    OEPLConnectionError,
    OEPLError,
    OEPLNotFoundError,
    OEPLResponseError,
    OEPLTimeoutError,
    OEPLUpdateError,
)

if TYPE_CHECKING:
    from .client import OEPLClient
    from .models import Tag, UploadProgress

DEFAULT_REPO = "OpenEPaperLink/OpenEPaperLink"

_RELEASES_URL = "https://api.github.com/repos/{repo}/releases"
_TAG_TYPE_URL = "https://raw.githubusercontent.com/{repo}/master/resources/tagtypes/{name}"
# Firmware from before /github_proxy downloads over http only, and the page
# sends it its firmware through this proxy (ota.js:updateESP).
_LEGACY_PROXY = "http://openepaperlink.eu/getupdate/?url="
_TAG_FIRMWARE_URL = "https://raw.githubusercontent.com/{repo}/master/binaries/Tag/{name}"
_TAG_FIRMWARE_DIR_URL = "https://api.github.com/repos/{repo}/contents/binaries/Tag"

_GITHUB_TIMEOUT = aiohttp.ClientTimeout(total=30)
_FLASH_TIMEOUT = 600.0
# A tag only fetches its update when it next checks in, which can be a while.
_TAG_UPDATE_TIMEOUT = 2 * 60 * 60.0
# The page treats a release published up to this long before the running
# build as that build (ota.js:initUpdate): CI publishes after building.
_BUILD_GRACE_SECONDS = 30 * 60

_PROGRESS = re.compile(r"^Progress: (\d+)%")
# A radio flash lists the images of the manifest it picked, then flashes them
# in that order (espflasher.cpp).
_RADIO_IMAGE = re.compile(r"^  (\S+\.bin)")
_RADIO_FLASHING = "Flashing /"

# Console lines that end a firmware flash (ota.cpp:firmwareUpdateTask).
_FIRMWARE_DONE = ("Firmware update successful",)
_FIRMWARE_FAILED = ("Error", "Failed")
# And a radio flash (ota.cpp:C6firmwareUpdateTask).
_RADIO_DONE = ("Finished!",)
_RADIO_FAILED = ("The radio doesn't respond", "Flashing failed")


class UpdateStage(enum.Enum):
    """The step of an update that is running."""

    FILESYSTEM = "filesystem"
    TAG_TYPES = "tag_types"
    FIRMWARE = "firmware"
    RADIO = "radio"
    TAG = "tag"


@dataclass(frozen=True)
class UpdateProgress:
    """How far an update has got.

    *percent* is that of the current stage, or ``None`` where the AP reports
    none.
    """

    stage: UpdateStage
    percent: int | None
    message: str = ""


ProgressCallback = Callable[[UpdateProgress], None]


def normalize_version(version: str) -> str:
    """Return *version* without trailing zeros after the decimal point.

    Release 2.90 was tagged both "2.9" and "2.90", and firmware reports its
    version as built ("3.0") while the release is tagged "3.00"
    (``ota.js:normalizeVersion``).
    """
    trimmed = re.sub(r"(\.\d*?)0+$", r"\1", str(version))
    return trimmed.removesuffix(".")


def same_version(a: str, b: str) -> bool:
    """Whether two version strings name the same release."""
    return normalize_version(a) == normalize_version(b)


def format_radio_version(version: int) -> str:
    """Format a radio firmware version as its releases write it ("0024")."""
    return f"{version:04X}"


@dataclass(frozen=True)
class ReleaseFile:
    """One entry of a release's ``binaries.json`` or ``filesystem.json``."""

    name: str
    url: str
    size: int
    md5: str
    # Where the file goes on the AP. Only filesystem.json entries have one.
    path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReleaseFile":
        return cls(
            name=str(data.get("name", "")),
            url=str(data.get("url", "")),
            size=int(data.get("size", 0)),
            md5=str(data.get("md5", "")),
            path=str(data.get("path", "")),
        )


@dataclass(frozen=True)
class TagFirmware:
    """A firmware image for a tag, from ``binaries/Tag`` on the repository."""

    # The firmware, as tagotaversions.json names it ("SOL_M2_29_UC").
    name: str
    # Its version as written in the file name: "0029", or "19" for old ones.
    version: str
    # Known for the image tagotaversions.json lists; checked when known.
    md5: str = ""

    @property
    def number(self) -> int:
        """The version as the tag reports it (``Tag.firmware_version``)."""
        return int(self.version, 16)

    @property
    def file_name(self) -> str:
        """The image's file name, on the repository and on the AP."""
        return f"{self.name}_{self.version}.bin"


@dataclass(frozen=True)
class Release:
    """A GitHub release of the AP firmware."""

    tag: str
    name: str
    published_at: datetime
    url: str
    notes: str
    # Asset name to download URL.
    assets: dict[str, str] = field(default_factory=dict)
    # Asset name to size in bytes.
    asset_sizes: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_github(cls, data: dict[str, Any]) -> "Release":
        """Build from one entry of GitHub's list-releases response."""
        published = str(data.get("published_at") or "1970-01-01T00:00:00Z")
        return cls(
            tag=str(data.get("tag_name", "")),
            name=str(data.get("name") or data.get("tag_name", "")),
            published_at=datetime.fromisoformat(published.replace("Z", "+00:00")),
            url=str(data.get("html_url", "")),
            notes=str(data.get("body") or ""),
            assets={
                str(asset["name"]): str(asset["browser_download_url"])
                for asset in data.get("assets", [])
                if "name" in asset and "browser_download_url" in asset
            },
            asset_sizes={
                str(asset["name"]): int(asset.get("size") or 0) for asset in data.get("assets", []) if "name" in asset
            },
        )

    def supports(self, env: str) -> bool:
        """Whether this release can update an AP built as *env*."""
        return {"filesystem.json", "binaries.json", f"{env}.bin"} <= self.assets.keys()

    def radio_manifest_url(self, chip: str) -> str | None:
        """The URL of the radio firmware manifest for *chip* ("C6" or "H2")."""
        return self.assets.get(f"firmware_{chip}.json")

    def is_update(self, installed_version: str, build_time: int) -> bool:
        """Whether this release is newer than firmware *installed_version*.

        A release with the installed version is not, nor one published well
        before the installed firmware was built: that firmware is a
        developer's own build (``ota.js:initUpdate``).
        """
        if same_version(self.tag, installed_version):
            return False
        return self.published_at.timestamp() >= build_time - _BUILD_GRACE_SECONDS


class Updates:
    """Firmware updates of the AP. Use :attr:`OEPLClient.updates`, don't construct directly."""

    def __init__(self, client: OEPLClient) -> None:
        self._client = client
        # A queued tag update is held in the AP's memory whole (up to 64 KB,
        # newproto.cpp:prepareDataAvail), so tags are updated one at a time.
        self._tag_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Finding an update
    # ------------------------------------------------------------------

    async def releases(self, repo: str = DEFAULT_REPO) -> list[Release]:
        """Return the releases of *repo*, newest first.

        GitHub allows 60 unauthenticated API requests an hour per address, so
        callers checking regularly should do so sparingly.
        """
        data = await self._get_json(_RELEASES_URL.format(repo=repo))
        if not isinstance(data, list):
            raise OEPLUpdateError(f"Unexpected releases response from {repo}")
        return [Release.from_github(item) for item in data if not item.get("draft")]

    async def latest_release(self, env: str, repo: str = DEFAULT_REPO) -> Release | None:
        """Return the newest release of *repo* that can update an AP built as *env*."""
        return next((r for r in await self.releases(repo) if r.supports(env)), None)

    async def filesystem_version(self) -> str | None:
        """Return the release the AP's web interface files are from.

        Read from ``/version.txt``, which an update writes only once every
        file is in place. ``None`` if the AP has none.
        """
        try:
            version = await self._client._http.get_text("version.txt")
        except OEPLNotFoundError:
            return None
        return version.strip() or None

    async def radio_version(self, release: Release, chip: str) -> int | None:
        """Return the radio firmware version *release* carries for *chip*.

        The manifest lists the bootloader, partition table and application;
        the application's version is the radio's (``ota.js:fetchRadioFwVersion``).
        ``None`` if the release has no firmware for *chip*.
        """
        url = release.radio_manifest_url(chip)
        if url is None:
            return None
        manifest = await self._get_json(url)
        try:
            return int(manifest[2]["version"], 16)
        except (IndexError, KeyError, TypeError, ValueError) as err:
            raise OEPLUpdateError(f"Unexpected radio firmware manifest at {url}") from err

    # ------------------------------------------------------------------
    # Installing
    # ------------------------------------------------------------------

    async def install(
        self,
        release: Release,
        env: str,
        *,
        repo: str = DEFAULT_REPO,
        on_progress: ProgressCallback | None = None,
        timeout: float = _FLASH_TIMEOUT,
    ) -> None:
        """Bring the AP's files, tag types and firmware to *release*. **REBOOTS THE AP.**

        Stops before flashing if any file could not be updated.

        Raises:
            OEPLUpdateError: If a step fails; the steps before it stay done.
        """
        await self.update_filesystem(release, on_progress=on_progress)
        await self.update_tag_types(repo, on_progress=on_progress)
        await self.update_firmware(release, env, on_progress=on_progress, timeout=timeout)

    async def update_filesystem(self, release: Release, *, on_progress: ProgressCallback | None = None) -> None:
        """Bring the AP's web interface files to *release*.

        Only files whose size or MD5 differ are uploaded, so a retry is cheap.
        ``/version.txt`` is written last, and only when every file succeeded
        (``ota.js:updateWebpage``).

        Raises:
            OEPLUpdateError: If any file could not be updated.
        """
        stage = UpdateStage.FILESYSTEM
        files_url = release.assets.get("filesystem.json")
        if files_url is None:
            raise OEPLUpdateError(f"Release {release.tag} has no filesystem.json")
        files = [ReleaseFile.from_dict(item) for item in await self._get_json(files_url)]

        failed: list[str] = []
        actions = next((f for f in files if f.name == "update_actions.json"), None)
        if actions is not None:
            try:
                await self._client.files.upload(actions.path, await self._get_bytes(actions.url))
                await self._client.run_update_actions()
            except OEPLError as err:
                failed.append(f"{actions.path}: {err}")

        others = [f for f in files if f is not actions]
        for done, file in enumerate(others):
            _report(on_progress, stage, done * 100 // max(len(others), 1), file.path)
            try:
                current = await self._client.files.check(file.path)
                if current and current["filesize"] == file.size and current["md5"] == file.md5:
                    continue
                await self._client.files.upload(file.path, await self._get_bytes(file.url))
            except OEPLError as err:
                failed.append(f"{file.path}: {err}")

        if failed:
            raise OEPLUpdateError("Files not updated: " + "; ".join(failed))
        await self._client.files.upload("/www/version.txt", release.tag.encode())
        _report(on_progress, stage, 100)

    async def update_tag_types(self, repo: str = DEFAULT_REPO, *, on_progress: ProgressCallback | None = None) -> None:
        """Update the AP's tag type definitions that *repo* has newer versions of.

        Compares each file in ``/tagtypes`` with the one on the repository's
        master branch by its ``version`` field. Types the repository does not
        have, such as custom ones, are left alone, and nothing is deleted
        (``ota.js:fetchAndCheckTagtypes``).
        """
        stage = UpdateStage.TAG_TYPES
        names = [e.name for e in await self._client.files.list("/tagtypes") if e.name.endswith(".json")]
        for done, name in enumerate(names):
            _report(on_progress, stage, done * 100 // max(len(names), 1), name)
            remote = await self._get_raw(_TAG_TYPE_URL.format(repo=repo, name=name))
            if remote is None:
                continue
            local = await self._client.files.download(f"/tagtypes/{name}")
            if _tag_type_version(remote) > _tag_type_version(local):
                await self._client.files.upload(f"/tagtypes/{name}", remote)
        _report(on_progress, stage, 100)

    async def update_firmware(
        self,
        release: Release,
        env: str,
        *,
        on_progress: ProgressCallback | None = None,
        timeout: float = _FLASH_TIMEOUT,
    ) -> None:
        """Flash the AP's firmware from *release*. **REBOOTS THE AP.**

        Writing the image does not restart the AP: the firmware prints
        "Reboot system now" and a ``[reboot]`` marker, which its update page
        renders as a button, and keeps running the old image
        (``ota.cpp:updateFirmware``). Once the image is written this reboots
        the AP, as that button does, and returns.

        Raises:
            OEPLUpdateError: If the release has no image for *env*, or the AP
                reports the flash failed.
            OEPLTimeoutError: If the AP reports no outcome within *timeout*.
        """
        binaries_url = release.assets.get("binaries.json")
        if binaries_url is None:
            raise OEPLUpdateError(f"Release {release.tag} has no binaries.json")
        binaries = [ReleaseFile.from_dict(item) for item in await self._get_json(binaries_url)]
        image = next((b for b in binaries if b.name == f"{env}.bin"), None)
        if image is None:
            raise OEPLUpdateError(f"Release {release.tag} has no firmware for {env}")
        url = image.url if await self._downloads_https() else _LEGACY_PROXY + quote(image.url, safe="")

        await self._flash(
            lambda: self._client.update_ota(url, image.md5, image.size),
            UpdateStage.FIRMWARE,
            _FIRMWARE_DONE,
            _FIRMWARE_FAILED,
            on_progress,
            timeout,
        )
        await self._client.reboot_ap()

    async def update_radio(
        self,
        release: Release,
        chip: str,
        *,
        on_progress: ProgressCallback | None = None,
        timeout: float = _FLASH_TIMEOUT,
    ) -> None:
        """Flash the radio co-processor (*chip* "C6" or "H2") from *release*.

        The AP takes the release's download directory and picks the manifest
        its board needs itself (``espflasher.cpp``). Its radio is offline
        while flashing; the AP itself does not reboot.

        The AP flashes several images and reports each from 0 to 100%;
        progress is reported across all of them, weighted by size.

        Raises:
            OEPLUpdateError: If the release has no firmware for *chip*, or the
                AP reports the flash failed.
            OEPLTimeoutError: If the AP reports no outcome within *timeout*.
        """
        manifest_url = release.radio_manifest_url(chip)
        if manifest_url is None:
            raise OEPLUpdateError(f"Release {release.tag} has no firmware for the {chip}")
        directory = manifest_url.rsplit("/", 1)[0]
        await self._flash(
            lambda: self._client.update_c6(directory),
            UpdateStage.RADIO,
            _RADIO_DONE,
            _RADIO_FAILED,
            on_progress,
            timeout,
            progress=_RadioProgress(release.asset_sizes),
        )

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    async def tag_firmware(self, tag: Tag, repo: str = DEFAULT_REPO) -> TagFirmware | None:
        """Return the newest firmware *repo* has for *tag*, ``None`` if none.

        Looked up by hardware type in ``tagotaversions.json``. Chroma tags of
        one hardware type come in variants, told apart by bits of their MAC,
        each with its own firmware (``main.js``, ``#cfgautoupdate``).
        """
        url = _TAG_FIRMWARE_URL.format(repo=repo, name="tagotaversions.json")
        try:
            entry = (await self._get_json(url))[0].get(_hw_type_key(tag.hw_type))
        except (IndexError, KeyError, TypeError, AttributeError) as err:
            raise OEPLUpdateError(f"Unexpected tag firmware list at {url}") from err
        if not entry or not entry.get("type"):
            return None
        suffix = ""
        if str(entry["type"]).startswith("chroma"):
            variant = int(tag.mac[4:6], 16) >> 5
            if variant:
                suffix = f"_{variant}"
        name, version = entry.get("type" + suffix), entry.get("version" + suffix)
        if not name or not version:
            return None
        return TagFirmware(str(name), str(version), str(entry.get("md5" + suffix) or ""))

    async def tag_firmware_versions(self, name: str, repo: str = DEFAULT_REPO) -> list[TagFirmware]:
        """Return every image of firmware *name* on *repo*, oldest first.

        Older ones are kept alongside the newest, so a tag can be taken back
        to one: tags check that an image is firmware for them, not that it is
        newer (``Tag_FW_ZBS243``, ``validateFWMagic``). Very old images may
        predate that check and be refused.
        """
        listing = await self._get_json(_TAG_FIRMWARE_DIR_URL.format(repo=repo))
        pattern = re.compile(rf"^{re.escape(name)}_([0-9A-Fa-f]+)\.bin$")
        found = [
            TagFirmware(name, match[1])
            for entry in listing
            if isinstance(entry, dict) and (match := pattern.match(str(entry.get("name", ""))))
        ]
        return sorted(found, key=lambda firmware: firmware.number)

    async def update_tag(
        self,
        mac: str,
        firmware: TagFirmware,
        *,
        repo: str = DEFAULT_REPO,
        on_progress: ProgressCallback | None = None,
        timeout: float = _TAG_UPDATE_TIMEOUT,
    ) -> None:
        """Have tag *mac* install *firmware*. **A failed update can brick a tag.**

        Puts the image on the AP (unless it already has it) and switches the
        tag to the Firmware content mode, as the tag's "auto update" button
        does. The AP keeps the tag's content configuration and restores it
        once the image is delivered (``web.cpp``, ``pushTagInfo``). The tag
        fetches the image when it next checks in, flashes it and restarts.

        Progress is ``None`` until the tag starts fetching, then follows the
        blocks it fetches. Returns once the tag reports *firmware*'s version.
        One tag is updated at a time per AP; a second call waits.

        Raises:
            OEPLUpdateError: If the image cannot be put on the AP, or the tag
                refuses it (``WakeupReason.FAILED_OTA``).
            OEPLTimeoutError: If the tag does not report the new version
                within *timeout*.
        """
        if not self._client.connected:
            raise OEPLUpdateError("Following a tag update needs a connected client")
        mac = mac.upper()
        stage = UpdateStage.TAG
        async with self._tag_lock:
            _report(on_progress, stage, None, "Putting the firmware on the AP")
            path = "/" + firmware.file_name
            await self._stage_tag_firmware(path, firmware, repo)

            outcome: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
            known = self._client.tags.get(mac)
            seen_before = known.last_seen if known else 0
            highest = -1

            def _on_tag(tag: Tag) -> None:
                # Only what the tag reports after this update was queued.
                if outcome.done() or tag.last_seen <= seen_before:
                    return
                if tag.wakeup_reason == WakeupReason.FAILED_OTA:
                    outcome.set_result(f"Tag {mac} refused {firmware.file_name}")
                elif tag.firmware_version == firmware.number:
                    outcome.set_result(None)

            def _on_upload(progress: UploadProgress) -> None:
                nonlocal highest
                if outcome.done() or progress.src.upper() != mac or not progress.total:
                    return
                # A tag that loses a block asks for it again; never go back.
                percent = progress.current * 100 // progress.total
                if percent > highest:
                    highest = percent
                    _report(on_progress, stage, percent, f"Block {progress.current} of {progress.total}")

            unsubscribe_tag = self._client.on_tag_update(_on_tag, mac=mac)
            unsubscribe_upload = self._client.on_upload_progress(_on_upload)
            try:
                await self._client.save_tag_config(
                    mac, content_mode=ContentMode.FIRMWARE, mode_cfg_json={"filename": path}
                )
                _report(on_progress, stage, None, "Waiting for the tag to check in")
                try:
                    error = await asyncio.wait_for(outcome, timeout)
                except TimeoutError as err:
                    raise OEPLTimeoutError(f"Tag {mac} did not report {firmware.file_name} installed") from err
            finally:
                unsubscribe_tag()
                unsubscribe_upload()
        if error is not None:
            raise OEPLUpdateError(error)
        _report(on_progress, stage, 100)

    async def _stage_tag_firmware(self, path: str, firmware: TagFirmware, repo: str) -> None:
        """Put *firmware* on the AP at *path*, unless it already has it."""
        current = await self._client.files.check(path)
        if current and (not firmware.md5 or current["md5"] == firmware.md5):
            return
        data = await self._get_bytes(_TAG_FIRMWARE_URL.format(repo=repo, name=firmware.file_name))
        if firmware.md5 and hashlib.md5(data).hexdigest() != firmware.md5:
            raise OEPLUpdateError(f"{firmware.file_name} does not match its MD5")
        await self._client.files.upload(path, data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _flash(
        self,
        start: Callable[[], Awaitable[None]],
        stage: UpdateStage,
        done: tuple[str, ...],
        failed: tuple[str, ...],
        on_progress: ProgressCallback | None,
        timeout: float,
        *,
        progress: Callable[[str], int | None] | None = None,
    ) -> None:
        """Start a flash and follow the AP's console until it reports an outcome.

        *progress* turns a console line into the percentage to report, if it
        carries one; by default the AP's own ``Progress: N%`` is reported.
        """
        progress = progress or _plain_progress
        if not self._client.connected:
            raise OEPLUpdateError("Following a flash needs a connected client")
        outcome: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()

        def _on_console(line: str) -> None:
            if outcome.done():
                return
            if (percent := progress(line)) is not None:
                _report(on_progress, stage, percent, line)
            elif line.startswith(done):
                outcome.set_result(None)
            elif line.startswith(failed):
                outcome.set_result(line)

        unsubscribe = self._client.on_console(_on_console)
        try:
            _report(on_progress, stage, 0)
            await start()
            try:
                error = await asyncio.wait_for(outcome, timeout)
            except TimeoutError as err:
                raise OEPLTimeoutError(f"The AP reported no outcome of the {stage.value} update") from err
        finally:
            unsubscribe()
        if error is not None:
            raise OEPLUpdateError(error)
        _report(on_progress, stage, 100)

    async def _downloads_https(self) -> bool:
        """Whether the AP can download release files from GitHub itself.

        Firmware that can answers ``/github_proxy`` without a URL with 400;
        older firmware has no such endpoint.
        """
        try:
            await self._client._http.get_text("github_proxy")
        except OEPLNotFoundError:
            return False
        except OEPLResponseError:
            return True
        return True

    async def _github(self, url: str) -> aiohttp.ClientResponse | None:
        """GET *url*; ``None`` on 404."""
        try:
            resp = await self._client.session.get(url, timeout=_GITHUB_TIMEOUT)
        except aiohttp.ClientError as err:
            raise OEPLConnectionError(f"{url}: {err}") from err
        except TimeoutError as err:
            raise OEPLTimeoutError(f"{url} timed out") from err
        if resp.status == 404:
            resp.release()
            return None
        if resp.status != 200:
            body = await resp.text()
            resp.release()
            raise OEPLResponseError(resp.status, body)
        return resp

    async def _get_raw(self, url: str) -> bytes | None:
        resp = await self._github(url)
        return None if resp is None else await resp.read()

    async def _get_bytes(self, url: str) -> bytes:
        data = await self._get_raw(url)
        if data is None:
            raise OEPLNotFoundError(f"{url} not found")
        return data

    async def _get_json(self, url: str) -> Any:
        try:
            return json.loads(await self._get_bytes(url))
        except ValueError as err:
            raise OEPLUpdateError(f"{url} is not JSON") from err


def _hw_type_key(hw_type: int) -> str:
    """A hardware type as tagotaversions.json keys it ("01", or "0103")."""
    return f"{hw_type:0{4 if hw_type > 0xFF else 2}X}"


def _plain_progress(line: str) -> int | None:
    """The percentage of a ``Progress: N%`` console line."""
    match = _PROGRESS.match(line)
    return int(match[1]) if match else None


class _RadioProgress:
    """Progress across the images of a radio flash, weighted by their size.

    The AP lists the images of the manifest it picked, then flashes them in
    that order, reporting each from 0 to 100%. Images whose size the release
    does not give count equally.
    """

    def __init__(self, sizes: dict[str, int]) -> None:
        self._sizes = sizes
        self._images: list[str] = []
        self._current = -1

    def __call__(self, line: str) -> int | None:
        if match := _RADIO_IMAGE.match(line):
            self._images.append(match[1])
            return None
        if line.startswith(_RADIO_FLASHING):
            self._current += 1
            return None
        percent = _plain_progress(line)
        if percent is None or not 0 <= self._current < len(self._images):
            return percent
        weights = [self._sizes.get(name) or 0 for name in self._images]
        if not all(weights):
            weights = [1] * len(self._images)
        done = sum(weights[: self._current]) + weights[self._current] * percent / 100
        return int(done * 100 / sum(weights))


def _tag_type_version(data: bytes | None) -> int:
    """The ``version`` of a tag type definition, 0 if it has none or is unreadable."""
    if not data:
        return 0
    try:
        return int(json.loads(data).get("version", 0))
    except (ValueError, AttributeError, TypeError):
        return 0


def _report(callback: ProgressCallback | None, stage: UpdateStage, percent: int | None, message: str = "") -> None:
    if callback is not None:
        callback(UpdateProgress(stage, percent, message))


__all__ = [
    "DEFAULT_REPO",
    "Release",
    "ReleaseFile",
    "TagFirmware",
    "UpdateProgress",
    "UpdateStage",
    "Updates",
    "format_radio_version",
    "normalize_version",
    "same_version",
]
