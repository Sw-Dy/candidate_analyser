# Candidate Analyser

FastAPI dashboard for pulling live LMS/candidate data, analysing candidate exam attempts, and serving both cohort and candidate-specific JSON.

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
3. Write the latest live analysis/debug artifacts to JSON files.
4. Serve dashboard JSON and candidate-specific JSON through FastAPI endpoints.

In simple terms:

```text
External APIs
  -> app/services/api_client.py
  -> app/services/analytics.py
  -> analysis.json + live_api_corpus.json
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

## Live JSON Artifacts

The app always calls the live external APIs for dashboard and analysis endpoints. The JSON files below are overwritten after live analysis builds and are useful for inspection/debugging; they are not used to serve responses.

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

So:

```text
analysis.json = latest live analysis written as a readable file
live_api_corpus.json = latest live raw API corpus written as a readable file
```

## How Analysis Works

The analysis logic lives in `app/services/analytics.py`.

There are two levels:

### Per-attempt analysis

`build_dashboard_payload(...)` analyses one candidate attempt.

It calculates:

- total marks
- obtained marks
- per-question obtained marks from the LMS API when available
- score percentage
- accuracy
- attempted questions
- correct/partial/incorrect/skipped questions
- time taken
- average time per question
- question status
- selected answer and correct answer
- ChatGPT-generated domain and topic labels
- ChatGPT-generated difficulty based on the applied position
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

When a request includes `candidate_id`, the backend still keeps all candidate attempts in the cohort ranking. The candidate id only selects the candidate detail returned by candidate-specific/dashboard endpoints; it does not change `ranked_candidates` or `top_performer`.

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

### Latest live analysis

```text
GET /api/analysis/latest
```

Calls the live APIs and returns a newly built analysis payload.

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

### One candidate's analyses for one exam

```text
GET /api/analysis/candidate/{candidate_id}/exam/{exam_id}
```

Example:

```text
GET /api/analysis/candidate/12254/exam/9
```

Returns a compact candidate/exam payload with:

- basic candidate details
- exam details
- candidate summary for that exam
- attempt summaries
- `questions`, containing all selected-candidate questions with topic, domain, marks, status, answers, and skill labels
- `primary_attempt_id`
- `analyses`, containing compact analysed attempts for that candidate and exam
- `top_performer_analysis`, containing the best-ranked candidate's compact analysis for the same exam

The compact response excludes repeated `student` and `exam` objects inside each attempt, cohort-level `rankings`, `top_performer`, and heavy debug payloads such as `raw_apis`.

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

## Live Data Loading

All dashboard and analysis endpoints call the live external APIs. The older `force_refresh` query parameter is still accepted for backwards compatibility, but it no longer changes how data is loaded.

Flow:

```text
call APIs -> rebuild analysis -> write JSON artifacts -> return source="live"
```

If a live API call fails, the request fails with an error instead of falling back to an older response.

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
- selected answer and correct answer
- per-question obtained marks and full marks

The prompt asks the ChatGPT API to return strict JSON:

- 5 to 8 skill labels
- free-form domain per question
- free-form topic per question
- primary skill per question
- supporting skills per question
- difficulty label based on the candidate's applied role/position
- difficulty rating from 1 to 5

That result becomes:

- `domain`
- `topic`
- `primary_skill`
- `supporting_skills`
- `difficulty_label`
- `difficulty_rating`
- `skill_radar`

Domain, topic, and primary skill labels are ChatGPT-only. The backend validates that the ChatGPT response is specific, retries missing or vague labels through the same ChatGPT URL, and fails the request if usable labels are still not returned. It does not replace missing labels with hardcoded local topic/domain guesses.

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
- always loads live API data
- writes `analysis.json`
- writes `live_api_corpus.json`

### `app/config.py`

Central place for:

- API URLs
- tenant/application/candidate ids
- file paths

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

Get latest live analysis:

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

Get one candidate's analyses for one exam:

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/12254/exam/9"
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

FastAPI rebuilds the live analysis payload and returns only candidate `12254`.

The cohort-level ranking and top performer always come from the full live candidate set for the exam, even when a request selects one candidate for detail display.
