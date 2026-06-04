## Get full analysis JSON in terminal

This project already has an API that returns the full analysis JSON directly.

You do **not** need to open the dashboard UI.
You only need to run the FastAPI server and call the endpoint.

### 1) Start the server

From `D:\candidate_analyser`:

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2) Main API for full analysis

This endpoint:

- calls the required LMS APIs
- builds the analysis
- calls the recommendation API
- returns everything in JSON

```text
GET http://127.0.0.1:8000/api/analysis/all?force_refresh=true
```

### 3) Exact curl commands

#### Fetch fresh live analysis

Use `curl.exe` on Windows PowerShell to avoid the PowerShell curl alias issue.

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true"
```

#### Fetch latest cached analysis

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/latest"
```

#### Save fresh live analysis to a JSON file

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true" -o analysis.json
```

#### Save cached analysis to a JSON file

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/latest" -o latest-analysis.json
```

### 4) What you get in the JSON

The response includes the same analysis data shown on the dashboard:

- `student`
- `exam`
- `summary`
- `domains`
- `questions`
- `strengths`
- `weaknesses`
- `recommendations`
- `raw_apis`
- `generated_at`
- `snapshot_id`

### 5) If you want the dashboard wrapper JSON

This endpoint returns the payload inside a `data` object and also includes `source`:

```text
GET http://127.0.0.1:8000/api/dashboard/analytics?force_refresh=true
```

curl:

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/analytics?force_refresh=true"
```

### 6) Useful endpoints

#### Health

```bash
curl.exe "http://127.0.0.1:8000/api/health"
```

#### Full analysis as direct JSON

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true"
```

#### Latest cached analysis

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/latest"
```

#### Dashboard response with `data` and `source`

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/analytics?force_refresh=true"
```

### 7) Important clarification

If by "without the main script" you mean:

- **without opening the HTML dashboard**: yes, this is already supported
- **without running the FastAPI server at all**: no

An API endpoint must be served by the backend process, so `uvicorn app.main:app` still needs to run.

### 8) Recommended command for your use case

If you want all analysis details in JSON directly in terminal, run:

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?force_refresh=true"
```
