# Candidate Analyser

FastAPI dashboard for pulling LMS/candidate data, analysing candidate exam attempts, storing snapshots, and serving both cohort and candidate-specific JSON.

## Run The App

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Big Picture Flow

The app works in four stages:

1. Fetch live data from external APIs.
2. Convert the raw API responses into analysis objects.
3. Store the analysis in files and SQLite.
4. Serve dashboard JSON and candidate-specific JSON through FastAPI endpoints.

In simple terms:

```text
External APIs
  -> app/services/api_client.py
  -> app/services/analytics.py
  -> analysis.json + live_api_corpus.json + analytics.db
  -> app/main.py endpoints
  -> static/js dashboard UI
```

## External APIs Used

The API URLs and fixed ids live in `app/config.py`.

Current important constants:

- `CANDIDATE_ID`: default candidate used for the older single-candidate detailed attempt API.
- `APPLICATION_ID`: LMS application id.
- `EXAM_ID`: default exam id for the configured candidate.
- `TENANT_ID`: tenant id sent to LMS/profile APIs.
- `COURSE_LIST_URL`: LMS course catalog API.
- `ALL_CANDIDATE_ATTEMPTS_URL`: all candidate exam attempt API.
- `CURRENT_CANDIDATE_PROFILE_URL`: candidate EAF/profile API.
- `CANDIDATE_DETAILS_URL`: candidate basic details API.
- `RECOMMENDATION_URL`: ChatGPT/chat API used for enrichment and recommendations.

The main fetcher is `app/services/api_client.py`.

It does these jobs:

- Calls LMS course list.
- Calls all-candidate exam attempts.
- Calls candidate profile and candidate details for each discovered candidate id.
- Keeps the raw API response metadata under `raw_apis`.
- Normalizes awkward API shapes, for example when an API returns JSON inside a string.

## What Gets Stored Where

### `live_api_corpus.json`

This is the raw/live corpus file.

It stores the external API material used for analysis:

- course list
- all candidate attempts
- candidate details
- candidate profile/EAF data
- raw API response metadata

Think of this file as: "What did the APIs give us?"

### `analysis.json`

This is the analysed output file.

It stores:

- all candidate analysis
- candidate rankings
- top performer
- per-candidate attempts
- per-question analysis
- domains
- strengths and weaknesses
- skill radar
- recommended courses
- raw ChatGPT API responses

Think of this file as: "What did we calculate from the API data?"

Important keys:

- `candidate_analyses`: dictionary keyed by candidate id.
- `candidates`: list form of candidate analysis.
- `ranked_candidates`: compact ranking list for dashboard display.
- `attempt_analyses`: every analysed attempt.
- `top_performer`: highest ranked candidate.

### `analytics.db`

This is a local SQLite cache.

The table is created in `app/database.py`:

```text
analytics_snapshots
```

Columns:

- `id`: auto-increment snapshot id.
- `candidate_id`: legacy/default candidate id field.
- `exam_id`: legacy/default exam id field.
- `generated_at`: when the snapshot was produced.
- `payload_json`: the full analysis JSON as text.

The important part is `payload_json`: it contains the entire latest analysis payload. The database is used so the app can still show the dashboard if:

- an external API is slow,
- an external API fails,
- live refresh returns empty data,
- you open the dashboard and do not want to wait for a full live refresh.

So:

```text
analysis.json = latest analysis written as a readable file
analytics.db = latest and historical snapshots used by the backend cache
```

## How Analysis Works

The analysis logic lives in `app/services/analytics.py`.

There are two levels:

### Per-attempt analysis

`build_dashboard_payload(...)` analyses one candidate attempt.

It calculates:

- total marks
- obtained marks
- score percentage
- accuracy
- attempted questions
- correct/incorrect/skipped questions
- time taken
- average time per question
- question status
- selected answer and correct answer
- domain classification
- strengths
- weaknesses
- skill radar
- recommended courses

### Multi-candidate analysis

`build_all_candidate_analysis(...)` groups attempts by candidate id.

It:

- discovers all candidates from `all_candidate_attempts`
- adds the configured/default candidate attempt too
- builds per-attempt analysis for each candidate
- groups attempts under each candidate
- calculates candidate averages
- ranks candidates
- stores the result under `candidate_analyses`

That is why this endpoint works:

```text
GET /api/analysis/candidate/12254
```

The backend is not re-analysing only that candidate from scratch. It loads the all-candidate analysis, then selects:

```text
candidate_analyses["12254"]
```

## How Candidate-Specific APIs Work

The endpoints are in `app/main.py`.

### All analysis

```text
GET /api/analysis/all?force_refresh=true
```

Returns the full analysis document.

### Latest cached analysis

```text
GET /api/analysis/latest
```

Returns the latest saved snapshot from `analytics.db`.

### One candidate

```text
GET /api/analysis/candidate/{candidate_id}
```

Example:

```text
GET /api/analysis/candidate/12254
```

This loads the current analysis payload and extracts one candidate from `candidate_analyses`.

### One candidate's attempts

```text
GET /api/analysis/candidate/{candidate_id}/attempts
```

Example:

```text
GET /api/analysis/candidate/12254/attempts
```

Returns only that candidate's analysed attempt list.

### Dashboard overview

```text
GET /api/dashboard/overview?force_refresh=false&selected_candidate_id=12254
```

This is the main endpoint used by the browser dashboard. It returns a UI-friendly shape:

- overview cards
- top performer panel
- aggregate analysis
- ranked candidates
- selected candidate details
- chart data

The shaping happens in `app/services/aggregate_dashboard.py`.

## Live Data Versus Cache

Many endpoints accept `force_refresh`.

### `force_refresh=true`

The backend tries to call the live external APIs again.

Flow:

```text
call APIs -> rebuild analysis -> write JSON files -> save DB snapshot -> return source="live"
```

Use this when you want the newest possible data.

### `force_refresh=false`

The backend reads the latest snapshot from `analytics.db`.

Flow:

```text
read analytics.db -> return source="cache"
```

Use this when you want a fast dashboard load.

### Why the dashboard sometimes says `live`

It says `live` when the response came from a fresh external API pull.

### Why the dashboard sometimes says `cache`

It says `cache` when the response came from `analytics.db`.

This can happen intentionally when `force_refresh=false`, or automatically when a live refresh fails or returns no usable candidates.

This fallback is handled in `app/main.py` inside `_load_dashboard_payload(...)`.

## What The ChatGPT API Does

The app uses the configured `RECOMMENDATION_URL`, currently:

```text
https://chatgptapi.iecsl.in/api/ChatBot/chat
```

There are two separate uses.

### Skill intelligence

File:

```text
app/services/skill_intelligence.py
```

For each analysed attempt, the app sends a compact prompt containing:

- candidate applied role
- self-reported computer proficiency
- languages
- exam info
- question ids and question text
- existing domain/topic guesses

The prompt asks the ChatGPT API to return strict JSON:

- 5 to 8 skill labels
- primary skill per question
- supporting skills per question
- difficulty label
- difficulty rating from 1 to 5

That result becomes:

- `primary_skill`
- `supporting_skills`
- `difficulty_label`
- `difficulty_rating`
- `skill_radar`

If the ChatGPT API fails, the app uses keyword-based fallback logic.

### Recommendations and courses

File:

```text
app/services/recommendation.py
```

The app first shortlists LMS courses locally using keywords from:

- strengths
- weaknesses
- weak topics
- weak skill radar scores
- applied position

Then it sends the candidate analytics plus the course shortlist to the ChatGPT API.

The prompt asks for strict JSON:

- `recommendations`: 4 concise action items
- `recommended_courses`: 3 to 5 course objects

Each course object should have:

- `course_id`
- `course_name`
- `priority`
- `reason`

If the ChatGPT API fails, the app uses fallback recommendations and fallback course matches.

## Frontend Files

### `templates/index.html`

The dashboard HTML shell.

It contains the page sections:

- hero/header
- summary cards
- top performer
- aggregate analysis
- ranked candidates
- selected candidate
- charts
- recommendations
- question table

### `static/js/api.js`

Small wrapper around browser `fetch`.

It calls:

```text
/api/dashboard/overview
```

### `static/js/dashboard.js`

Main browser UI logic.

It:

- loads dashboard JSON
- fills summary cards
- renders candidate list
- renders selected candidate details
- renders recommendations
- renders the question table
- handles candidate selection clicks
- handles refresh/export buttons

### `static/js/charts.js`

Chart.js rendering logic.

It draws:

- cohort ranking bar chart
- selected candidate skill radar
- selected candidate domain bar chart

### `static/css/styles.css`

All dashboard styling.

## Backend Files

### `app/main.py`

FastAPI entry point.

Responsibilities:

- starts app
- serves dashboard HTML
- serves static files
- exposes JSON endpoints
- decides live versus cache
- writes `analysis.json`
- writes `live_api_corpus.json`
- saves snapshots to `analytics.db`

### `app/config.py`

Central place for:

- API URLs
- tenant/application/candidate ids
- file paths
- dashboard domain labels

### `app/database.py`

SQLite helper.

Responsibilities:

- create `analytics_snapshots`
- save a full analysis snapshot
- fetch latest saved snapshot

### `app/services/api_client.py`

External API client.

Responsibilities:

- call LMS/profile APIs
- parse API responses
- discover candidate ids
- fetch profile/details for each candidate
- return one raw payload for analysis

### `app/services/analytics.py`

Core analysis engine.

Responsibilities:

- analyse questions
- calculate marks/accuracy/time
- classify domains
- build skill radar
- call skill intelligence
- call recommendations
- build all-candidate analysis
- rank candidates

### `app/services/aggregate_dashboard.py`

Dashboard response shaper.

It takes the larger analysis payload and converts it into a smaller structure that is convenient for the UI.

### `app/services/skill_intelligence.py`

ChatGPT API wrapper for skill extraction and question difficulty enrichment.

### `app/services/recommendation.py`

ChatGPT API wrapper for action recommendations and LMS course recommendations.

## Common Commands

Start server:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Get fresh analysis:

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true"
```

Get cached analysis:

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/latest"
```

Get one candidate:

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/12254"
```

Get one candidate's attempts:

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/12254/attempts"
```

Open dashboard:

```text
http://127.0.0.1:8000
```

## Important Mental Model

The external APIs do not directly power every dashboard card.

They provide raw facts. The app then creates its own analysis object.

The candidate-specific endpoint works because the analysis object is structured like this:

```text
analysis.json
  candidate_analyses
    12254
      profile
      summary
      attempts
      primary_attempt
    13104
      profile
      summary
      attempts
      primary_attempt
```

So when you call:

```text
/api/analysis/candidate/12254
```

FastAPI loads the latest analysis payload and returns only candidate `12254`.

The database is not doing complex scoring. It is mainly storing completed analysis snapshots so the dashboard can load quickly and survive API failures.
