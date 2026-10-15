# Contributing

1. Fork the repository and create a focused branch.
2. Do not commit credentials or generated runtime metadata.
3. Run `python3 -m unittest discover -s tests`, `python3 -m py_compile generator/generate.py`, and `docker build -t atlas-background .` before opening a pull request.
4. Describe behavior changes and include test evidence. Do not include generated images, runtime metadata, or API credentials.

## Optional Gitea deployment workflow

The `.gitea/workflows/build.yaml` workflow builds and pushes an image and, for version tags, promotes the tag in a GitOps repository. To enable it, create these repository Actions secrets in your own Gitea instance:

- `FORGE_HTTP_HOST`: internal forge host and port, without scheme, e.g. `gitea.example:3000`.
- `APP_REPO_PATH`: owner/repository path for this checkout.
- `GITOPS_REPO_PATH`: owner/repository path for the GitOps checkout.
- `IMAGE_REGISTRY`: registry host.
- `IMAGE_PATH`: image namespace and name.
- `GITOPS_VALUES_PATH`: relative path to the values file whose top-level `tag` is promoted.
- `REGISTRY_USER` and `REGISTRY_TOKEN`: credentials allowed to push the image and update the GitOps repository.

The GitHub workflow performs validation only and does not need these deployment secrets.
