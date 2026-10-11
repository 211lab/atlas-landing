#!/usr/bin/env python3
"""Generate the Atlas homepage background from the current local weather.

Fetches current conditions for the configured coordinates from Open-Meteo,
asks an OpenRouter image model for a photorealistic scene in which the word
"Atlas" appears as graffiti, then asks an OpenRouter vision model to verify the
result. Only images that pass verification replace the served background; any
failure leaves the previous image untouched.

No third-party packages: standard library only, so the runtime image stays small.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
WEATHER_URL = os.environ.get(
    "WEATHER_URL", "https://api.open-meteo.com/v1/forecast"
)

LAT = os.environ.get("WEATHER_LAT", "<latitude>")
LON = os.environ.get("WEATHER_LON", "<longitude>")
PLACE = os.environ.get("WEATHER_PLACE", "<configured-place>")

IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "google/gemini-2.5-flash-image")
VISION_MODEL = os.environ.get("VISION_MODEL", "google/gemini-2.5-flash")

DATA_DIR = os.environ.get("DATA_DIR", "/data")
IMAGE_PATH = os.path.join(DATA_DIR, "background.jpg")
META_PATH = os.path.join(DATA_DIR, "weather.json")

API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

# WMO weather interpretation codes (Open-Meteo).
WMO = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def log(msg: str) -> None:
    print(f"[atlas-weather] {msg}", flush=True)


def http_json(url: str, payload: dict | None = None, headers: dict | None = None,
              method: str | None = None, attempts: int = 4) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    last_err: Exception | None = None
    for i in range(attempts):
        req = urllib.request.Request(url, data=data, headers=hdrs,
                                     method=method or ("POST" if data else "GET"))
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            body = err.read().decode(errors="replace")
            last_err = RuntimeError(f"HTTP {err.code}: {body[:300]}")
            if err.code in (429, 500, 502, 503, 504) and i < attempts - 1:
                delay = 2 ** i * 5
                log(f"retrying after HTTP {err.code} in {delay}s")
                time.sleep(delay)
                continue
            raise last_err
        except Exception as err:  # noqa: BLE001 - network layer, retry then surface
            last_err = err
            if i < attempts - 1:
                time.sleep(2 ** i * 5)
                continue
            raise
    raise last_err if last_err else RuntimeError("request failed")


def fetch_weather() -> dict:
    params = ",".join([
        "temperature_2m", "relative_humidity_2m", "apparent_temperature",
        "is_day", "precipitation", "weather_code", "cloud_cover",
        "wind_speed_10m",
    ])
    url = (f"{WEATHER_URL}?latitude={LAT}&longitude={LON}"
           f"&current={params}&timezone=auto")
    data = http_json(url)
    cur = data.get("current", {})
    return {
        "temperature_c": cur.get("temperature_2m"),
        "apparent_c": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "precipitation_mm": cur.get("precipitation"),
        "cloud_cover": cur.get("cloud_cover"),
        "wind_kmh": cur.get("wind_speed_10m"),
        "is_day": bool(cur.get("is_day")),
        "code": int(cur.get("weather_code", 0) or 0),
        "observed_at": cur.get("time"),
        "place": PLACE,
    }


def scene_guidance(w: dict) -> str:
    code = w["code"]
    day = w["is_day"]
    if code in (95, 96, 99):
        light = "daytime" if day else "night"
        return (f"a dramatic {light} thunderstorm; dark towering clouds, "
                "sheets of rain, occasional lightning")
    if code in (71, 73, 75, 77, 85, 86):
        light = "daytime" if day else "night"
        return (f"a cold {light} snow scene; falling snow, snow collected on "
                "ledges and ground, overcast pale sky")
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        light = "daytime" if day else "night"
        wet = "heavy rain" if code in (65, 67, 82) else "rain"
        return (f"a {light} rain scene; {wet} falling, wet reflective surfaces, "
                "puddles, damp sheen on the wall")
    if code in (45, 48):
        light = "daytime" if day else "night"
        return (f"a misty {light} scene; dense fog softening the background, "
                "low visibility, cool grey light")
    if code == 3:
        light = "daytime" if day else "night"
        return (f"a flat overcast {light}; heavy grey cloud, soft diffuse "
                "light, no direct sun")
    if code == 2:
        light = "daytime" if day else "night"
        return (f"a partly cloudy {light}; broken clouds with patches of sky, "
                "dappled light")
    if code in (0, 1):
        return ("a bright clear-sky scene; strong sunlight, crisp shadows, "
                "vivid blue sky" if day else
                "a clear night; deep blue-black sky, stars, cool moonlight")


def build_prompt(w: dict) -> str:
    sky = scene_guidance(w) or "an overcast day"
    temp = w.get("temperature_c")
    temp_txt = f"{temp:.0f}°C" if isinstance(temp, (int, float)) else "unknown"
    return (
        "A photorealistic, cinematic wide photograph of a real urban scene, "
        f"shot in {PLACE} during {sky}. Conditions: "
        f"{WMO.get(w['code'], 'variable weather')}, around {temp_txt}, "
        f"wind {w.get('wind_kmh')} km/h. Show a textured wall or structure "
        "where the word \"Atlas\" is painted as large, bold graffiti, "
        "integrated into the scene and lit naturally by the weather. "
        "The word \"Atlas\" must be spelled exactly A-t-l-a-s, and it must be "
        "the only text or lettering anywhere in the image. "
        "Gritty, wet-street realism; shallow depth of field; 35mm photograph, "
        "natural colour grading, high detail. No people. No other graffiti, "
        "tags, signatures, posters, signs, watermarks, logos, captions or UI."
    )


def generate_image(prompt: str) -> tuple[bytes, dict]:
    payload = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "n": 1,
        "aspect_ratio": "16:9",
    }
    resp = http_json(f"{OPENROUTER_BASE}/images", payload,
                     headers={"Authorization": f"Bearer {API_KEY}"})
    items = resp.get("data") or []
    if not items or "b64_json" not in items[0]:
        raise RuntimeError(f"image response missing data: {json.dumps(resp)[:300]}")
    raw = base64.b64decode(items[0]["b64_json"])
    return raw, (resp.get("usage") or {})


def verify_image(image_bytes: bytes, w: dict) -> dict:
    b64 = base64.b64encode(image_bytes).decode()
    content = [
        {
            "type": "text",
            "text": (
                "You are a strict image reviewer. Inspect the attached image "
                "and reply with ONLY a JSON object with boolean keys "
                "\"spelling_ok\", \"photorealistic\", \"matches_weather\", and a "
                "short string \"notes\". spelling_ok is true only if the word "
                "\"Atlas\" appears exactly once, spelled A-t-l-a-s, and no other "
                "text or lettering appears. photorealistic is true only if the "
                "image looks like a real photograph rather than an illustration, "
                "3D render or painting. matches_weather is true only if the scene "
                f"is consistent with: {WMO.get(w['code'], 'variable weather')}, "
                f"temperature {w.get('temperature_c')}°C, "
                f"{'daytime' if w['is_day'] else 'night'}. "
                "Do not add any prose outside the JSON."
            ),
        },
        {"type": "image_url",
         "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]
    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 300,
    }
    resp = http_json(f"{OPENROUTER_BASE}/chat/completions", payload,
                     headers={"Authorization": f"Bearer {API_KEY}"})
    text = resp["choices"][0]["message"]["content"]
    if isinstance(text, list):
        text = "".join(part.get("text", "") for part in text)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError(f"verifier returned non-JSON: {text[:200]}")
    return json.loads(text[start:end + 1])


def atomic_write(path: str, data: bytes) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def main() -> int:
    if not API_KEY:
        log("OPENROUTER_API_KEY is not set")
        return 2

    os.makedirs(DATA_DIR, exist_ok=True)

    log(f"fetching weather for {PLACE} ({LAT},{LON})")
    weather = fetch_weather()
    log(f"conditions: {WMO.get(weather['code'], 'n/a')}, "
        f"{weather['temperature_c']}°C, day={weather['is_day']}")

    prompt = build_prompt(weather)
    log(f"generating image with {IMAGE_MODEL}")
    image, usage = generate_image(prompt)
    log(f"generated {len(image)} bytes (cost={usage.get('cost')})")

    log(f"verifying image with {VISION_MODEL}")
    verdict = verify_image(image, weather)
    log(f"verdict: {json.dumps(verdict)}")

    if not (verdict.get("spelling_ok") and verdict.get("photorealistic")
            and verdict.get("matches_weather")):
        log("verification failed; keeping the existing background")
        return 1

    atomic_write(IMAGE_PATH, image)
    meta = {
        "source": "openrouter",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": WMO.get(weather["code"], "weather"),
        "temperature_c": weather["temperature_c"],
        "is_day": weather["is_day"],
        "image_model": IMAGE_MODEL,
        "vision_model": VISION_MODEL,
        "place": PLACE,
        "verdict": verdict,
    }
    atomic_write(META_PATH, json.dumps(meta, indent=2).encode())
    log(f"published new background to {IMAGE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
