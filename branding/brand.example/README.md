# Brand: the single source of the product's name and look

Everything that shows the product name or logo reads ONE `brand.json`: the web app (title, sidebar, texts via
`{{brand}}`), the API (`/brand`), messages and notifications, and the agent engine's canvas (built in).

- `branding/brand.example/` (this folder, committed): the neutral public brand.
- `branding/brand.local/` (git-ignored): your organisation's brand. When it exists it wins.

To brand a deployment: copy this folder to `branding/brand.local/` and edit it.

| Field | Meaning |
|---|---|
| `name`, `name_ar` | Product name (English, Arabic) |
| `tagline`, `tagline_ar` | One line under the name |
| `logo` | Logo file in this folder (SVG or PNG) |
| `favicon` | Browser-tab icon file in this folder |
| `theme` | Optional CSS file overriding the colour variables (empty = built-in look) |

The engine canvas takes the brand when its image is built (`.\scripts\dev.ps1 build`); the web app and API read it
when they start.
