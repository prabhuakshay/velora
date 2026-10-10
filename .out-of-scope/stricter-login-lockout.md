# Stricter Login Lockout

Velora locks out a username and IP address pair after repeated failed logins. It does not add a per-username or per-IP lockout.

## Why this is out of scope

Velora has one user (ADR 0001). A per-username lockout would let anyone lock that user out from any address, and a per-IP lockout can lock them out of their own address after someone else's failures. The pair (`AXES_LOCKOUT_PARAMETERS` in `config/settings.py`) avoids both.

A botnet rotating IPs gets five tries per IP and username, but `LOGIN_RATE_LIMIT` throttles requests per IP, and for one user with a strong password the remaining risk is small.

## Prior requests

- #100: "Decide: lockout parameters, healthz cost, login IP display" (also decided: leave `/healthz/` uncached and keep "Your IP address" on the login page)
