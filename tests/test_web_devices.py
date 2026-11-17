"""The device in words (spec 6.3 of stage 7.2): a real `User-Agent` for each row of the tables, the unknown ones, a long one."""

import pytest

from app.web.devices import MAX_USER_AGENT, UNKNOWN_DEVICE, device_words

ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
)
ANDROID_SAMSUNG = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 "
    "Chrome/121.0.0.0 Mobile Safari/537.36"
)
ANDROID_YANDEX = (
    "Mozilla/5.0 (Linux; arm_64; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 "
    "YaBrowser/24.10.0.0 Mobile Safari/537.36"
)
ANDROID_EDGE = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36 "
    "EdgA/130.0.0.0"
)
IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
IPHONE_CHROME = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0.6723.37 "
    "Mobile/15E148 Safari/604.1"
)
IPAD_SAFARI = (
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
IPAD_AS_A_MAC = (  # iPadOS 13 and later: the User-Agent of a Mac (KI-72)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)
WINDOWS_EDGE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)
WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
WINDOWS_OPERA = WINDOWS_CHROME + " OPR/115.0.0.0"
WINDOWS_FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"
MAC_SAFARI = IPAD_AS_A_MAC
LINUX_FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"
CHROMEOS = (
    "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@pytest.mark.parametrize(
    "user_agent, words",
    [
        (ANDROID_CHROME, "Android, Chrome"),
        (ANDROID_SAMSUNG, "Android, Samsung Internet"),
        (ANDROID_YANDEX, "Android, Яндекс Браузер"),
        (ANDROID_EDGE, "Android, Edge"),
        (IPHONE_SAFARI, "iPhone, Safari"),
        (IPHONE_CHROME, "iPhone, Chrome"),
        (IPAD_SAFARI, "iPad, Safari"),
        (WINDOWS_EDGE, "Windows, Edge"),
        (WINDOWS_CHROME, "Windows, Chrome"),
        (WINDOWS_OPERA, "Windows, Opera"),
        (WINDOWS_FIREFOX, "Windows, Firefox"),
        (MAC_SAFARI, "macOS, Safari"),
        (LINUX_FIREFOX, "Linux, Firefox"),
        (CHROMEOS, "ChromeOS, Chrome"),
    ],
    ids=lambda value: value[:24],
)
def test_a_real_user_agent_gives_the_system_and_the_browser(user_agent, words):
    assert device_words(user_agent) == words


def test_an_ipad_that_says_it_is_a_mac_reads_as_a_mac_known_issue_72():
    assert device_words(IPAD_AS_A_MAC) == "macOS, Safari"


@pytest.mark.parametrize("user_agent", ["", "curl/8.5.0", "Mozilla/5.0", "python-httpx/0.27"])
def test_an_empty_or_unknown_user_agent_is_an_unknown_device(user_agent):
    assert device_words(user_agent) == UNKNOWN_DEVICE == "неизвестное устройство"


def test_a_missing_user_agent_is_an_unknown_device():
    assert device_words(None) == UNKNOWN_DEVICE  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "user_agent, words",
    [("Mozilla/5.0 (Windows NT 10.0) SomeTool/1.0", "Windows"), ("Firefox/100.0", "Firefox"), ("Mozilla/5.0 Version/17 Safari/604", "Safari")],
)
def test_one_known_part_stands_alone(user_agent, words):
    assert device_words(user_agent) == words


def test_safari_needs_its_version_mark():
    assert device_words("SomeWebView/1.0 Safari/604.1") == UNKNOWN_DEVICE


def test_the_first_match_of_a_table_wins():
    # a Chrome-based browser says "Chrome/" too; its own mark comes first in the table
    assert device_words(ANDROID_SAMSUNG) != device_words(ANDROID_CHROME)
    assert device_words("Android YaBrowser/1 Edg/1 OPR/1 Firefox/1 Chrome/1") == "Android, Яндекс Браузер"


def test_a_long_user_agent_is_cut_before_it_is_read():
    padding = "x" * MAX_USER_AGENT
    assert device_words(padding + " Firefox/132.0") == UNKNOWN_DEVICE  # the mark is past the 512 characters
    assert device_words(WINDOWS_FIREFOX + " " + padding) == "Windows, Firefox"  # the marks come first
