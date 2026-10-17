# Deploy

## GHCR package (one-time step)

CI publishes the image to `ghcr.io/semaputnik/taler-bot` (tags `latest` and `sha-<short sha>`)
on every green push to `main`. A package created by CI is private at first, so the server could
not pull it without a token. After the first successful `publish` job, make it public once:

GitHub profile, Packages, `taler-bot`, Package settings, Danger Zone, Change visibility, Public.

Check it from a machine that is not logged in to GHCR: `docker pull ghcr.io/semaputnik/taler-bot:latest`.
