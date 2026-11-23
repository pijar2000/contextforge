# Log Retention Specification

## Scope

This specification defines how long each class of log data is stored and how it is protected.

## Retention periods

- Debug logs are kept for 7 days and then deleted.
- Application logs are kept for 30 days in hot storage and for 365 days in the cold archive.
- Audit logs are kept for 7 years and cannot be modified or deleted before that date.
- Security event logs are kept for 2 years.

## Personal data

Logs that contain personal data must be pseudonymised after 30 days. The pseudonymisation job runs
nightly and replaces user identifiers with salted hashes. The salt is rotated every quarter.

## Access

Hot storage is readable by the engineering group. The cold archive requires an approved access
request and is read-only. Audit logs can only be read by administrators and the compliance team.
