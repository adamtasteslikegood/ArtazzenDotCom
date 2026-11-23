# AI prompt guidance on the admin settings page: feature brief

Date: 2026-11-22. Status: pre-spec. This brief records the request, what the code and the OpenAI docs say today, a recommended set of controls, and the questions to answer before a spec is written. No prompt text or guidance code has been changed; the model catalog, the two new efforts and the wider token range landed separately on the same day.

## 1. The request, as written

Kept verbatim so the original voice stays with the feature.

```text
the current setup sends a prompt, along with an image file (or  image link/url ) , to a chatgpt model via the opeai responses api. The prompt, along with any other information passed as a different part of the api request, includes instructions - that, extremely simplified essentially 1. ask  for the model to generate text describing  the image. and 2. formulate (format) the text into a specified  'shape' and respond to our request with stuctured output which we save alongside the image file as a json sidecar... So far the artist/admin's only instrument of creative control over the {stle} of the generated text offered by our app is the choice of which model, effort level and most recently a checkbox that toggles whether to include the artists name in the prompt (before the 'toggle' if the name was set in the admin/settings page - the prompt, and the resuting description incuded the name of the artist) - the temprature, top p, bottom p, etc.  - temprature was there but its has been undergoing depreciation by api endpoints and newer models/request expectations for some time now, to the point where including this param. will result in an error when calling the latest models... The toggle switch probally had the most profound results, and the effort level, and newer models themselves offer a noticable change for one to the next... This prompt is turning into a 2-for, as i invoked the senior-prompt-engineer - my original intention was to describe the feat requests that , for starters would add some more fields to the settings page, allowing the artist to (optionally) specify some guidance in a few key categories.. as well as some more direct settings, such as a list of 'banned' words (disallow list) , and possibly some less final inclusions and exclusions.. I mentioned top p and other params that are not temprature, but might have application as a slider if there still used by the responses api with the gpt6-6.1-6.2 families of models.. I am leaving the details up to your expertiese on the subject as far as what sliders, params, categoires of guidence form fields beyond 'general' and lists besides 'disallowed' words.. the 2for situation i refered too is i intended to use the senior-prompt engineer skill for its expertiese in what goes into a prompt ai request.. and i would like the 'voice' of this original feat request/user story to be included in its 'raw' form.. i would employ your direct advertised 'skill/function' to process this and then extract the points that will go into the feature change, as well as a list of 'grill-me' /gstack/brainstroming style - for the necessary rounds  of questions and ansers to turn this into a well scoped and spec'd ...prd? or the appropriate and not necessarily as formal design-plan doc.. remeber this is just the begging - anaylasing images with ai to curate and classify artwork, including tags and titles and description is a main feature of artazzen.com app - and the gateway too, hopefully cloudflare's content indepence day and the agentic internet 'tools' that have grown popular quickly - md4a, webmcp, and certianly not least 402x micro-blockchain payments though ai-gateways and even micro- agent -2-agent negotiaions .. brought to where its needed - original creators  and contributators of unique quality content - digiatal or digitally shared.. for now the prompt guidence on admin/settings please..;)
```

## 2. What is in scope

In scope, from the request:

- Optional guidance fields on the admin settings page that shape how titles, descriptions, captions and tags are written.
- A banned-word list that is actually enforced.
- Softer include and exclude lists.
- Direct controls (sliders or presets) where the API still offers one that works.

Out of scope for now, named in the request as the longer road: Cloudflare's pay-per-crawl work, markdown for agents, WebMCP, x402 micropayments and agent-to-agent negotiation. One link worth keeping in mind: consistent tags and accurate facts about each work are what those later features will read, so the tag vocabulary in 4.2 and the facts box in 4.1 lean toward consistency.

## 3. Where things stand today

### 3.1 The request the app sends

Built in `app/ai_metadata.py` (`_build_openai_prompt`, `_request_openai_metadata`).

- System message, fixed: "You create concise, visitor-friendly metadata for artwork images."
- User message: one paragraph that names the file, lists any existing title, description, caption and tags (and the artist, if the toggle is on), asks for the missing fields with hard-coded limits (title 80 characters, description 400, caption 160, 3 to 8 tags), and asks for "concise English text suitable for a public art gallery".
- The image, resized to 1024 px on the long edge.
- A strict JSON schema for the output. This is already the right mechanism: the shape is guaranteed by the API, not by the prompt.
- `reasoning.effort` for GPT-5 and GPT-6 models; `temperature` only for older models, which the model list no longer offers.

Baseline from the skill's analyzer on the current prompt, all four fields requested: about 169 tokens, clarity 75, structure 65. The baseline file is in the session scratchpad and should be regenerated when the spec work starts.

### 3.2 What the artist can set today

Model (six GPT-6 models), effort, max output tokens, default artist, the artist-in-prompt toggle, default copyright. `temperature` is still stored and accepted by `POST /admin/config` but has no form field and is never sent for the listed models.

### 3.3 Which request parameters still work

Checked against OpenAI's documentation on 2026-11-22.

| Parameter                                | Status                                                                         | Confidence                                                                        |
| ---------------------------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| `temperature`, `top_p`                   | The GPT-6.2 guide says to omit both from Responses requests.                   | Official for GPT-6.2. Not tested against `gpt-6-luna`, the app default.           |
| `frequency_penalty`, `presence_penalty`  | Not in the Responses create reference at all.                                  | Solid.                                                                            |
| `logit_bias` (the old way to ban tokens) | Not in the Responses create reference.                                         | Solid.                                                                            |
| `text.verbosity`                         | In the reference, with low, medium and high.                                   | Exists. Its effect on short, schema-bound text with character limits is untested. |
| `reasoning.effort`                       | Supported. The `gpt-6-luna` page lists none, low, medium, high, xhigh and max. | Official.                                                                         |

Conclusion: no sampling slider is worth building. A control that errors on some models is worse than none. The controls that still do something are the words in the prompt, the length and count limits, effort, and possibly verbosity.

### 3.4 Findings next to this feature

These were noticed while reading and are not fixed here.

1. **Settings do not survive a deploy.** `CONFIG_PATH` is `ai_config.json` in the repository root, and that file is committed. Saves from the admin page write to the container's disk, so by the code path each Railway deploy starts again from the committed file. I have not confirmed this against production. Short settings are easy to re-enter; paragraphs of guidance are not. Treat moving this file onto the images volume as a prerequisite.
2. **"Reset to defaults" replaces the whole config.** With guidance stored in the same object, one click would erase it.
3. **`minimal` was offered where the API rejects it.** Fixed on 2026-11-22: a live check showed no listed model accepts `minimal`, so it is now blocked for all of them. `xhigh` and `max` were added the same day, and the model list is now driven by `ai_config/models.json`.
4. **`ai_details` cannot take new keys.** The sidecar schema sets `additionalProperties: false` there, and `ai_details.prompt` stores only the user message. Guidance placed in the system message would leave no per-image record unless the schema grows.
5. **The filename is in the prompt.** A name like `IMG_2231.jpg` or `final-v3.png` can leak into titles. Worth testing in a later prompt pass, not here.
6. **Limits are asked for, not enforced.** The prompt asks for 80, 400 and 160 characters, but the code only rejects text above 320, 1600 and 640 (`_FIELD_MAX_LEN`), and a rejection empties the field instead of shortening it. Tag count is not checked at all. A 900-character description is saved as it comes.
7. **An emptied field is retried automatically, and the review page does not say why.** The watcher treats any empty title, description, caption or tag list as missing and tries again, up to `AI_MAX_RETRIES` more times (5 by default), 60 seconds apart, with a fresh budget after each restart. The review templates do not show `ai_details.status` or its error text, so a rejected field looks the same as one that was never generated.

## 4. Recommended controls

The rule used to choose: a control earns a place only if changing it produces a difference the artist can see and a test can check.

### 4.1 Guidance boxes

The model treats two kinds of text differently, so there are two boxes rather than a row of loosely different ones.

- **About the work** (facts the model cannot see). Medium, process, subject matter it tends to misread. Example: "These are digital edits of my own photographs. Never call them paintings or illustrations." The prompt presents this as true background.
- **Voice and style** (how to write). Tone, point of view, what to notice, what to leave alone. Example: "Plain and specific. Describe what is in the frame before any mood. No exclamation marks."

Splitting style further into tone, focus and audience would give the artist more boxes to fill with text that lands in the same place in the prompt. That split is offered as question 3 in case the extra structure helps as a writing aid.

Both boxes are optional and capped in length (suggested 600 characters each). Each goes into the prompt in its own labelled block, ahead of the output rules, so nothing typed there can change the field names, which the schema guarantees. Limits are a weaker story today (finding 6): free text such as "write long, detailed descriptions" could win against a length preset unless the code starts checking the preset itself. Question 7 covers that.

### 4.2 Lists

- **Banned words** (hard). Prompt text alone cannot guarantee a word is absent, and listing words can make them slightly more likely. The guarantee comes from a check on the returned text before anything is saved. The hook is the per-field loop that already rejects malformed values (`_looks_like_stuffed_response`). What happens on a hit is question 4, and finding 7 shapes the answer.
- **Avoid** (soft). Clichés and habits to steer away from ("captivating", "a symphony of", "invites the viewer"). Prompt only, no enforcement.
- **Words to favour in prose** (soft): no separate list. A sentence in Voice and style ("prefer botanical names over common ones") does the same job with less to maintain.
- **Preferred tags** (soft by default). A vocabulary the model should pick from when a term fits. This is the list with the most long-term value because it keeps tags consistent across the gallery. The API can also make it a closed list through the schema, which is a hard guarantee; question 8 covers the trade-off, and whether the schema accepts such a list still needs checking.

### 4.3 Direct controls

- **Description length**: Short, Standard, Long, replacing the hard-coded 400 characters. This is the closest thing to a slider that works on every model.
- **Tag count**: a minimum and maximum, replacing the hard-coded 3 to 8.
- **Verbosity**: a candidate only. Run it at low, medium and high on the test images first; ship it only if the difference is visible.
- **Effort**: already present. The option list is already fixed (finding 3).
- **Temperature and top_p**: not offered, for the reasons in 3.3. Variety between attempts comes from regenerating in preview.

### 4.4 Where each piece goes in the request

| Piece                           | Placement                                                     | Why                                                               |
| ------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------- |
| Role line                       | System message, unchanged                                     | No evidence it needs changing.                                    |
| About the work, Voice and style | Labelled blocks in the user message, before the field request | Recorded per image in `ai_details.prompt` with no schema change.  |
| Avoid list, preferred tags      | Short lines after the guidance blocks                         | Same record; easy to diff.                                        |
| Field names and shape           | JSON schema, unchanged                                        | Guaranteed by the API.                                            |
| Length and count limits         | Prompt text, plus a code check against the chosen preset      | The prompt asks; only a code check can hold the line (finding 6). |
| Banned words                    | Code check after the response                                 | Only code can guarantee absence.                                  |

No examples and no step-by-step reasoning text are added. Current models usually do worse with scaffolding they do not need; add either only if the test images show a failure it fixes.

## 5. How we will know it works

Acceptance criteria for the eventual spec:

1. With every new field empty, the request body is byte-identical to today's. This is the no-regression gate, and it keeps the token and clarity baseline unchanged for artists who use none of this.
2. Each filled field appears in the sent prompt inside its labelled block and nowhere else, and is truncated to its cap.
3. A response containing a banned word is never saved silently (tested with a mocked response).
4. Settings round-trip through `GET` and `POST /admin/config`, survive a restart, and survive a deploy once the file is moved.
5. Existing sidecars change only when the artist regenerates.
6. The settings form stays usable by keyboard and keeps the existing save and error feedback.

Test loop for the wording itself: a fixed set of 10 to 12 images from the local seed set in `test_data/images` (12 images are there now), run through `POST /admin/ai/regenerate` with `preview: true` so nothing is saved. Run once with no guidance to capture today's output, then once per setting. Checks: banned words absent, lengths inside limits, tags drawn from the preferred list when it is set, and the artist's own read of the voice. At the rates on the `gpt-6-luna` model page (0.10 USD per million input tokens, 0.50 per million output), a full pass over the set costs well under a cent; that is an estimate, not a measurement.

Code that will need to change: `_get_ai_config` (it silently drops keys it does not know), `_default_ai_config_from_env`, `_sanitize_ai_config`, `update_admin_config`, `_build_openai_prompt`, the response loop in `_request_openai_metadata`, the settings form and its script in `templates/reviewAddedFiles.html`, and tests in `tests/test_main.py`.

## 6. Questions to settle

One decision each, in dependency order, with a recommended answer.

### Decided on 2026-11-22

- **Question 1:** guidance is gallery-wide in version 1.
- **Question 3:** two boxes, About the work and Voice and style.
- **Question 4:** save and flag. Text containing a banned word is saved as generated and marked for the reviewer; there is no retry. This differs from the recommendation and is simpler: the field is not empty, so the watcher's automatic retry never starts. It leaves three things for the spec:
  - The review page has to show the flag and the word, which it cannot do today (finding 7).
  - The flag needs somewhere to live. `ai_details.status` is a free string, so a new status value avoids a schema change, but the forced-regenerate route treats any status other than `success` as a failure and that check would need adjusting.
  - Regenerating an image that is already approved would put the flagged text on the public site at once. See the new question 17.
- **Question 13:** `ai_config.json` moves onto the images volume inside this feature, not as a separate change. The spec should make it the first commit so it can be reviewed on its own.

### Round 1: shape

1. **Is guidance global, or can a collection override it?** Recommended: global only in version 1, stored so that per-collection overrides can layer on later. A series of stylised edits may want a different voice from botanical studies, but that doubles the settings surface before the basic version has been used.
2. **Which outputs does Voice and style apply to?** Recommended: title, description and caption. Tags are governed by the preferred-tags list and the count range only.
3. **Two guidance boxes, or more?** Recommended: two (About the work, Voice and style). The alternative is four (General, Tone, Focus, About the work), which gives more prompts for the artist but no difference in what the model receives.
4. **What happens when a banned word comes back?** Recommended: retry once with the offending words named; if it happens again, keep the text out of the public field, show it in the review queue with the word highlighted, and stop automatic retries for that image. This needs two small additions, because today an emptied field is retried up to five more times and the review page shows no reason (finding 7). Alternatives: save the text and flag it; or strip the word, which breaks sentences and is not recommended.
5. **How are banned words matched?** Recommended: case-insensitive, whole word or whole phrase, no stemming. The artist lists the variants they care about ("vibrant", "vibrantly").

### Round 2: controls

6. **Length as presets or as a number?** Recommended: three presets (about 200, 400 and 800 characters). A number invites fiddling without a visible difference.
7. **What happens to text that runs past its preset?** Recommended: allow a quarter over, and beyond that retry once asking for a shorter version, then keep the long text for review instead of cutting it mid-sentence. Today nothing happens until four times the limit (finding 6).
8. **Preferred tags: soft or closed?** Recommended: soft, "choose from these when one fits". A closed list guarantees consistency but means a new subject cannot be tagged until the list is edited. Whether the strict schema accepts a fixed list of allowed tag values is not verified yet.
9. **Does verbosity ship?** Recommended: only if the test run shows a clear difference at fixed length limits.
10. **Does new guidance apply to existing artwork?** Recommended: no. It applies to new images and to explicit regeneration.
11. **Should "Reset to defaults" clear guidance?** Recommended: no. Reset covers model, effort and tokens; guidance gets its own clear action with a confirmation.

### Round 3: record and safety

12. **How is the guidance used for an image recorded?** Recommended: inside the stored prompt, by placing guidance in the user message. The alternative is a new `ai_details` field and a schema migration.
13. **Move `ai_config.json` onto the volume as part of this work?** Recommended: yes, as a separate small change that lands first.
14. **What are the caps?** Recommended: 600 characters per guidance box, 50 entries per list, 40 characters per entry. Everything in the two prompt lists is sent with every request and stored in every sidecar's prompt, so at these caps the worst case is about 4,000 extra characters per image.
15. **Can the artist try guidance before saving it?** Recommended: version 1 saves first and uses the existing preview regenerate. A "try on this image" button with unsaved guidance is the natural second step.
16. **Which images form the test set, and who judges voice?** Recommended: the artist picks 10 to 12 that cover the range of the work, and judges voice; the mechanical checks are automated.
17. **What if a banned word turns up when regenerating an image that is already approved?** Recommended: keep the previous public text and hold the new text for review. Save and flag is fine for pending images, which nobody outside the admin can see, but an approved image has no reviewer between the model and the public page.

## 7. Sources

- [Using GPT-6.2 (OpenAI guide)](https://developers.openai.com/api/docs/guides/latest-model): unsupported parameters for Responses requests.
- [Create a model response (OpenAI API reference)](https://developers.openai.com/api/reference/resources/responses/methods/create/): `text.verbosity`, `temperature`, `top_p`; no penalty or `logit_bias` parameters.
- [GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna): effort values, structured output support, pricing.
- [Reasoning models (OpenAI guide)](https://developers.openai.com/api/docs/guides/reasoning): found in search, not read in full.
