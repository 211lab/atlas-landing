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
        "local_hour": int(str(cur.get("time", "")).split("T")[-1].split(":")[0] or 0),
        "cloud_cover": cur.get("cloud_cover"),
        "precipitation_mm": cur.get("precipitation"),
        "humidity": cur.get("relative_humidity_2m"),
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

    parts = [
        f"It is {phase} in {PLACE}",
        f"the sky shows {sky}",
        f"around {w.get('temperature_c')}°C",
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


def build_prompt(w: dict) -> str:
    weather = weather_elements(w)
    light = lighting(w)
    return (
        "Create an extraordinary, ultra-wide cinematic typographic artwork "
        "featuring the exact word \"ATLAS\" in an intensely stylized, "
        "experimental graffiti letterography style, fused with colossal "
        "brutalist architecture, monumental sculptural typography and an "
        "overwhelming sense of architectural scale. "
        "CORE CONCEPT: the word \"ATLAS\" is not simply written on a surface; "
        "the letters themselves are immense architectural megastructures, "
        "towering like ancient concrete monuments, futuristic brutalist "
        "skyscrapers and impossible urban sculptures. Each letter is "
        "constructed from massive interlocking slabs of raw concrete, angular "
        "geometric volumes, cantilevered structures, deep architectural "
        "recesses, exposed structural beams and intricately connected "
        "three-dimensional graffiti forms. The five letters form one unified, "
        "incredibly wide, visually commanding composition stretching "
        "horizontally across an immense architectural landscape, and the word "
        "must read clearly as ATLAS while retaining the sophisticated "
        "complexity of experimental graffiti lettering. "
        "TYPOGRAPHY AND LETTEROGRAPHY: an extremely advanced fusion of "
        "wildstyle graffiti, architectural lettering, abstract calligraphic "
        "geometry, experimental typographic sculpture and brutalist graphic "
        "design. Exceptionally wide, heavily extended proportions with "
        "monumental horizontal presence; aggressive angular extensions, "
        "dramatic overlapping strokes, geometric interlocking shapes and "
        "unconventional negative spaces; massive extruded three-dimensional "
        "letter structures with extraordinary architectural depth; intricate "
        "graffiti-inspired connections between the letters forming one "
        "continuous sculptural installation; razor-sharp edges contrasting "
        "with enormous rounded concrete surfaces and sweeping structural "
        "curves; dynamic variations in stroke thickness, complex internal "
        "cutouts, recessed channels and deep shadow-filled voids; subtle "
        "hand-designed graffiti imperfections; strong visual rhythm, "
        "purposeful asymmetry, architectural tension and a distinctive custom "
        "lettering identity, as if designed by an experimental graffiti master "
        "collaborating with a visionary brutalist architect. "
        "BRUTALIST ARCHITECTURAL ENVIRONMENT: place the enormous ATLAS letter "
        "sculpture within an expansive brutalist architectural complex of "
        "colossal concrete towers, monolithic retaining walls, impossible "
        "cantilevered platforms, massive staircases, monumental pillars, "
        "elevated pedestrian bridges, deeply recessed openings and vast "
        "geometric planes, inspired by Soviet-era megastructures, Japanese "
        "Metabolist architecture, experimental concrete monuments and "
        "speculative architectural photography. The architecture should feel "
        "ancient, futuristic, intimidating and strangely sacred, and the "
        "letters appear to be load-bearing structures rather than decorative "
        "objects. "
        "IMMENSE SCALE AND PERSPECTIVE: an almost incomprehensible sense of "
        "size; the ATLAS sculpture appears hundreds of metres tall and "
        "kilometres wide, dwarfing every surrounding structure, with several "
        "extremely tiny human silhouettes standing near the base of the "
        "letters and miniature staircases, distant walkways and small doorways "
        "for scale. Use an ultra-wide, low-angle cinematic perspective with a "
        "20mm architectural lens, the viewer near ground level looking "
        "slightly upward, with dramatic vanishing points, extraordinary depth, "
        "overwhelming vertical mass and an immense panoramic horizontal "
        "composition, like an entire city built in the shape of a word. "
        "MATERIALS AND TEXTURES: predominantly raw, weathered, board-formed "
        "concrete with highly realistic surface imperfections including "
        "concrete grain, construction seams, exposed aggregate, erosion, dark "
        "water stains, mineral deposits, chipped edges and fine architectural "
        "weathering, plus occasional oxidized steel inserts and dark metallic "
        "structural joints, so that every letter feels physically constructed "
        "and impossibly heavy. "
        "COLOR PALETTE: restrained and cinematic, charcoal black, graphite "
        "grey, cold concrete silver, desaturated slate, deep shadow tones and "
        "muted industrial ivory, with subtle accents of oxidized orange or "
        "faded safety red in selected recesses; avoid excessive saturation and "
        "let the impact come from sculptural form, monumental scale, material "
        "realism and dramatic light. "
        f"WEATHER AND TIME OF DAY, rendered faithfully into the scene: "
        f"{weather}. "
        f"LIGHTING AND ATMOSPHERE: {light} "
        "COMPOSITION AND ART DIRECTION: extreme panoramic landscape "
        "composition that fills the entire 16:9 frame edge to edge, with no "
        "letterboxing, no black bars, no borders and no vignette. The word "
        "ATLAS dominates the central 80 percent of the frame, the five letters "
        "forming one continuous horizontal architectural silhouette, "
        "horizontally centred with generous breathing room at both ends and "
        "dramatic open sky above. Balance typographic readability with dense "
        "architectural complexity, with strong visual hierarchy, extraordinary "
        "negative space and intentional geometric relationships; every "
        "architectural detail reinforces the overall letterforms. "
        "RENDERING AND FINISH: photorealistic architectural visualization "
        "combined with high-end experimental typography, cinematic "
        "environmental concept art, ultra-detailed material rendering, "
        "physically based lighting, realistic atmospheric perspective, "
        "impeccable geometry and sophisticated editorial art direction, "
        "architecturally plausible yet conceptually impossible, powerful, "
        "immersive and unmistakably original. "
        "CRITICAL REQUIREMENTS: the image must contain exactly five letters "
        "spelling ATLAS, in the correct order A, T, L, A, S, in uppercase, and "
        "all five letters must remain recognizable despite the elaborate "
        "graffiti construction. No additional words, no captions, no logos, no "
        "watermarks, no decorative borders, no black bars, no letterboxing and "
        "no other text of any kind. The artwork fills the whole canvas."
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
    phase = time_of_day(w)
    cond = WMO.get(w["code"], "variable weather")
    content = [
        {
            "type": "text",
            "text": (
                "You are a strict image reviewer. Inspect the attached image "
                "and reply with ONLY a JSON object with boolean keys "
                "\"spelling_ok\", \"photorealistic\", \"matches_weather\", "
                "\"centered_ok\", and a short string \"notes\". spelling_ok is "
                "true only if the uppercase word \"ATLAS\" appears exactly "
                "once, spelled A-T-L-A-S in that order, and no other text, "
                "lettering, captions or logos appear. photorealistic is true "
                "only if the image looks like a real architectural photograph "
                "or visualization rather than a flat illustration, cartoon or "
                "painting. matches_weather is true only if the scene, weather "
                f"effects and lighting are consistent with: {cond}, temperature "
                f"{w.get('temperature_c')}°C, {phase}. centered_ok is true "
                "only if the complete five-letter word ATLAS is horizontally "
                "centred, fully visible with clear breathing room at both "
                "sides, no letter cut off by the frame edge, and open space "
                "above it. "
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
            and verdict.get("matches_weather") and verdict.get("centered_ok")):
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
