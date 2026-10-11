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
import io
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from PIL import Image

OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
WEATHER_URL = os.environ.get(
    "WEATHER_URL", "https://api.open-meteo.com/v1/forecast"
)

LAT = os.environ.get("WEATHER_LAT", "<latitude>")
LON = os.environ.get("WEATHER_LON", "<longitude>")
PLACE = os.environ.get("WEATHER_PLACE", "<configured-place>")

IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "google/gemini-2.5-flash-image")
VISION_MODEL = os.environ.get("VISION_MODEL", "google/gemini-2.5-flash")
# The artwork is a balanced 3:2 landscape; the API request must match the
# aspect ratio named in the prompt.
ASPECT_RATIO = os.environ.get("ASPECT_RATIO", "3:2")

# Wildstyle treatments, chosen at random for every generation. Weather talk in
# these fragments is intentionally absent: the scene weather comes from the
# live Open-Meteo conditions.
WILDSTYLES = [
    ("W1-barely-technical",
     "The wall is a clean neon/UV-lit surface and the only future-tech is a "
     "couple of glowing circuit-trace accents running inside the letterforms."),
    ("W2-neon-back-alley",
     "Chrome-tinted wildstyle in a neon-lit back-alley composition: blurred "
     "holographic signage glows far behind the piece and reflections play "
     "across the paint, while the piece itself stays clean."),
    ("W3-half-lit-decay",
     "Half of the piece glows with healthy neon while the other half flickers "
     "or is burnt out; the surrounding mega-city wall carries peeling paint, "
     "dangling cables and steam vents."),
    ("W4-post-apocalyptic",
     "The neon is weathered, scratched and scorched, fighting to stay lit on "
     "a ruined wall of cracked concrete and exposed rebar, with drifting ash "
     "and a single working drone light."),
]


def pick_wildstyle() -> tuple[str, str]:
    return random.choice(WILDSTYLES)


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


def build_prompt(w: dict, style_txt: str, camera_txt: str) -> str:
    weather = weather_elements(w)
    light = lighting(w)
    return (
        "Create an extraordinary, cinematic architectural photograph whose main "
        "subject is a monumental piece of wildstyle graffiti spelling exactly "
        "the word \"ATLAS\", painted across an immense physical surface or "
        "fixture within a dramatic brutalist architectural environment. "
        "The graffiti is the hero of the image; the surrounding architecture "
        "and supporting structures provide context, scale and atmosphere, "
        "never becoming part of the lettering. "

        "CORE CONCEPT: the five letters \"ATLAS\" form one huge, visually "
        "commanding graffiti masterpiece that dominates the composition as "
        "a single continuous piece. The graffiti may appear on a monumental "
        "concrete wall, oversized industrial sign, elevated billboard, "
        "freestanding architectural panel, massive metal structure, "
        "retaining wall, suspended signage or another physically believable "
        "urban fixture. The lettering must remain authentic painted graffiti, "
        "not buildings, megastructures or architecture-shaped letters. "
        "The supporting surface should feel naturally integrated into the "
        "environment, with realistic structural connections, mounting "
        "hardware and physical construction where appropriate. "

        "TYPOGRAPHY AND LETTEROGRAPHY (wildstyle graffiti): full wildstyle "
        "construction with interlocking letters, aggressive arrows and "
        "extensions, overlapping bars, sharp angular cuts and folds, kinetic "
        "highlights and hard painted 3D block shadows; an authentic, complex "
        "piece by a world-class graffiti writer in which every letter remains "
        "identifiable and the word unmistakably reads ATLAS. The lettering "
        "should have monumental presence, controlled drips and overspray, "
        "purposeful asymmetry and subtle hand-painted imperfections. "
        "The primary letter skeletons must remain structurally recognizable "
        "despite their intricate wildstyle connections and extensions. "
        "The lettering must look physically applied to its supporting "
        "surface using spray paint and markers, never constructed from "
        "architectural elements. "

        f"STYLE TREATMENT: {style_txt} "

        "BRUTALIST SETTING: place the graffiti within an expansive brutalist "
        "architectural complex of colossal raw-concrete towers, monolithic "
        "retaining walls, vast brutalist plazas, cantilevered platforms, "
        "massive staircases, monumental pillars, elevated walkways and "
        "dramatic industrial infrastructure. Draw inspiration from Soviet-era "
        "megastructures, Japanese Metabolist architecture and speculative "
        "architectural photography, creating an environment that feels "
        "ancient, futuristic, intimidating and strangely sacred. "
        "The graffiti-bearing surface or fixture is the primary focal "
        "element, while the surrounding architecture frames it, establishes "
        "scale and contributes to the visual atmosphere. The graffiti may "
        "be mounted on, suspended from, integrated into or positioned "
        "independently within the architectural environment, provided "
        "its physical placement remains believable. "

        "IMMENSE SCALE AND PERSPECTIVE: the graffiti is monumental, several "
        "storeys tall or otherwise dramatically oversized, dwarfing nearby "
        "people and architectural details. Include several extremely tiny "
        "human silhouettes near the artwork or within the surrounding "
        "environment to communicate its immense scale. Use expressive but "
        "physically believable architectural photography, allowing low "
        "street-level camera positions, upward-looking perspectives, "
        "three-quarter views, diagonal framing, off-axis compositions "
        "and intentional Dutch angles. The camera may look dramatically "
        "upward at the artwork from ground level, creating a powerful "
        "sense of height, depth and architectural presence. Camera "
        "rotation and dynamic viewpoints are encouraged when they "
        "strengthen the composition. Use natural rectilinear photographic "
        "optics, generally equivalent to a 35mm to 50mm full-frame lens, "
        "with realistic perspective and controlled foreshortening. "
        "Natural perspective convergence is permitted when physically "
        "appropriate, but avoid fisheye effects, ultra-wide-angle "
        "stretching, warped geometry, curved straight lines, exaggerated "
        "lens distortion and unnatural deformation of the graffiti. "
        "The artwork must retain its recognizable letterforms regardless "
        "of the camera position or viewing angle. "

        f"{camera_txt} "

        "MATERIALS AND TEXTURES: highly realistic physical surfaces "
        "appropriate to the selected graffiti-bearing structure, including "
        "weathered board-formed concrete, painted industrial metal, "
        "oxidized steel, aged signage, distressed architectural panels, "
        "industrial cladding or other believable urban materials. "
        "Show authentic surface imperfections such as concrete grain, "
        "construction seams, exposed aggregate, erosion, rust, dark "
        "water stains, mineral deposits, chipped edges, scratches, "
        "fading and accumulated environmental wear where appropriate. "
        "The graffiti displays layered spray-paint, visible pigment "
        "texture, subtle ageing, controlled drips, realistic paint "
        "coverage and hard-edged overspray, physically adhering to "
        "the underlying surface. Surface texture should remain visible "
        "through the paint where appropriate, reinforcing the appearance "
        "of genuine graffiti rather than digitally composited lettering. "

        "COLOR PALETTE: restrained and cinematic overall, charcoal black, "
        "graphite grey, cold concrete silver, desaturated slate and muted "
        "industrial ivory, with the graffiti carrying the boldest colour "
        "contrast as vivid but controlled paint. Incorporate subtle "
        "oxidized orange, weathered metal tones or faded safety red "
        "accents within the architecture and industrial fixtures. "
        "Allow the selected graffiti style treatment to influence "
        "the artwork's paint colours while keeping the surrounding "
        "environment visually cohesive and appropriately restrained. "
        "Avoid excessive saturation across the entire image and let "
        "the visual impact come from the letterforms, monumental scale, "
        "material realism, architectural atmosphere and dramatic light. "

        f"LOCAL CONDITIONS at <configured-weather-area>, rendered faithfully into the scene: "
        f"{weather}. "

        f"LIGHTING AND ATMOSPHERE: {light} "

        "COMPOSITION AND ART DIRECTION: standard landscape composition "
        "with a balanced 3:2 aspect ratio, filling the entire frame "
        "edge to edge without panoramic cropping, letterboxing, black "
        "bars, borders or vignette. The graffiti word ATLAS remains "
        "the unmistakable primary subject, clearly visible in its "
        "entirety with all five letters recognizable. Allow creative "
        "camera positioning, dramatic diagonal compositions, low-angle "
        "upward views, off-axis framing and intentional Dutch angles "
        "when they strengthen the image. The graffiti may occupy a "
        "large central or dynamically positioned area of the frame, "
        "with the surrounding brutalist environment providing depth, "
        "negative space and architectural context. The composition "
        "does not need to be symmetrical, perfectly level or strictly "
        "frontal. Preserve realistic proportions, credible physical "
        "geometry and natural photographic perspective while allowing "
        "expressive framing and dramatic spatial relationships. "
        "Ensure that the entire word remains within the image boundaries "
        "without clipping any essential letterforms. The supporting "
        "surface may be viewed frontally, diagonally or from below, "
        "provided the graffiti remains visually dominant and legible. "

        "RENDERING AND FINISH: photorealistic architectural photography "
        "combined with high-end graffiti lettering craft, cinematic "
        "environmental realism, ultra-detailed material rendering, "
        "physically based lighting, realistic atmospheric perspective, "
        "accurate physical geometry and sophisticated editorial art "
        "direction. Emphasize the appearance of a professionally "
        "captured real-world photograph with expressive camera placement, "
        "natural lens characteristics, realistic optical behavior, "
        "authentic surface interaction and no artificial geometric "
        "warping. Maintain photographic credibility while achieving "
        "an extraordinary sense of scale, environmental immersion "
        "and visual originality. "

        "CRITICAL REQUIREMENTS: the image must contain exactly five letters "
        "spelling ATLAS, in the correct order A, T, L, A, S, in uppercase, "
        "and all five letters must remain clearly recognizable. "
        "The lettering is authentic wildstyle graffiti paint applied "
        "to a believable physical surface or fixture, NOT architecture: "
        "do not turn the letters into buildings, towers, megastructures "
        "or sculptural architectural forms. The graffiti is not required "
        "to be on a concrete wall and may occupy any suitable believable "
        "urban surface or structural fixture. Camera angles may be "
        "dramatic, tilted, diagonal or low to the ground, but must "
        "maintain natural photographic optics without fisheye distortion "
        "or artificial stretching. No panoramic framing, no extreme "
        "wide-angle distortion, no additional words, no captions, "
        "no logos, no watermarks, no decorative borders, no black "
        "bars, no letterboxing and no other text of any kind. "
        "The artwork fills the whole canvas."
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


def generate_image(prompt: str) -> tuple[bytes, dict]:
    payload = {
        "model": IMAGE_MODEL,
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
    content = [
        {
            "type": "text",
            "text": (
                "You are a strict image reviewer. Inspect the attached image "
                "and reply with ONLY a JSON object with boolean keys "
                "\"spelling_ok\", \"photorealistic\", \"matches_weather\", "
                "\"framing_ok\", and a short string \"notes\". spelling_ok is "
                "true only if the uppercase word \"ATLAS\" appears exactly "
                "once, spelled A-T-L-A-S in that order, and it is the only "
                "word in the image. Wildstyle elements that are integral "
                "parts of the letters themselves — arrows, extensions, "
                "cross-outs, flourishes, circuit traces or chrome accents — "
                "do NOT count as other text. spelling_ok is false only if "
                "there are separate additional words, letters, tags, "
                "captions, logos or signatures besides the ATLAS piece. "
                "photorealistic is true "
                "only if the image looks like a real architectural photograph "
                "or visualization rather than a flat illustration, cartoon or "
                "painting. matches_weather is true only if the scene, weather "
                f"effects and lighting are consistent with: {cond}, temperature "
                f"{w.get('temperature_c')}°C, {phase}. framing_ok is true "
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


def _render_gallery_index() -> None:
    """Rewrite the static gallery page from the archived images."""
    entries = []
    for name in sorted(os.listdir(GALLERY_DIR), reverse=True):
        if not name.endswith(".jpg"):
            continue
        sidecar = os.path.join(GALLERY_DIR, f"{name}.json")
        info = {}
        if os.path.exists(sidecar):
            with open(sidecar) as fh:
                info = json.load(fh)
        entries.append((name, info))

    items = []
    for name, info in entries:
        when = str(info.get("generated_at", ""))[:16].replace("T", " ")
        label = info.get("label", "unknown weather")
        style = str(info.get("wildstyle", "")).split("-", 1)[-1].replace("-", " ")
        temp = info.get("temperature_c")
        caption = (f"{when} UTC · {label}"
                   + (f", {temp:.0f}°C" if isinstance(temp, (int, float)) else "")
                   + (f" · {style}" if style else ""))
        items.append(
            f'<a class="card" href="{name}">'
            f'<img loading="lazy" src="thumbs/{name}" alt="Atlas background">'
            f"<span>{caption}</span></a>"
        )

    css = (
        "body{margin:0;background:#0b0d10;color:#cbd5e1;"
        "font-family:system-ui,sans-serif}"
        "h1{font-size:1.2rem;margin:1rem 1.2rem}"
        "main{display:grid;grid-template-columns:repeat(auto-fill,"
        "minmax(260px,1fr));gap:.8rem;padding:0 1.2rem 2rem}"
        ".card{display:block;text-decoration:none;color:inherit;"
        "background:#151a21;border-radius:.5rem;overflow:hidden}"
        ".card img{width:100%;height:auto;display:block}"
        ".card span{display:block;padding:.5rem .6rem;font-size:.75rem;"
        "color:#94a3b8}"
    )
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Atlas background gallery ({len(entries)})</title>"
        f"<style>{css}</style></head><body>"
        f"<h1>Atlas background gallery ({len(entries)})</h1>"
        f'<main>{"".join(items)}</main></body></html>'
    )
    atomic_write(os.path.join(GALLERY_DIR, "index.html"), html.encode())


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

    os.makedirs(DATA_DIR, exist_ok=True)

    log(f"fetching weather for {PLACE} ({LAT},{LON})")
    weather = fetch_weather()
    log(f"conditions: {WMO.get(weather['code'], 'n/a')}, "
        f"{weather['temperature_c']}°C, day={weather['is_day']}")

    style_id, style_txt = pick_wildstyle()
    log(f"wildstyle treatment: {style_id}")
    camera_facets, camera_txt = pick_camera()
    log(f"camera: {camera_facets['height']}, {camera_facets['pitch']}, "
        f"{camera_facets['framing']}, {camera_facets['roll']}, "
        f"{camera_facets['focus']}")
    prompt = build_prompt(weather, style_txt, camera_txt)
    log(f"generating image with {IMAGE_MODEL}")
    image, usage = generate_image(prompt)
    log(f"generated {len(image)} bytes (cost={usage.get('cost')})")

    log(f"verifying image with {VISION_MODEL}")
    verdict = verify_image(image, weather)
    log(f"verdict: {json.dumps(verdict)}")

    if not (verdict.get("spelling_ok") and verdict.get("photorealistic")
            and verdict.get("matches_weather") and verdict.get("framing_ok")):
        log("verification failed; keeping the existing background")
        return 1

    atomic_write(IMAGE_PATH, image)
    meta = {
        "source": "openrouter",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": WMO.get(weather["code"], "weather"),
        "temperature_c": weather["temperature_c"],
        "is_day": weather["is_day"],
        "wildstyle": style_id,
        "camera": camera_facets,
        "image_model": IMAGE_MODEL,
        "vision_model": VISION_MODEL,
        "place": PLACE,
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
