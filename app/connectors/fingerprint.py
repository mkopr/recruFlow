import random
from typing import Any


class FingerprintPool:
    """Builds a randomized, internally-consistent set of browser headers per call.

    Rather than picking from a handful of frozen profiles, each call mixes a browser
    family from `_PROFILES` with a randomly chosen compatible OS, version, and
    language, multiplying out into ~1,400 distinct combinations while staying
    plausible: Safari never leaves macOS, only Chromium families get `sec-ch-ua`
    client hints, and the User-Agent's platform token always matches the chosen OS.

    Combos are drawn without replacement from a shuffled bag (`_next_combo`), so
    consecutive calls never repeat the same combo -- only once the bag empties does
    it reshuffle and start a new cycle, at which point the boundary is checked too
    so the last combo of one cycle can't equal the first of the next.
    """

    _WINDOWS: tuple[str, ...] = ("Windows NT 10.0; Win64; x64", "Windows NT 11.0; Win64; x64")
    _MACOS: tuple[str, ...] = (
        "Macintosh; Intel Mac OS X 10_15_7",
        "Macintosh; Intel Mac OS X 13_6",
        "Macintosh; Intel Mac OS X 14_5",
    )
    _LINUX: tuple[str, ...] = ("X11; Linux x86_64", "X11; Ubuntu; Linux x86_64")

    _LANGUAGES: tuple[str, ...] = (
        "en-US,en;q=0.9",
        "en-GB,en;q=0.9",
        "en-US,en;q=0.8,de;q=0.6",
        "en-CA,en;q=0.9,fr;q=0.6",
        "en-US,en;q=0.9,es;q=0.5",
        "en-US,en;q=0.5",
    )

    # Chrome inserts a random "GREASE" brand into sec-ch-ua as an anti-fingerprinting
    # measure -- both its version token and its position among the real brands vary.
    _CHROMIUM_GREASE_VERSIONS: tuple[str, ...] = ("8", "24", "99")

    _PROFILES: tuple[dict[str, Any], ...] = (
        {
            "family": "chrome",
            "os_tokens": _WINDOWS + _MACOS + _LINUX,
            "versions": tuple(range(118, 128)),
        },
        {"family": "edge", "os_tokens": _WINDOWS + _MACOS, "versions": tuple(range(118, 128))},
        {
            "family": "firefox",
            "os_tokens": _WINDOWS + _MACOS + _LINUX,
            "versions": tuple(range(115, 129)),
        },
        {
            "family": "safari",
            "os_tokens": _MACOS,
            "versions": ("16.4", "16.6", "17.0", "17.4", "17.5"),
        },
    )

    def __init__(self, *, rand: random.Random | None = None) -> None:
        self._rand = rand if rand is not None else random.Random()
        self._combo_bag: list[tuple[str, str, int | str, str]] = []
        self._last_combo: tuple[str, str, int | str, str] | None = None

    def get_headers(self) -> dict[str, str]:
        family, os_token, version, language = self._next_combo()
        return self._build_headers(family, os_token, version, language)

    def _next_combo(self) -> tuple[str, str, int | str, str]:
        # Draw without replacement from a shuffled "bag" of every (family, os,
        # version, language) combo instead of independent random picks, so no combo
        # repeats until the whole ~1,400-combo space has been used once.
        if not self._combo_bag:
            self._combo_bag = self._all_combos()
            self._rand.shuffle(self._combo_bag)
            if self._combo_bag[-1] == self._last_combo:
                self._combo_bag[0], self._combo_bag[-1] = self._combo_bag[-1], self._combo_bag[0]

        combo = self._combo_bag.pop()
        self._last_combo = combo
        return combo

    def _all_combos(self) -> list[tuple[str, str, int | str, str]]:
        return [
            (profile["family"], os_token, version, language)
            for profile in self._PROFILES
            for os_token in profile["os_tokens"]
            for version in profile["versions"]
            for language in self._LANGUAGES
        ]

    def _build_headers(
        self, family: str, os_token: str, version: int | str, language: str
    ) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": language,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }

        if family == "chrome":
            headers["User-Agent"] = (
                f"Mozilla/5.0 ({os_token}) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{self._chromium_version(version)} Safari/537.36"
            )
            headers.update(self._chromium_client_hints("Google Chrome", version, os_token))
        elif family == "edge":
            chrome_version = self._chromium_version(version)
            headers["User-Agent"] = (
                f"Mozilla/5.0 ({os_token}) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_version} Safari/537.36 Edg/{chrome_version}"
            )
            headers.update(self._chromium_client_hints("Microsoft Edge", version, os_token))
        elif family == "firefox":
            headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            headers["User-Agent"] = (
                f"Mozilla/5.0 ({os_token}; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"
            )
        elif family == "safari":
            webkit_build = "605.1.15"
            headers["User-Agent"] = (
                f"Mozilla/5.0 ({os_token}) AppleWebKit/{webkit_build} (KHTML, like Gecko) "
                f"Version/{version} Safari/{webkit_build}"
            )

        return headers

    def _chromium_version(self, major: int | str) -> str:
        return f"{major}.0.{self._rand.randint(1000, 6999)}.{self._rand.randint(0, 199)}"

    def _chromium_client_hints(
        self, brand: str, version: int | str, os_token: str
    ) -> dict[str, str]:
        if "Windows" in os_token:
            platform = "Windows"
        elif "Mac" in os_token:
            platform = "macOS"
        else:
            platform = "Linux"

        grease_version = self._rand.choice(self._CHROMIUM_GREASE_VERSIONS)
        brands = [
            f'"Chromium";v="{version}"',
            f'"{brand}";v="{version}"',
            f'"Not.A/Brand";v="{grease_version}"',
        ]
        self._rand.shuffle(brands)

        return {
            "sec-ch-ua": ", ".join(brands),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": f'"{platform}"',
        }
