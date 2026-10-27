# Domain options for the GitHub Pages site

The site is published from the repository's `site/` directory by `.github/workflows/site.yml`. GitHub Pages serves it at `https://omar-colab.github.io` today.

## Options

| Option | Cost | What changes | Tradeoffs |
| --- | --- | --- | --- |
| Keep `omar-colab.github.io` | Free | Nothing | No DNS or renewal. The GitHub Pages address stays visible. |
| `sample.is-a.dev` | Free | Request a subdomain through a pull request to [is-a.dev/register](https://github.com/is-a-dev/register), then point its DNS record at Pages | Community-run and approval-based. Check the current project rules and registration format before preparing a PR. |
| A name under `eu.org` | Free | Request a subdomain through eu.org, then configure the delegation or records they require | Approval and setup can take time; availability and current instructions need checking. |
| A `.com` from Cloudflare Registrar or Porkbun | About US$10/year (estimate; verify current registration and renewal prices) | Register the name, set DNS, and configure it in Pages | Paid renewal. Cloudflare Registrar generally uses Cloudflare DNS; check current eligibility and terms. Porkbun lets you manage DNS there or use another DNS provider. |

The current provider prices, availability, and registration rules have not been checked for this guide. Confirm them before choosing or submitting an application. A free subdomain is not guaranteed until its operator accepts the request.

## is-a.dev request shape

The project has historically accepted registrations as pull requests to `is-a-dev/register`, with one JSON file under `domains/` for the requested label. A request has typically identified the GitHub account owner and a DNS record, for example:

```text
domains/sample.json
```

```json
{
  "owner": {
    "username": "github-handle",
    "email": "maintainer@example.com"
  },
  "record": {
    "CNAME": "omar-colab.github.io"
  }
}
```

This is only an illustrative shape. **Verify the current contribution guide, file schema, eligibility rules, and whether the proposed name is available** in the register repository before opening a PR. The email above is a fictional placeholder; do not copy personal contact information into this repository.

## Connect a custom domain to GitHub Pages

1. Choose the exact hostname first, such as `sample.is-a.dev` or `example.com`. Add that hostname as the only line in `site/CNAME` (no scheme, path, or trailing slash). Because the Pages workflow uploads `site/`, the file will be included in the published artifact.
2. In the repository's GitHub settings, open **Pages** and enter the same hostname under **Custom domain**. Save it. GitHub may create or update the repository's `CNAME` setting/file; keep the source-controlled `site/CNAME` in sync so subsequent deployments retain it.
3. Configure DNS for the chosen hostname:
   - For an apex domain such as `example.com`, create four `A` records for `@`: `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, and `185.199.111.153`.
   - For a subdomain such as `www.example.com` or `sample.is-a.dev`, create a `CNAME` for that subdomain pointing to `omar-colab.github.io` (no protocol or path). If a DNS provider already manages the `is-a.dev` zone, follow its current instructions for adding the record rather than attempting to edit the parent zone directly.
   - Remove conflicting records for the same hostname. DNS providers' controls and propagation times vary.
4. Wait for DNS to resolve, then return to **Settings → Pages**. Once GitHub reports the domain is configured and the certificate is ready, enable **Enforce HTTPS**. Certificate issuance may take some time after DNS is correct.

GitHub Pages DNS targets and setup labels can change. Before changing live DNS, verify these steps against GitHub's current custom-domain documentation and your DNS provider's instructions. The four IPv4 addresses above are the standard GitHub Pages apex `A` records; IPv6 `AAAA` records are optional and are omitted here.
