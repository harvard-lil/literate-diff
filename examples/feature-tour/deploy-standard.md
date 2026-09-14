# Deploy standard

Every service ships one image per commit. CI builds it once, runs the suite
against a test stage layered on top of it, and publishes it tagged with the
commit. A deploy promotes an image the suite has passed; it never builds.

## Registry

Commit tags are immutable. Only the per-tier moving tags may be repointed.
Deployed images expire on their own rule, more slowly than build candidates,
so a rollback target is still there when it is needed.

## Identity

A deploy job assumes a role through the platform's OIDC provider. The role's
trust policy names one deployment environment, not a branch pattern. No
long-lived cloud credentials are stored as repository secrets.

## Settings

An image chooses its settings at runtime from the environment. Nothing is
copied into the image at build time that would make it tier-specific.
