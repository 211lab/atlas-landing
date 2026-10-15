#!/usr/bin/env python3
"""Generate the Atlas homepage background from the current local weather.

Fetches current conditions for the configured coordinates from Open-Meteo,
asks an OpenRouter image model for a photorealistic scene in which the word
"Atlas" appears as graffiti, then asks an OpenRouter vision model to verify the
result. Only images that pass verification replace the served background; any
failure leaves the previous image untouched.

Pillow is the only third-party dependency, used to strip model letterboxing and normalize image output.
"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
WEATHER_URL = os.environ.get(
    "WEATHER_URL", "https://api.open-meteo.com/v1/forecast"
)

LAT = os.environ.get("WEATHER_LAT", "").strip()
LON = os.environ.get("WEATHER_LON", "").strip()
PLACE = os.environ.get("WEATHER_PLACE", "").strip()
WEATHER_LABEL = os.environ.get("WEATHER_LABEL", "").strip()

IMAGE_MODELS = (
    "qwen/qwen-image-3",
    "meta/muse-image",
    "krea/krea-2-medium-turbo",
    "bytedance-seed/seedream-5-0-flash",
    "tencent/hy-image-v3.5-preview",
    "google/gemini-3.1-flash-lite-image",
)
IMAGE_MODEL = os.environ.get("IMAGE_MODEL")
VISION_MODEL = os.environ.get("VISION_MODEL", "google/gemini-2.5-flash")
# The artwork is a balanced 3:2 landscape; the API request must match the
# aspect ratio named in the prompt.
ASPECT_RATIO = os.environ.get("ASPECT_RATIO", "3:2")

# Visual recipe definitions are shared with the static prompt tool through
# catalogs.json. Live weather remains an independent runtime input.
@dataclass(frozen=True)
class CatalogEntry:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class Facet:
    id: str
    label: str
    entries: tuple[CatalogEntry, ...]


def _load_catalogs() -> tuple[Facet, ...]:
    path = Path(__file__).with_name("catalogs.json")
    with path.open(encoding="utf-8") as catalog_file:
        data = json.load(catalog_file)
    return tuple(
        Facet(facet["id"], facet["label"], tuple(
            CatalogEntry(entry["id"], entry["label"], entry["description"])
            for entry in facet["entries"]
        ))
        for facet in data
    )


CATALOGS = _load_catalogs()

WILDSTYLES = tuple((e.id, e.description) for e in CATALOGS[0].entries)


def select_recipe() -> dict[str, CatalogEntry]:
    return {facet.id: random.choice(facet.entries) for facet in CATALOGS}


def recipe_metadata(recipe: dict[str, CatalogEntry]) -> dict[str, str]:
    return {facet.id: recipe[facet.id].id for facet in CATALOGS}


def pick_wildstyle() -> tuple[str, str]:
    entry = random.choice(CATALOGS[0].entries)
    return entry.id, entry.description


def select_image_model() -> str:
    return os.environ.get("IMAGE_MODEL") or random.choice(IMAGE_MODELS)


# Camera and framing facets, drawn independently for every generation so the
# artwork is photographed differently each time while remaining physically
# plausible. All combinations are meant to be compatible.
CAMERA_HEIGHT = [
    "at ground level right at the base of the artwork",
    "at a low tripod position a short distance away",
    "at standing eye height across the plaza",
    "at an elevated vantage such as a walkway or balcony above",
    "well back near the far edge of the complex",
]
CAMERA_PITCH = [
    "pitched sharply upward so the artwork towers overhead",
    "pitched slightly upward with mild perspective convergence",
    "held level with no upward pitch",
    "pitched slightly downward to include more of the setting",
]
CAMERA_FRAMING = [
    "frontal and near-symmetrical with the artwork filling the centre",
    "as a three-quarter view revealing the depth of the surface",
    "off-axis with the artwork seen at an oblique slant",
    "as a diagonal composition with the artwork crossing the frame",
]
CAMERA_ROLL = [
    "with a subtle Dutch-angle roll",
    "with a pronounced Dutch-angle roll",
    "with no roll and true verticals",
]
CAMERA_FOCUS = [
    "with shallow depth of field isolating the artwork",
    "with deep focus keeping artwork and architecture sharp",
    "with mild long-lens compression",
]


def pick_camera() -> tuple[dict, str]:
    """Return the chosen camera facets and the prompt fragment describing them."""
    facets = {
        "height": random.choice(CAMERA_HEIGHT),
        "pitch": random.choice(CAMERA_PITCH),
        "framing": random.choice(CAMERA_FRAMING),
        "roll": random.choice(CAMERA_ROLL),
        "focus": random.choice(CAMERA_FOCUS),
    }
    fragment = (
        "CAMERA AND FRAMING: the camera is positioned "
        f"{facets['height']}, {facets['pitch']}, {facets['framing']}, "
        f"{facets['roll']}, {facets['focus']}."
    )
    return facets, fragment

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


def validate_location_config(lat: str, lon: str, place: str,
                             label: str) -> str | None:
    missing = [name for name, value in (
        ("WEATHER_LAT", lat), ("WEATHER_LON", lon),
        ("WEATHER_PLACE", place), ("WEATHER_LABEL", label),
    ) if not value]
    if missing:
        return "missing required location settings: " + ", ".join(missing)
    try:
        latitude, longitude = float(lat), float(lon)
    except ValueError:
        return "WEATHER_LAT and WEATHER_LON must be numeric"
    if not -90 <= latitude <= 90:
        return "WEATHER_LAT must be between -90 and 90"
    if not -180 <= longitude <= 180:
        return "WEATHER_LON must be between -180 and 180"
    return None


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
    temp_c = cur.get("temperature_2m")
    temperature_f = temp_c * 9 / 5 + 32 if isinstance(temp_c, (int, float)) else None
    apparent_c = cur.get("apparent_temperature")
    apparent_f = apparent_c * 9 / 5 + 32 if isinstance(apparent_c, (int, float)) else None
    return {
        "temperature_c": temp_c,
        "temperature_f": temperature_f,
        "apparent_c": apparent_c,
        "apparent_f": apparent_f,
        "humidity": cur.get("relative_humidity_2m"),
        "precipitation_mm": cur.get("precipitation"),
        "cloud_cover": cur.get("cloud_cover"),
        "wind_kmh": cur.get("wind_speed_10m"),
        "is_day": bool(cur.get("is_day")),
        "code": int(cur.get("weather_code", 0) or 0),
        "observed_at": cur.get("time"),
        "local_hour": int(str(cur.get("time", "")).split("T")[-1].split(":")[0] or 0),
        "utc_offset_seconds": int(data.get("utc_offset_seconds") or 0),
        "place": PLACE,
    }


def time_of_day(w: dict) -> str:
    """Phase of the local day, from the Open-Meteo local timestamp."""
    h = w.get("local_hour", 12)
    if h < 5:
        return "deep night"
    if h < 7:
        return "pre-dawn twilight"
    if h < 11:
        return "early morning"
    if h < 13:
        return "midday"
    if h < 17:
        return "afternoon"
    if h < 19:
        return "golden hour"
    if h < 21:
        return "dusk"
    return "night"


def weather_elements(w: dict) -> str:
    """Weather detail woven into the scene: sky, wind, precipitation, wetness."""
    code = w["code"]
    phase = time_of_day(w)
    cloud = w.get("cloud_cover")
    wind = w.get("wind_kmh") or 0
    precip = w.get("precipitation_mm") or 0
    humidity = w.get("humidity")

    if wind < 8:
        wind_txt = "still air"
    elif wind < 20:
        wind_txt = "a light wind moving the mist"
    elif wind < 40:
        wind_txt = "blustery winds funnelling between the structures"
    else:
        wind_txt = "gale-force winds whipping debris past the letters"

    cloud_txt = "overcast" if (cloud is None or cloud >= 85) else (
        "broken cloud" if cloud >= 50 else
        "scattered cloud" if cloud >= 20 else "clear sky")

    if code in (95, 96, 99):
        sky = "a towering storm front; sheets of rain and occasional lightning"
    elif code in (71, 73, 75, 77, 85, 86):
        sky = "falling snow settling on every horizontal surface"
    elif code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        heavy = "heavy rain" if code in (65, 67, 82) else "light rain"
        sky = f"{heavy}, rain-slicked reflective concrete and puddles"
    elif code in (45, 48):
        sky = "dense fog softening the far towers into silhouettes"
    else:
        sky = f"{cloud_txt}"

    temp_f = w.get("temperature_f")
    temp_txt = (f"around {temp_f:.0f}°F"
                if isinstance(temp_f, (int, float)) else "temperature unknown")
    parts = [
        f"It is {phase} in {PLACE}",
        f"the sky shows {sky}",
        temp_txt,
        f"with {wind_txt}",
    ]
    if precip:
        parts.append(f"recent precipitation {precip} mm/h")
    if humidity:
        parts.append(f"humidity {humidity}%")
    return ", ".join(str(p) for p in parts)


def lighting(w: dict) -> str:
    """Lighting and atmosphere, adapted to the current weather and time of day."""
    code = w["code"]
    phase = time_of_day(w)
    night = not w["is_day"] or phase in ("deep night", "night", "dusk")
    base = (
        "Gigantic architectural shadows stretch across the concrete landscape. "
        "Soft volumetric light penetrates deep structural voids and catches "
        "selected edges of the lettering. Subtle atmospheric haze, fine "
        "airborne dust and realistic depth-based contrast reduction emphasise "
        "the extraordinary size of the structures. High dynamic range, rich "
        "blacks, luminous concrete highlights and physically accurate global "
        "illumination."
    )
    if night:
        light = ("At night the megacity is lit by cold moonlight and sodium "
                 "floodlighting; lit windows dot the towers, and the wet "
                 "concrete mirrors the glow.")
    elif code in (95, 96, 99):
        light = ("Dramatic storm light with powerful shafts breaking through "
                 "dense cloud; distant lightning silhouettes the letters.")
    elif code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        light = ("Diffuse grey storm light; rain-slicked concrete reflects the "
                 "sky, water sheets down the letterforms and mist rises off "
                 "the surfaces.")
    elif code in (71, 73, 75, 77, 85, 86):
        light = ("Soft snow-diffused light; fresh snow dusts the horizontal "
                 "ledges and mutes every reflection.")
    elif code in (45, 48):
        light = ("Fog-diffused light with glowing halos around the floodlights; "
                 "distant structures fade into haze.")
    elif code == 3:
        light = ("Flat overcast diffusion with no hard shadows; the heavy cloud "
                 "casts a uniform cinematic grey light.")
    elif phase == "golden hour":
        light = ("Low golden sunlight rakes across the concrete at a shallow "
                 "angle, igniting the edges of the letters and throwing "
                 "kilometre-long shadows.")
    elif phase in ("pre-dawn twilight", "dusk"):
        light = ("Twilight grading from deep blue to a faint warm horizon "
                 "glow; the letters are caught between day and night light.")
    else:
        light = ("Dramatic directional sunlight breaks through atmospheric "
                 "cloud, raking across the concrete faces.")
    return f"{light} {base}"


def build_prompt(w: dict, recipe: dict[str, CatalogEntry]) -> str:
    weather = weather_elements(w)
    light = lighting(w)
    facets = "\n".join(
        f"{facet.label}: {recipe[facet.id].description}"
        for facet in CATALOGS
    )
    return (
        "Create a photorealistic architectural photograph.\n"
        f"VISUAL RECIPE:\n{facets}\n"
        f"LOCAL CONDITIONS near {WEATHER_LABEL}: {weather}. Respect these "
        "observed weather conditions in the visible scene.\n"
        f"LIGHTING CONTEXT: {light}\n"
        "SHARED INVARIANTS: The artwork spells exactly uppercase ATLAS in the "
        "correct order. All five letters must be clearly recognizable and the "
        "complete word must remain inside the frame. The painted artwork is "
        "physically integrated with and adheres to its believable supporting "
        "surface. Do not add any other words, lettering, tags, logos, captions, "
        "watermarks or marks; no other words are allowed. Use natural photographic optics, realistic "
        "materials and credible physical geometry."
    )

def refine_image(raw: bytes) -> bytes:
    """Strip uniform letterbox bars and return the artwork as a real JPEG."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    width, height = img.size
    gray = img.convert("L")
    limit_top, limit_bottom = int(height * 0.15), int(height * 0.85)

    def dark(y: int) -> bool:
        return gray.crop((0, y, width, y + 1)).getextrema()[1] < 16

    top = 0
    while top < limit_top and dark(top):
        top += 1
    bottom = height - 1
    while bottom > limit_bottom and dark(bottom):
        bottom -= 1
    if top or bottom < height - 1:
        img = img.crop((0, top, width, bottom + 1))

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    log(f"refined image {width}x{height} -> {img.size[0]}x{img.size[1]} "
        f"(bars removed: {top + (height - 1 - bottom)})")
    return buf.getvalue()


def generate_image(prompt: str, image_model: str) -> tuple[bytes, dict]:
    payload = {
        "model": image_model,
        "prompt": prompt,
        "n": 1,
        "aspect_ratio": ASPECT_RATIO,
    }
    resp = http_json(f"{OPENROUTER_BASE}/images", payload,
                     headers={"Authorization": f"Bearer {API_KEY}"})
    items = resp.get("data") or []
    if not items or "b64_json" not in items[0]:
        raise RuntimeError(f"image response missing data: {json.dumps(resp)[:300]}")
    raw = base64.b64decode(items[0]["b64_json"])
    return refine_image(raw), (resp.get("usage") or {})


def verify_image(image_bytes: bytes, w: dict) -> dict:
    b64 = base64.b64encode(image_bytes).decode()
    phase = time_of_day(w)
    cond = WMO.get(w["code"], "variable weather")
    # The prompt deliberately overrides time-of-day light when the sky is
    # overcast, foggy or precipitating (there is no golden-hour sun under dense
    # cloud), so the reviewer must judge weather, not the hour's light quality.
    day_night = "daytime" if w.get("is_day") else "night"
    content = [
        {
            "type": "text",
            "text": (
                "You are a strict image reviewer. Inspect the attached image "
                "and reply with ONLY a JSON object with boolean keys "
                "\"spelling_ok\", \"photorealistic\", \"matches_weather\", "
                "\"framing_ok\", and a short string \"notes\". spelling_ok is "
                "true only if the uppercase word \"ATLAS\" is legible in order "
                "as A-T-L-A-S and it is the only readable word in the image. "
                "Wildstyle is expected to be highly stylised: arrows, "
                "extensions, cross-outs, flourishes, interlocking bars, "
                "circuit traces and chrome accents are integral parts of the "
                "letters and do NOT count as other text, and stylised letter "
                "shapes are NOT a failure as long as a normal reader would "
                "read the piece as ATLAS rather than a different word. Faint, "
                "small or illegible background markings, weathering stains or "
                "abstract marks that cannot be read as words or letters are "
                "tolerated. spelling_ok is false only if the piece reads as a "
                "different word, letters are missing, substituted or extra, or "
                "there are separate additional READABLE words, tags, captions, "
                "logos or signatures besides the ATLAS piece. "
                "photorealistic is true "
                "only if the image looks like a real architectural photograph "
                "or visualization rather than a flat illustration, cartoon or "
                "painting. matches_weather is true only if the sky, "
                "precipitation, surface wetness and time of day are consistent "
                f"with: {cond}, temperature {w.get('temperature_f'):.0f}°F, "
                f"{day_night} around {phase}. Judge the weather itself: the "
                "exact colour, warmth or intensity of the light must NOT fail "
                "this check — an overcast or rainy sky gives flat grey light at "
                "any hour, and wet surfaces, mist, snow or dry pavement are the "
                "signals that matter. framing_ok is true "
                "only if the complete five-letter word ATLAS stays fully "
                "inside the frame with no letter clipped by an image edge, "
                "remains the dominant subject and stays legible from the "
                "chosen camera angle — the composition may be off-centre, "
                "diagonal, tilted or low-angle, and it does not need to be "
                "symmetrical or level. "
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


GALLERY_DIR = os.path.join(DATA_DIR, "gallery")
THUMB_WIDTH = 480


def _gallery_slug(meta: dict) -> str:
    stamp = str(meta.get("generated_at", "")).replace("-", "").replace(":", "")
    return f"{stamp}-{meta.get('wildstyle', 'unknown')}"


def _gallery_card(name: str, info: dict) -> str:
    """Render one gallery card: thumbnail, corrected meta, expandable prompt."""
    if info.get("generated_at_local"):
        when = f"{info['generated_at_local']} local"
    else:
        when = str(info.get("generated_at", ""))[:16].replace("T", " ") + " UTC"
    wx = info.get("weather") or {}

    def wxval(key: str, fallback_key: str | None = None):
        val = wx.get(key)
        if val is None and fallback_key:
            val = info.get(fallback_key)
        return val

    bits = [str(wxval("label", "label") or "unknown weather")]
    temp_f = wxval("temperature_f", "temperature_f")
    if temp_f is None:
        temp_c = wxval("temperature_c", "temperature_c")
        if isinstance(temp_c, (int, float)):
            temp_f = temp_c * 9 / 5 + 32
    if isinstance(temp_f, (int, float)):
        bits.append(f"{temp_f:.0f}°F")
    for key, fmt, label in (("wind_kmh", "{:.0f} km/h", "wind"),
                            ("humidity", "{:.0f}%", "RH"),
                            ("cloud_cover", "{:.0f}%", "clouds"),
                            ("precipitation_mm", "{:.1f} mm/h", "precip")):
        val = wxval(key)
        if isinstance(val, (int, float)):
            bits.append(f"{label} {fmt.format(val)}")
    if "is_day" in wx or "is_day" in info:
        bits.append("day" if wxval("is_day", "is_day") else "night")
    style = str(info.get("wildstyle", "")).split("-", 1)[-1].replace("-", " ")

    caption = (when + " · " + ", ".join(bits)
               + (f" · {style}" if style else ""))
    model_ids = []
    for key in ("image_model", "vision_model"):
        model_id = info.get(key)
        if model_id:
            model_ids.append(f"{key.replace('_', ' ')}: {model_id}")
    if model_ids:
        caption += " · " + " · ".join(model_ids)
    chips = []
    recipe = info.get("facets") or {}
    for facet in CATALOGS:
        entry_id = recipe.get(facet.id)
        entry = next((item for item in facet.entries if item.id == entry_id), None)
        if entry:
            chips.append(
                f'<a class="chip" href="catalog.html#{html.escape(facet.id + "-" + entry.id, quote=True)}">'
                f'{html.escape(facet.label)}: {html.escape(entry.label)}</a>')
        elif facet.id == "style" and info.get("wildstyle"):
            chips.append(f'<span class="chip">Style: {html.escape(style)}</span>')
    chips_html = '<nav class="chips">' + "".join(chips) + "</nav>" if chips else ""
    prompt_html = ""
    if info.get("prompt"):
        prompt_html = (
            "<details><summary>prompt</summary>"
            f"<pre>{html.escape(str(info['prompt']))}</pre></details>"
        )
    return (
        f'<figure class="card">'
        f'<a href="{html.escape(name, quote=True)}" target="_blank" rel="noopener noreferrer">'
        f'<img loading="lazy" src="thumbs/{html.escape(name, quote=True)}" '
        f'alt="Atlas background"></a>'
        f"<figcaption><span>{html.escape(caption)}</span>{chips_html}{prompt_html}"
        f"</figcaption></figure>"
    )


def _render_gallery_index() -> None:
    """Rewrite the static gallery page from the archived images."""
    groups = {}
    for name in os.listdir(GALLERY_DIR):
        if not name.endswith(".jpg"):
            continue
        base = name[:-4]
        sidecar = os.path.join(GALLERY_DIR, f"{base}.json")
        info = {}
        if os.path.exists(sidecar):
            with open(sidecar) as fh:
                info = json.load(fh)
        local_stamp = str(info.get("generated_at_local") or "")
        utc_stamp = str(info.get("generated_at") or "")
        group = "Unknown date"
        try:
            group = date.fromisoformat(local_stamp[:10]).isoformat()
        except ValueError:
            try:
                group = datetime.fromisoformat(
                    utc_stamp.replace("Z", "+00:00")
                ).date().isoformat()
            except ValueError:
                pass
        groups.setdefault(group, []).append((name, info))

    day_sections = []
    days = sorted([day for day in groups if day != "Unknown date"], reverse=True)
    if "Unknown date" in groups:
        days.append("Unknown date")
    for day in days:
        entries = sorted(groups[day], key=lambda item: item[0], reverse=True)
        day_sections.append(
            f'<h2>{html.escape(day)}</h2><section class="day">'
            + "".join(_gallery_card(name, info) for name, info in entries)
            + "</section>"
        )
    count = sum(len(entries) for entries in groups.values())

    _render_catalog_index()
    css = (
        "body{margin:0;background:#0b0d10;color:#cbd5e1;"
        "font-family:system-ui,sans-serif}"
        "h1{font-size:1.2rem;margin:1rem 1.2rem}"
        "h2{font-size:1rem;margin:1rem 1.2rem .5rem}"
        ".day{display:grid;grid-template-columns:repeat(auto-fill,"
        "minmax(260px,1fr));gap:.8rem;padding:0 1.2rem 2rem}"
        ".card{display:block;margin:0;text-decoration:none;color:inherit;"
        "background:#151a21;border-radius:.5rem;overflow:hidden}"
        ".card img{width:100%;height:auto;display:block}"
        ".card figcaption span{display:block;padding:.5rem .6rem;"
        "font-size:.72rem;color:#94a3b8}"
        ".card details{margin:.2rem .6rem .6rem}"
        ".card summary{cursor:pointer;font-size:.68rem;color:#7f96ab}"
        ".chips{display:flex;flex-wrap:wrap;gap:.3rem;padding:0 .6rem}"
        ".chip{font-size:.65rem;color:#93c5fd;background:#202a36;"
        "padding:.2rem .4rem;border-radius:.4rem;text-decoration:none}"
        ".card pre{white-space:pre-wrap;word-break:break-word;"
        "font-size:.62rem;line-height:1.35;color:#8aa0b4;"
        "max-height:14rem;overflow:auto;margin:.4rem 0 0}"
    )
    html_doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Atlas background gallery ({count})</title>"
        f"<style>{css}</style></head><body>"
        f"<h1>Atlas background gallery ({count})</h1>"
        f'<p><a href="catalog.html">Visual catalog</a></p>'
        f'<main>{"".join(day_sections)}</main></body></html>'
    )
    atomic_write(os.path.join(GALLERY_DIR, "index.html"), html_doc.encode())


def _render_catalog_index() -> None:
    sections = []
    for facet in CATALOGS:
        entries = "".join(
            f'<article id="{html.escape(facet.id + "-" + entry.id, quote=True)}">'
            f'<h3>{html.escape(entry.label)}</h3><p>{html.escape(entry.description)}</p></article>'
            for entry in facet.entries
        )
        sections.append(f'<section><h2>{html.escape(facet.label)}</h2>{entries}</section>')
    doc = ('<!doctype html><html lang="en"><meta charset="utf-8">'
           '<title>Atlas visual catalog</title><body><h1>Visual catalog</h1>'
           '<p><a href="index.html">Gallery</a></p>' + "".join(sections) + '</body></html>')
    atomic_write(os.path.join(GALLERY_DIR, "catalog.html"), doc.encode())


def archive_gallery(image: bytes, meta: dict) -> tuple[bool, str]:
    """Archive the accepted image and refresh the static gallery page.

    Non-fatal by design: the homepage background is already published when
    this runs, and a gallery problem must not fail the whole generation.
    """
    try:
        os.makedirs(os.path.join(GALLERY_DIR, "thumbs"), exist_ok=True)
        slug = _gallery_slug(meta)

        atomic_write(os.path.join(GALLERY_DIR, f"{slug}.jpg"), image)
        atomic_write(os.path.join(GALLERY_DIR, f"{slug}.json"),
                     json.dumps(meta, indent=2).encode())

        with Image.open(io.BytesIO(image)) as img:
            ratio = THUMB_WIDTH / img.width
            thumb = img.resize((THUMB_WIDTH, max(1, round(img.height * ratio))))
            buf = io.BytesIO()
            thumb.convert("RGB").save(buf, "JPEG", quality=80)
        atomic_write(os.path.join(GALLERY_DIR, "thumbs", f"{slug}.jpg"),
                     buf.getvalue())

        _render_gallery_index()
        return True, ""
    except Exception as err:  # noqa: BLE001 - archiving must not kill the run
        return False, f"{type(err).__name__}: {err}"


def main() -> int:
    if not API_KEY:
        log("OPENROUTER_API_KEY is not set")
        return 2
    config_error = validate_location_config(LAT, LON, PLACE, WEATHER_LABEL)
    if config_error:
        log(config_error)
        return 2

    os.makedirs(DATA_DIR, exist_ok=True)

    log(f"fetching weather for {PLACE} ({LAT},{LON})")
    weather = fetch_weather()
    log(f"conditions: {WMO.get(weather['code'], 'n/a')}, "
        f"{weather['temperature_f']:.0f}°F, day={weather['is_day']}")

    recipe = select_recipe()
    prompt = build_prompt(weather, recipe)
    image_model = select_image_model()
    log(f"generating image with {image_model}")
    image, usage = generate_image(prompt, image_model)
    log(f"generated {len(image)} bytes (cost={usage.get('cost')})")

    log(f"verifying image with {VISION_MODEL}")
    verdict = verify_image(image, weather)
    log(f"verdict: {json.dumps(verdict)}")

    if not (verdict.get("spelling_ok") and verdict.get("photorealistic")
            and verdict.get("matches_weather") and verdict.get("framing_ok")):
        log("verification failed; keeping the existing background")
        return 1

    atomic_write(IMAGE_PATH, image)
    # Local wall-clock time in the target place, derived from Open-Meteo's
    # UTC offset so no timezone database is needed.
    local_dt = datetime.now(timezone.utc) + timedelta(
        seconds=int(weather.get("utc_offset_seconds") or 0))
    meta = {
        "source": "openrouter",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_local": local_dt.strftime("%Y-%m-%d %H:%M"),
        "label": WMO.get(weather["code"], "weather"),
        "temperature_f": weather["temperature_f"],
        "temperature_c": weather["temperature_c"],
        "is_day": weather["is_day"],
        "wildstyle": recipe["style"].id,
        "facets": recipe_metadata(recipe),
        "image_model": image_model,
        "vision_model": VISION_MODEL,
        "place": PLACE,
        "weather_area": WEATHER_LABEL,
        "prompt": prompt,
        "weather": {
            "label": WMO.get(weather["code"], "weather"),
            "code": weather.get("code"),
            "temperature_f": weather.get("temperature_f"),
            "temperature_c": weather.get("temperature_c"),
            "apparent_f": weather.get("apparent_f"),
            "apparent_c": weather.get("apparent_c"),
            "humidity": weather.get("humidity"),
            "precipitation_mm": weather.get("precipitation_mm"),
            "cloud_cover": weather.get("cloud_cover"),
            "wind_kmh": weather.get("wind_kmh"),
            "is_day": weather.get("is_day"),
            "local_hour": weather.get("local_hour"),
            "observed_at": weather.get("observed_at"),
        },
        "verdict": verdict,
    }
    gallery_ok, gallery_note = archive_gallery(image, meta)
    meta["gallery_ok"] = gallery_ok
    if gallery_note:
        meta["gallery_note"] = gallery_note
        log(f"gallery archive failed: {gallery_note}")
    else:
        log("archived image to the gallery")
    atomic_write(META_PATH, json.dumps(meta, indent=2).encode())
    log(f"published new background to {IMAGE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
