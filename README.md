# Atlas background generator

An open-source generator for a self-hosted Homepage background. It fetches current weather from Open-Meteo, creates a photorealistic graffiti scene with an OpenRouter image model, verifies the result with an OpenRouter vision model, and publishes only images that pass. Each accepted image can also be archived with weather metadata and its generation prompt.

The code has no built-in location. Set `WEATHER_LAT`, `WEATHER_LON`, `WEATHER_PLACE`, and `WEATHER_LABEL` for your deployment. Avoid publishing precise home coordinates in a public configuration repository.

## Configure and run locally

Requirements: Python 3.12+, Docker (optional), and an OpenRouter API key with access to the configured image and vision models.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your own location and `OPENROUTER_API_KEY`, then run:

```sh
set -a
. ./.env
set +a
python3 generator/generate.py
```

The latest accepted background, metadata, and historical gallery are written under `DATA_DIR` (default `/data`). Set `DATA_DIR=./data` for a local run. Failed generation or verification leaves the previous background untouched.

Each image uses an independently randomized visual recipe spanning graffiti style, placement, lens, composition, environment, paint treatment, lighting, and palette. The archived metadata records stable facet IDs and the full prompt. Gallery cards link recipe chips to the generated `catalog.html` index, which documents every available option.

Run tests with:

```sh
python3 -m unittest discover -s tests
```

## Prompt generator

Use the [ATLAS prompt generator](https://211lab.github.io/atlas-landing/) to inspect and toggle the visual options, then generate and copy a randomized plain-text prompt for your vLLM. It runs entirely in the browser and does not call vLLM, OpenRouter, or any image API.

## Container

```sh
set -a
. ./.env
set +a
docker build -t atlas-background .
docker run --rm \
  --env OPENROUTER_API_KEY --env WEATHER_LAT --env WEATHER_LON \
  --env WEATHER_PLACE --env WEATHER_LABEL \
  --env IMAGE_MODEL --env VISION_MODEL --env ASPECT_RATIO \
  --env DATA_DIR=/data \
  -v "$PWD/data:/data" atlas-background
```

## Deployment and CI

The GitHub Actions workflow runs tests, a secret scan, and a container build without publishing artifacts or requiring credentials. The Gitea workflow is an optional deployment integration; configure its action secrets as described in [CONTRIBUTING.md](CONTRIBUTING.md). It builds and pushes the image and promotes its release tag to the configured GitOps repository.

The public workflow does not contain deployment credentials or a cluster-specific location. Deployment-specific values belong in your private configuration or runtime secret store.

## Models and costs

Each generator run randomly selects one image model from `qwen/qwen-image-3`, `meta/muse-image`, `krea/krea-2-medium-turbo`, `bytedance-seed/seedream-5-0-flash`, `tencent/hy-image-v3.5-preview`, and `google/gemini-3.1-flash-lite-image`. Set `IMAGE_MODEL` to override that selection. The verifier remains configurable with `VISION_MODEL`. Each accepted attempt makes one image-generation and one vision request; rejected attempts are retried by the Kubernetes Job according to its policy. API costs depend on the provider's current pricing and are reported when the response includes usage data.

## License

Code and included assets are provided under the MIT License; see [LICENSE](LICENSE).
