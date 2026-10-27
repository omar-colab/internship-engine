# Chrome Web Store publishing notes

GitHub Releases can distribute the extension ZIP for manual **Load unpacked** installation. Chrome requires extensions intended for ordinary one-click installation to be published through the Chrome Web Store. This repository has no published store listing yet.

## Draft listing

- **Name:** Internship Engine
- **Short description:** Save internship postings and prepare application fields from your web-app or laptop profile. You review and submit every application.
- **Single purpose:** Help a user save internship postings and prepare supported application fields using a profile from the hosted web app or the user's local laptop engine. The user reviews and submits each application.
- **Support URL:** `https://github.com/omar-colab/internship-engine/issues`
- **Privacy policy URL:** `https://omar-colab.github.io/internship-engine/privacy.html`
- **Category:** Productivity

### Data and permissions disclosure

The extension stores its profile, selected resume PDF, learned answers, queued events, and optional local-engine token in `chrome.storage.local`. In web-app-only mode, it receives the profile from the hosted app and returns queued events to that app on the matching app page; the extension does not upload this data to a server. In laptop-engine mode, the extension sends the current page URL, posting details, and application-field information needed for lookup and answer generation to the user's own engine at `127.0.0.1:8765`, authenticated with the stored token. It can retrieve the resume from that local engine or use the PDF selected in the popup. The extension does not send data to a project-operated server or the maintainers. The job site receives form information only when the user submits the application themselves. The extension never clicks Submit.

Permission justifications:

- `storage`: retain the profile, selected resume PDF, learned answers, queued events, and optional engine token in the browser's local extension storage.
- `alarms`: check the public internship feed once a day around 8:00 local time and once when the extension is installed.
- `notifications`: show matching new internships from the public feed; clicking the alert opens the hosted tracker.
- `host_permissions` for `https://omar-colab.github.io/internship-engine/feed.json`: read the public internship feed to find new roles matching the user's saved watch fields and places.
- `host_permissions` for `127.0.0.1:8765`: let the extension connect to the local engine the user runs on their computer when they choose laptop-engine mode.
- `host_permissions` for `https://omar-colab.github.io/internship-engine/app/*`: let the extension exchange profile and queued-event messages with the hosted app page.
- Content-script match patterns for supported job-board pages: read and fill supported application fields only after the user visits one of those pages.
- Content-script match pattern for `https://omar-colab.github.io/internship-engine/app/*`: receive the web-app profile and return queued events to the tracker on that app page.

### Draft screenshots

Regenerate these with `uv run python scripts/store_screenshots.py` (Playwright Chromium required). The script seeds a scratch tracker
with fictional data and uses the existing fictional Greenhouse form fixture; it never reads `data/`.

![Today dashboard](../site/store/today.png)
![Jobs for you with role details](../site/store/jobs.png)
![Applications board](../site/store/applications.png)
![Extension panel on a fictional form](../site/store/extension-panel.png)

## Before submitting

1. Confirm the store developer account is owned by the project maintainer and has two-step verification enabled.
2. Upload the ZIP attached to a GitHub Release. The workflow checks that its version matches `extension/manifest.json` and that `manifest.json` is at the ZIP root.
3. Complete the Store Listing and Privacy tabs using the disclosures above, and add real screenshots of the extension on supported pages.
4. Submit for review. Chrome reviews the listing before it can offer one-click installation; use the official [publishing guide](https://developer.chrome.com/docs/webstore/publish/).
5. After approval, add the Chrome Web Store listing link to the repository README and landing page. Do not label a GitHub ZIP as a one-click Chrome install.

Do not commit Web Store API credentials, refresh tokens, or signing keys to this repository.
