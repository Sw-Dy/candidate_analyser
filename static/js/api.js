export async function fetchDashboard(forceRefresh = true) {
    const response = await fetch(`/api/dashboard/analytics?force_refresh=${forceRefresh}`);
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
