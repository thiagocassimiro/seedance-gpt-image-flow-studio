# Seedance + GPT Image Flow Studio

A reusable local studio for turning an idea into a short film with creative review, financial controls, and auditable production.

> **Core principle:** catch errors in text before generating images, and catch errors in images before paying for video.

At this stage, the project is configured for local checks and dry-runs. **No paid images or videos are generated automatically. There is no web interface, server, global installation, or automatic approval.**

**Repository name:** `seedance-gpt-image-flow-studio`.

## Quick start from GitHub

```powershell
git clone https://github.com/<your-username>/seedance-gpt-image-flow-studio.git
cd seedance-gpt-image-flow-studio
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python scripts/check_publication.py
python -m unittest discover -s tests -t . -v
```

No credentials are required to clone the repository, validate publication safety, or run offline tests. For production, start with `python -m studio new my-first-film` and complete preflight before any estimate or approval.

## Components

- **Direction:** prompts in `prompts/` for the director, story reviewer, frame reviewer, supervisor, and final reviewer.
- **Images:** integration with the existing `gpt-image` CLI; Flare for `low`-quality drafts and Sunburst for reference-based edits. The model is always explicit and only one image is generated per call.
- **Video:** official BytePlus ModelArk only, using `ARK_API_KEY`, with no intermediaries, model fallback, or automatic retries.
- **Post-production:** Python standard library + FFmpeg/ffprobe. No required Python dependencies or heavy frameworks.
- **Controls:** versioned estimates, unknown prices represented as `null`, independent reviews, hash-bound human approvals, idempotency ledger, and manifest history.

## Local installation

Python 3.11+ is required, plus FFmpeg/ffprobe on PATH for media processing. The `gpt-image` CLI is detected on PATH or at `~/.local/bin/gpt-image.exe`. Missing dependencies are reported but never installed automatically.

### Without installing the package

From this directory in Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m studio --help
```

If `python` is only the Microsoft Store alias, use the executable from your local Python runtime.

### Optional virtual environment inside the project

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\studio.exe --help
```

Nothing is installed globally. Skip this installation if your environment cannot create the local virtual environment or download its local build requirements; the `PYTHONPATH` method requires no installation.

## Create your first project

```powershell
studio new my-first-film
# or, without installing:
python -m studio new my-first-film
```

This creates `projects/my-first-film/` and copies the example configurations to `config/models.json` and `config/pricing.json` inside the film. If the project already exists, nothing is overwritten.

Important initial files:

- `briefing.md`, `requirements.json`, `story.md`, `storyboard.csv`;
- `style/palette.json`, `shots/SHOT-001.json`, `video_prompts/SHOT-001.md`;
- `manifest.json`, `edit_plan.json`, and versioned history;
- directories for references, characters, frames, estimates, reviews, approvals, tasks, clips, QC, costs, and delivery.

A new project contains no approvals, task IDs, or actual costs.

## Free local preflight

```powershell
studio preflight my-first-film
studio status my-first-film
```

Preflight checks:

- the Python runtime and Python on PATH;
- FFmpeg and ffprobe;
- the `gpt-image` CLI;
- only the **presence** of `ARK_API_KEY`, never its value;
- endpoint, region, and model structure in `config/models.json`;
- strict boolean safety settings, rejecting strings such as `"false"`;
- account availability as `not_run`/`unverified_account`, without network access.

The report is saved in `reports/`. No dependencies are installed and no account calls are made.

## Credentials

Only the process calling the API needs the environment variable. This example avoids placing the key in the command:

```powershell
$env:ARK_API_KEY = Read-Host "ARK_API_KEY"
```

Do not create `.env`, store keys in JSON/Markdown, print the variable, or share logs outside your team without review. The image CLI remains responsible for its own credential, as documented by the `gpt-image` skill.

## Safe publication on GitHub

- `projects/*` is ignored by default: films, manifests, task IDs, signed URLs, costs, and approvals must not be published.
- Do not use `git add -f` to bypass `.gitignore`.
- Run `python scripts/check_publication.py` before committing. The checker reports only the file and category, never the suspicious value.
- Review `git status --ignored` and the staged diff before every push.
- Use sanitized summaries in `docs/validation/` to share evidence without local paths or production data.
- `.github/workflows/offline-tests.yml` has read-only permissions, declares no secrets, and runs only publication checks and offline tests.
- Read `SECURITY.md` for safe reporting and credential-exposure response.

## Configured BytePlus models not yet verified in the account

The three IDs came from the supplied examples and use the global endpoint `https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks`:

| Role | ID | Initial state |
|---|---|---|
| Preferred economical pilot model | `dreamina-seedance-2-0-mini-260615` | `unverified_account`, disabled |
| Economical alternative, only through explicit selection | `dreamina-seedance-2-0-fast-260128` | `unverified_account`, disabled |
| Premium, only with justified capability and approved cost | `dreamina-seedance-2-5-260628` | `unverified_account`, disabled |

The Chinese endpoint and guide prices were not reused. Consulted official references: [task creation](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api), [Seedance 2.0 tutorial](https://docs.byteplus.com/en/docs/modelark/seedance-2-0), [Models API](https://docs.byteplus.com/en/docs/modelark/models-api), and [pricing](https://docs.byteplus.com/en/docs/modelark/model-pricing). The retrieved dynamic content did not confirm every parameter; account availability and parameters still require validation.

Before any future paid operation, verify the documentation and account, then manually review the project settings:

- `account_discovery.status`, check date, and available IDs;
- `availability: verified_available` for the selected model;
- `enabled_for_submission: true` only for that model;
- `safety.allow_paid_submissions: true` only after review and estimation;
- supported model parameters, without assuming duration or resolution.

The studio does not switch from Mini to Fast or 2.5 when a model is unavailable.

## Pricing and estimates

`config/pricing.json` starts with `null` prices, meaning **unknown, not free**. Fill prices only from an official source, including currency, effective date, retrieval date, and source URL.

```powershell
studio estimate my-first-film --shot SHOT-001
```

The calculation uses model, resolution, duration, quantity, and attempts:

```text
video = duration × attempts × quantity × price_per_second
images = sum(quantity × price_per_image)
total = video + images, only when every component is known
```

`attempts` is a budget-planning value, not retry authorization. Each real approval/submission covers exactly one generation. Set `image_costs_reconciled: true` only after reconciling `manifest.images`; `image_calls: []` means “no image calls included in this plan,” not “images are free.”

Each estimate is saved as a new version in `estimates/` with its file hash. A missing price or required metadata produces `known: false` and blocks approval.

## Required creative workflow

1. Complete the briefing and requirements.
2. Develop the story and request an independent review using `prompts/story_reviewer.md`.
3. Complete `storyboard.csv` and `style/palette.json`.
4. Create references and character/prop sheets.
5. Describe the first frame, last frame, and intermediate action before generating images.
6. Produce and review frames with identical dimensions and aspect ratio.
7. Write the prompt in `shots/SHOT-001.json` and configure local frames and official URLs.
8. Request an independent frame review using `prompts/frame_reviewer.md`.
9. Produce a known estimate and present model, duration, resolution, quantity, and amount.
10. Only the user records financial approval.
11. Submit one task, recover/download it by ID, then perform QC and post-production.
12. Complete the final review and record lessons learned without deleting previous versions.

### Images: dry-run, estimate, and approval

Draft without references:

```powershell
studio image-dry-run my-first-film --model gpt-image-2.5-flare --quality low --prompt "A cinematic ceramic cup on a wooden table" --output images/draft-v1.png
studio image-estimate my-first-film --model gpt-image-2.5-flare --quality low --prompt "A cinematic ceramic cup on a wooden table" --output images/draft-v1.png
```

After reviewing the estimate, the user runs:

```powershell
studio image-approve my-first-film --model gpt-image-2.5-flare --quality low --prompt "A cinematic ceramic cup on a wooden table" --output images/draft-v1.png --estimate estimates/images/<file>.json --approved-by "Your name" --confirmation "APROVO <estimate-sha256>"
```

`image-submit --approved` accepts only the approval registered for the exact request. An uncertain failure becomes `ambiguous` and prevents another execution. For reference-based edits, use `gpt-image-2.5-sunburst` with `--reference <file>`; Flare rejects references rather than silently switching models.

To reconcile an ambiguous image **without rerunning the CLI**, the user reviews the account and file, then explicitly chooses:

```powershell
# The image was located and the charge/identity was reconciled:
studio reconcile-image my-first-film --key <img1_...> --status completed --output images/ambiguous.png --approved-by "Your name" --evidence "File and charge reconciled"

# Only with evidence that no charge occurred:
studio reconcile-image my-first-film --key <img1_...> --status rejected --approved-by "Your name" --evidence "Invoice confirms no charge" --confirm-no-charge
```

Ambiguous images also block video submissions. Active/ambiguous video tasks block paid images; the lock and ledger are shared.

## Seedance payload dry-run

```powershell
studio dry-run my-first-film --shot SHOT-001
```

The dry-run performs no network requests. It displays:

- the endpoint and method that would be used;
- the payload with credentials and signed URL parameters redacted;
- the exact model, duration, resolution, audio, and watermark settings;
- `first_frame` and `last_frame` roles and references;
- local frame-dimension validation;
- the estimate and currently unknown availability;
- a deterministic idempotency key and payload hash.

Configure local frames in `frames.first_file` and `frames.last_file`. Assets sent to Seedance use `frames.first_url` and `frames.last_url`, restricted to HTTPS on approved hosts. The studio does not publish files to improvised hosts or implement uploads to unofficial services. Making assets available through an official BytePlus method remains a validation step.

## Review and approval before payment

After an independent reviewer produces a real report containing content and an explicit `APROVADO` or `REPROVADO` verdict:

```powershell
studio record-frame-review my-first-film --shot SHOT-001 --reviewer "Independent reviewer" --verdict approved --report reviews/frames/independent-report.md
studio estimate my-first-film --shot SHOT-001
```

The review is bound to the prompt, frames, references, storyboard, and palette. A new review, even with identical content, requires new approval.

**Only after reading the model, duration, resolution, quantity, currency, and estimated cost**, the user runs:

```powershell
studio approve my-first-film --shot SHOT-001 --approved-by "Your name" --confirmation "APROVO <estimate-file-sha256>"
studio submit my-first-film --shot SHOT-001 --approved
```

`submit --approved` **does not create an approval**. It refuses the operation unless all of these are present:

- a prior, valid human approval;
- an approved independent frame review;
- a known, reconciled total estimate;
- matching shot, payload, estimate, review, and approval;
- a verified/enabled model and `allow_paid_submissions: true`;
- `ARK_API_KEY` in the process;
- exactly one attempt/quantity and no other active or ambiguous generation.

Any material change requires a new estimate, review, and approval. Agents must never run `approve` or `image-approve` on the user's behalf.

## Recovery without resubmitting a task

Never repeat `submit` after a timeout, disconnection, HTTP 408/409/425/429/5xx, missing ID response, or local failure after acceptance.

```powershell
# Read-only API call: list candidates without creating a task.
studio tasks my-first-film

# Retrieve an existing task.
studio task my-first-film --task-id <id>

# If the ambiguous state had no task ID, explicitly associate the selected task.
studio task my-first-film --task-id <id> --idempotency-key <stv1_...>

# Download the completed task; repeating this returns the verified existing file.
studio download my-first-film --task-id <id>
```

`recovery_task_id` is reconciled whenever possible. Association through `--idempotency-key` is explicit and auditable; the studio never guesses candidates. API/download redirects are revalidated for HTTPS and allowed hosts. There is no automatic retry or cancellation.

Task IDs, URLs, and states are stored in the manifest for recovery. **Signed URLs can be temporary and sensitive:** keep the manifest and `tasks/` files private; audit logs redact signatures, tokens, and credentials. `ARK_API_KEY` is never persisted.

## Actual costs and reconciliation

Estimates are not invoices. Record actual costs only from official billing evidence:

```powershell
studio record-cost my-first-film --task-id <id> --amount "1.25" --currency USD --source "BytePlus invoice" --reference "<charge-id>"
studio record-cost my-first-film --amount "0.04" --currency USD --source "Image invoice" --reference "<charge-id>"
studio cost-report my-first-film
```

The same invoice/task reference is deduplicated. Reports are saved in `costs/`; incompatible currencies or incomplete entries are not summed.

## Frames, QC, and post-production

`src/studio/frames.py` provides dimension comparison and commands/execution for:

- side-by-side contact sheets;
- frame overlays;
- black-and-white conversion for contrast review;
- frame extraction before and after cuts.

All outputs use `-n` and new filenames. When FFmpeg is available, `studio qc` reads metadata, performs full decoding, and extracts frames. Failures make the aggregate status `incomplete` and return a CLI error. Reports always distinguish:

- technical verification through decoding/metadata;
- static-frame inspection;
- motion and listening **not evaluated**, unless explicit human review is documented.

`edit_plan.json` supports cuts, concatenation, last-frame freeze, light brightness/saturation adjustments, FPS/canvas settings, and Lanczos upscaling. The intermediate master is FFV1/FLAC; delivery is H.264/AAC with BT.709 metadata. Scaling preserves aspect ratio with padding. During real execution, `ffprobe` detects audio and silent clips receive stereo/48 kHz silence.

```powershell
studio assemble my-first-film --dry-run
studio assemble my-first-film
studio qc my-first-film
```

The master is registered before delivery, original hashes are verified, and original clips are never overwritten.

## Offline tests

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python scripts/check_publication.py
python -m unittest discover -s tests -t . -v
```

Tests use mocked transports and subprocesses, block `urlopen`, and never call paid APIs or CLIs. The same validation runs in GitHub Actions without secrets. Coverage includes Windows paths, payloads, redaction, dimensions, costs, approvals, idempotency, ambiguous timeout/HTTP handling, recovery, idempotent downloads, redirects, assembly, missing audio, QC, and invoice reconciliation.

## Current limitations

Separate validation is still required for actual model availability in the account, accepted parameters, official asset hosting, current pricing, real CLI/API calls, behavior of the installed FFmpeg build, and human evaluation of motion/audio. The pilot proposed in `docs/piloto-5s.md` **has not been executed**.
