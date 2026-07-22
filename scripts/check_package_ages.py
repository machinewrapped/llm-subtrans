import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/{version}/json"
AGE_THRESHOLD = timedelta(hours=24)


def get_installed_packages() -> list[dict]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def get_latest_upload_time(name : str, version : str) -> datetime|None:
    url = PYPI_JSON_URL.format(name=name, version=version)
    try:
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read())
        urls = data.get("urls", [])
        if not urls:
            return None
        times = [
            datetime.fromisoformat(u["upload_time"]).replace(tzinfo=timezone.utc)
            for u in urls
        ]
        return max(times)
    except HTTPError as e:
        if e.code == 404:
            return None  # Not on PyPI (local/editable install)
        raise
    except URLError as e:
        print(f"WARNING: Could not reach PyPI to check package ages ({e}) - age check skipped.")
        return None


def main():
    packages = get_installed_packages()
    now = datetime.now(timezone.utc)
    fresh = []

    for pkg in packages:
        name, version = pkg["name"], pkg["version"]
        upload_time = get_latest_upload_time(name, version)
        if upload_time and (now - upload_time) < AGE_THRESHOLD:
            age_minutes = int((now - upload_time).total_seconds() / 60)
            fresh.append((name, version, age_minutes))

    if fresh:
        print(f"\nWARNING: {len(fresh)} package(s) published less than 24 hours ago:")
        for name, version, age_minutes in fresh:
            print(f"  {name} {version} (published {age_minutes} minutes ago)")
        print("DO NOT publish or run this build without investigating these packages!")
        sys.exit(1)
    else:
        print("Package age check passed - no packages published in the last 24 hours.")


if __name__ == "__main__":
    main()
