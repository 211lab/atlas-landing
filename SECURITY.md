# Security Policy

## Reporting a vulnerability

Please report security issues through GitHub's private vulnerability reporting for this repository. Do not open a public issue with credentials, private URLs, personal location data, or exploit details.

## Secret handling

Never commit API keys, registry credentials, kubeconfigs, generated runtime metadata, or deployment-specific location data. Use environment variables locally and your platform's encrypted secret store in deployment. Revoke and rotate any credential that may have been exposed.
