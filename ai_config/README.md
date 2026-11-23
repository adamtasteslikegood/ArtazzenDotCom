# AI model catalog

Shipped data about the models the admin can pick for AI metadata. It is read once at startup by `app/config.py`, which checks it against the schema. A catalog that fails the check is ignored whole: the model dropdown is empty and the log says why.

| File                 | What it is                                                                      |
| -------------------- | ------------------------------------------------------------------------------- |
| `models.json`        | The catalog: model list, list prices, descriptions and allowed efforts.         |
| `models.schema.json` | JSON Schema for the catalog. The app and a test check `models.json` against it. |

The saved admin settings (`ai_config.json`) are a different thing and still live in the repository root. They are written at runtime; this folder is only changed by commits.

## What the catalog drives

- The **Model** dropdown in the admin settings, in the order listed.
- The description and price line under the dropdown, with the `as_of` date.
- Which **Effort** options are enabled for each model. On the server, an effort that is not in a model's `reasoning_efforts` falls back to `low`.
- The cost estimate next to **Max output tokens**.

A model that is saved in the settings but missing from the catalog still works. It shows no description or price, and no effort is blocked for it.

## Fields

Top level:

| Field                              | Meaning                                                           |
| ---------------------------------- | ----------------------------------------------------------------- |
| `as_of`                            | Date (`YYYY-MM-DD`) the prices and efforts were last checked.     |
| `currency`                         | Always `USD`.                                                     |
| `source`                           | Page the model list came from.                                    |
| `estimated_input_tokens_per_image` | Input tokens assumed per request when estimating cost. See below. |
| `models`                           | The model entries.                                                |

Each model:

| Field                   | Meaning                                                                 |
| ----------------------- | ----------------------------------------------------------------------- |
| `id`                    | Model ID sent to the API.                                               |
| `name`                  | Display name, shown in the dropdown with the ID beside it.              |
| `description`           | One or two sentences shown under the dropdown (200 characters at most). |
| `input_price_per_mtok`  | List price per 1M input tokens.                                         |
| `output_price_per_mtok` | List price per 1M output tokens. Reasoning tokens are billed as output. |
| `reasoning_efforts`     | Efforts the admin may choose for this model.                            |
| `source`                | The provider's page for the model.                                      |

## How the cost estimate is worked out

```text
cost per attempt = (estimated_input_tokens_per_image x input price
                    + max output tokens x output price) / 1,000,000
```

It is an upper bound on one request, not a typical cost: most requests stop well short of the output limit. It does not include cached-input discounts or other pricing tiers.

`estimated_input_tokens_per_image` is 1,200. That is the top of the range seen in 11 recorded `gpt-6-luna` requests (773 to 1,202 input tokens for the prompt plus one image resized to 1024 px). Other models may count image tokens differently, so treat it as an estimate.

A new image whose attempt leaves a field empty is retried automatically, up to `AI_MAX_RETRIES` more times, and every attempt is charged. That count is not a hard ceiling: regenerating from the admin page, reopening the image's review page while a field is still empty, and a server restart (which grants a new set of retries) all add attempts.

## Updating

1. Check each model's page (the `source` links) for price and supported efforts.
2. Edit `models.json` and set `as_of` to the day you checked. Re-read every `description`: several compare prices or name the default model, and nothing updates them for you.
3. Run `pytest tests/test_main.py -q` and `npx --yes prettier --check "ai_config/*"`.

To add a model, add an entry; to retire one, remove it. The default model is named separately, as `OPENAI_DEFAULT_MODEL` in `app/config.py`, and must stay in the catalog (a test checks this).

## Known gaps

- Prices are list prices copied by hand on the `as_of` date. Nothing fetches them.

## Last checked against the API

On 2026-11-22 every model and effort combination was sent to the Responses API as a small text request. The API accepted exactly the efforts listed in `models.json`. No listed model accepts `minimal`; the option stays in the form for models outside the catalog.
