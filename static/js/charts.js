let chartRegistry = [];

function destroyCharts() {
    chartRegistry.forEach((chart) => chart.destroy());
    chartRegistry = [];
}

function registerChart(chart) {
    chartRegistry.push(chart);
}

export function renderCharts(payload) {
    destroyCharts();

    const domainLabels = payload.domains.map((domain) => domain.domain);
    const domainAccuracy = payload.domains.map((domain) => domain.accuracy);
    const domainTime = payload.domains.map((domain) => domain.average_time_seconds);

    registerChart(
        new Chart(document.getElementById("domainBarChart"), {
            type: "bar",
            data: {
                labels: domainLabels,
                datasets: [
                    {
                        label: "Accuracy %",
                        data: domainAccuracy,
                        borderRadius: 12,
                        backgroundColor: ["#38bdf8", "#0ea5e9", "#22c55e", "#f59e0b", "#a855f7"],
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                    },
                },
            },
        }),
    );

    registerChart(
        new Chart(document.getElementById("domainRadarChart"), {
            type: "radar",
            data: {
                labels: domainLabels,
                datasets: [
                    {
                        label: "Skill Score",
                        data: domainAccuracy,
                        fill: true,
                        backgroundColor: "rgba(56, 189, 248, 0.2)",
                        borderColor: "#38bdf8",
                        pointBackgroundColor: "#38bdf8",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 100,
                    },
                },
            },
        }),
    );

    registerChart(
        new Chart(document.getElementById("accuracyPieChart"), {
            type: "pie",
            data: {
                labels: ["Correct", "Incorrect", "Skipped"],
                datasets: [
                    {
                        data: [
                            payload.summary.correct_answers,
                            payload.summary.incorrect_answers,
                            payload.summary.total_questions - payload.summary.attempted_questions,
                        ],
                        backgroundColor: ["#22c55e", "#ef4444", "#f59e0b"],
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
            },
        }),
    );

    registerChart(
        new Chart(document.getElementById("timeBarChart"), {
            type: "bar",
            data: {
                labels: domainLabels,
                datasets: [
                    {
                        label: "Avg Time (s)",
                        data: domainTime,
                        borderRadius: 12,
                        backgroundColor: "#a855f7",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                    },
                },
            },
        }),
    );
}
