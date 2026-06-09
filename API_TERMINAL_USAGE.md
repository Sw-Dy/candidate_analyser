## Get analysis JSON in terminal

This project already exposes FastAPI endpoints for the analysis JSON.

You do **not** need to open the dashboard UI.
You only need to run the backend and call the required endpoint.

### 1) Start the server

From `D:\candidate_analyser`:

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2) Main APIs

The backend now supports:

- all candidates for a selected exam
- one candidate across a selected exam
- candidate + exam specific dashboard filtering

Base endpoints:

```text
GET http://127.0.0.1:8000/api/analysis/all
GET http://127.0.0.1:8000/api/dashboard/analytics
GET http://127.0.0.1:8000/api/dashboard/overview
```

### 3) Supported query parameters

Available parameters:

- `force_refresh=true|false`
- `candidate_id=<candidate id>`
- `exam_id=<exam id>`
- `selected_candidate_id=<candidate id>` for dashboard selection

Examples:

```text
GET /api/analysis/all?force_refresh=true&exam_id=9
GET /api/analysis/all?force_refresh=true&candidate_id=13104&exam_id=9
GET /api/dashboard/overview?force_refresh=true&candidate_id=13104&exam_id=9
```

### 4) Exact curl commands

Use `curl.exe` on Windows PowerShell to avoid the PowerShell curl alias issue.

#### Fetch fresh live analysis for all candidates in one exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true&exam_id=9"
```

#### Fetch fresh live analysis for one candidate in one exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true&candidate_id=13104&exam_id=9"
```

#### Fetch candidate-specific analysis for one exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/13104?force_refresh=true&exam_id=9"
```

#### Fetch candidate-specific attempts for one exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/13104/attempts?force_refresh=true&exam_id=9"
```

#### Fetch dashboard overview for one candidate and one exam

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/overview?force_refresh=true&candidate_id=13104&exam_id=9"
```

#### Fetch dashboard wrapper JSON

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/analytics?force_refresh=true&candidate_id=13104&exam_id=9"
```

#### Fetch latest cached analysis

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/latest"
```

#### Save filtered live analysis to a JSON file

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true&candidate_id=13104&exam_id=9" -o analysis.json
```

### 5) What you get in the JSON

The response includes analysis data such as:

- `candidate_analyses`
- `candidates`
- `ranked_candidates`
- `attempt_analyses`
- `request_context`
- `raw_apis`
- `generated_at`

For detailed attempt payloads you will also see:

- `student`
- `exam`
- `summary`
- `domains`
- `questions`
- `strengths`
- `weaknesses`
- `recommendations`

### 6) Useful endpoints

#### Health

```bash
curl.exe "http://127.0.0.1:8000/api/health"
```

#### Full live analysis without filters

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true"
```

#### Full live analysis for exam only

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true&exam_id=9"
```

#### Full live analysis for candidate + exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true&candidate_id=13104&exam_id=9"
```

#### Dashboard focused on one selected candidate

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/overview?force_refresh=false&selected_candidate_id=13104"
```

#### Dashboard focused on one candidate in one exam

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/overview?force_refresh=true&candidate_id=13104&exam_id=9"
```

### 7) Important clarification

If by "without the main script" you mean:

- **without opening the HTML dashboard**: yes, supported
- **without running the FastAPI server at all**: no

An API endpoint must still be served by the backend process, so `uvicorn app.main:app` needs to run.

### 8) Recommended commands

If you want all candidates for a specific exam:

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true&exam_id=9"
```

If you want one candidate for one specific exam:

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true&candidate_id=13104&exam_id=9"
```
