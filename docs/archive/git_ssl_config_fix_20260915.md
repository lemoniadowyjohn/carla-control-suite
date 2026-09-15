# Git SSL Configuration Fix (2026-09-15)

## Issue
Git operations (e.g., `git clone`) against `github.com` were failing due to an SSL certificate verification error. The system-wide Git configuration was pinned to `http.sslbackend=openssl` and referenced a stale CA bundle from September 2024.

## Diagnosis
- `http.sslbackend` was set to `openssl`.
- The bundled CA file was out of date, leading to verification failures for modern certificates.

## Resolution
The Git SSL backend was changed from `openssl` to `schannel`. This switch allows Git to use the native Windows Certificate Store, which is managed and updated by the operating system, eliminating the need for a manually maintained CA bundle file.

## Changes Applied
- Set global Git configuration: `git config --global http.sslbackend schannel`
- Removed global CA bundle reference: `git config --global --unset http.sslcainfo`

## Verification
A test clone of a public repository (`github/helloworld`) was successfully performed without any `-c http.sslbackend=schannel` overrides.
