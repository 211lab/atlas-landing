# Contributing

1. Fork the repository and create a focused branch.
2. Keep deployment-specific values, credentials, and exact personal locations out of source and fixtures.
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

## Public mirror history

The public GitHub history is privacy-filtered from the deployment source, so commit IDs intentionally differ. Never force-push the raw deployment repository or its tags directly to GitHub; that would restore private configuration from older commits. Publish updates only from a full-history export processed with the maintainer-held redaction rules, then scan all branches and tags before pushing.
