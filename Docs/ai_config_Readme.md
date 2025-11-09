PyCharm - ArtazzenDotCom.
./Docs/test.md
<br> Created at: Tuesday, 04 November 2025 21:34.19 

Looking at your `main.py`, here are the environment variables that control AI metadata generation and JSON sidecar file creation:

## AI Metadata Generation

| Environment Variable | Purpose | Default | Valid Values |
|---------------------|---------|---------|--------------|
| **`AI_METADATA_ENABLED`** | Master toggle for AI metadata generation | `True` | `1`, `true`, `yes`, `y`, `on` (enable)<br>`0`, `false`, `no`, `n`, `off` (disable) |
| **`MY_OPENAI_API_KEY`** | OpenAI API key (primary) | None | Your OpenAI API key |
| **`My_OpenAI_APIKey`** | OpenAI API key (legacy fallback) | None | Your OpenAI API key |
| **`OPENAI_IMAGE_METADATA_MODEL`** | Which OpenAI model to use | `gpt-4o-mini` | Any valid OpenAI model name |
| **`OPENAI_IMAGE_METADATA_TEMPERATURE`** | Creativity/randomness of AI responses | `0.6` | Float between `0.0` and `2.0` |
| **`OPENAI_IMAGE_METADATA_MAX_TOKENS`** | Maximum tokens in AI response | `600` | Integer between `16` and `4000` |
| **`OPENAI_TIMEOUT_SECONDS`** | API request timeout | `30` | Float (seconds) |

## JSON Sidecar File Creation

**JSON sidecars are always created** for every image in the `Static/images/` directory. There's no environment variable to disable this behavior—it's fundamental to how the application tracks metadata.

However, the **content** of those JSON files is affected by:
- Whether AI generation is enabled (see `AI_METADATA_ENABLED` above)
- Whether an OpenAI API key is configured

## Example Usage

```shell script
    # Disable AI metadata generation entirely
    export AI_METADATA_ENABLED=false
    
    # Enable AI with custom settings
    export AI_METADATA_ENABLED=true
    export MY_OPENAI_API_KEY="sk-your-key-here"
    export OPENAI_IMAGE_METADATA_MODEL="gpt-4o"
    export OPENAI_IMAGE_METADATA_TEMPERATURE="0.8"
    export OPENAI_IMAGE_METADATA_MAX_TOKENS="800"
```


## Notes

- JSON sidecars are **always** created at `Static/images/<filename>.json` for each image
- If AI is disabled or no API key is provided, sidecars will contain empty/EXIF-only metadata
- The AI settings can also be changed at runtime via the admin dashboard at `/admin/config`
- Runtime config changes are persisted to `ai_config.json`