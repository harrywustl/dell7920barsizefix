# Public and private data

[简体中文](PRIVACY.zh-CN.md)

| Location | Suitable content |
|---|---|
| Public repository | Reusable scripts and guides, model/BIOS references, anonymized examples and screenshots |
| Your own private repository | Raw logs/screenshots, local profiles, hardware mappings, connection details and review records |
| Offline USB / controlled NAS | ESP, firmware-variable and configuration backups; complete recovery USB package |

Keep private keys, passwords, tokens and recovery keys out of **all Git repositories**. Keep IP/MAC addresses, account names, serials, device/partition identifiers and personal paths private. Shared firmware GUIDs and release hashes may be published when needed for verification.

Before publishing, users and AI agents must:

1. Use placeholders and reusable instructions. Keep conversation history, personal checklists, screenshot counts, timings and audit receipts in the private repository.
2. Inspect screenshot pixels and metadata; scan text for identifiers and secrets. Automated checks supplement visual review.
3. Review staged files, diffs and every commit being pushed. Deleting a file from the latest version does not remove it from older commits.

```sh
python3 -B scripts/privacy_check.py .
# Optional private JSON files: a list of literal strings and a path-to-SHA256 map.
python3 -B scripts/privacy_check.py . \
  --denylist "$PRIVATE_DENYLIST" --image-allowlist "$PRIVATE_IMAGE_ALLOWLIST"
```

A passing scan is not a publication approval. Store large recovery images outside Git and restrict access to archives containing private configuration.
