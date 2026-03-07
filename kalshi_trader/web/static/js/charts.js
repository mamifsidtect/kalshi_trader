function drawEquityCurve(tradeLog) {
  const ctx = document.getElementById('equity-chart');
  if (!ctx) return;
  let running = 0;
  const labels = tradeLog.map((_, i) => `Trade ${i+1}`);
  const data = tradeLog.map(t => { running += t.pnl; return parseFloat(running.toFixed(4)); });

  if (window._equityChart) window._equityChart.destroy();
  window._equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Equity Curve',
        data,
        borderColor: '#4f6ef7',
        backgroundColor: 'rgba(79,110,247,0.1)',
        fill: true,
        tension: 0.2,
        pointRadius: 2,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#e0e0e0' } } },
      scales: {
        x: { ticks: { color: '#8b8ea0' }, grid: { color: '#2d3148' } },
        y: { ticks: { color: '#8b8ea0' }, grid: { color: '#2d3148' } },
      }
    }
  });
}
