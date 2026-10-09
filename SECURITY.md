# Security

## Secrets

- tastytrade credentials (client secret, refresh token) live only in `.env` at the repo root, or
  in the process environment. `.env`, `config/config.toml` and `data/` are gitignored, excluded
  from the Docker build context, and never baked into the image.
- The settings object never prints its secrets, even in a traceback.
- CI and the pre-commit hooks scan for committed secrets (gitleaks, detect-private-key).

## Brokerage access

The tastytrade OAuth application is created with the read scope only, so its credentials cannot
place orders. The code has no order-entry path, and none may be added. A failed sign-in is never
retried automatically, which avoids tastytrade's IP block after repeated failures.

## Sign-in

The app's sign-in page is a mock: nothing is verified, sent or stored. Do not expose the
dashboard to the public internet; run it on localhost or a private network.

## Reporting a vulnerability

Open a private report through GitHub Security Advisories on this repository, or email the
maintainer listed on the GitHub profile. Do not open a public issue for a vulnerability.

In scope: credential handling, the Docker image, dependency vulnerabilities, anything that could
send data or credentials to a third party. Out of scope: the mock sign-in (documented as not
real), denial of service against a local instance, and vulnerabilities in tastytrade's or
Yahoo's own services.
