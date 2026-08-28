const studentsChart = document.getElementById("studentsChart");

if (studentsChart) {
    const labels = studentsChart.dataset.labels ? JSON.parse(studentsChart.dataset.labels) : ["BSCS", "BSIS", "BLIS"];
    const values = studentsChart.dataset.values ? JSON.parse(studentsChart.dataset.values) : [30, 25, 15];

    new Chart(studentsChart, {
        type: "pie",
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: [
                    "rgba(59, 130, 246, 0.9)",
                    "rgba(236, 72, 153, 0.9)",
                    "rgba(245, 158, 11, 0.9)"
                ],
                borderColor: ["#0b0b0b", "#0b0b0b", "#0b0b0b"],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: "bottom" }
            }
        }
    });
}

const paymentsChart = document.getElementById("paymentsChart");

if (paymentsChart) {
    const labels = paymentsChart.dataset.labels ? JSON.parse(paymentsChart.dataset.labels) : ["1st", "2nd", "Summer"];
    const values = paymentsChart.dataset.values ? JSON.parse(paymentsChart.dataset.values) : [10000, 18000, 4000];

    new Chart(paymentsChart, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Payments",
                data: values,
                backgroundColor: "rgba(59, 130, 246, 0.85)",
                borderColor: "rgba(37, 99, 235, 0.9)",
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}