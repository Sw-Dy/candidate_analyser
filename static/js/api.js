export async function fetchDashboard(
    forceRefresh = true,
    selectedCandidateId = null,
    selectedExamId = null,
    filterCandidateId = null,
) {
    const params = new URLSearchParams({ force_refresh: String(forceRefresh) });
    if (selectedCandidateId !== null && selectedCandidateId !== undefined) {
        params.set("selected_candidate_id", String(selectedCandidateId));
    }
    if (filterCandidateId !== null && filterCandidateId !== undefined) {
        params.set("candidate_id", String(filterCandidateId));
    }
    if (selectedExamId !== null && selectedExamId !== undefined) {
        params.set("exam_id", String(selectedExamId));
    }
    const response = await fetch(`/api/dashboard/overview?${params.toString()}`);
    if (!response.ok) {
        let detail = "Failed to load dashboard analytics";
        try {
            const errorBody = await response.json();
            detail = errorBody.detail || detail;
        } catch (error) {
            const errorText = await response.text();
            if (errorText) {
                detail = errorText;
            }
        }
        throw new Error(detail);
    }

    return response.json();
}

export function downloadCsv() {
    window.open("/api/dashboard/export/csv", "_blank");
}
